"""Tests du moteur de simulation."""

import copy
import json
import time

import pytest

from app import moteur as M
from app import regles as R

T0 = 1_700_000_000.0
H = 3600
JOUR = 24 * H
# À 6 colons la mine se débloque : on la débloque d'avance pour isoler l'effet testé
TOUS = list(R.BATIMENTS)


def etat(**modifs) -> dict:
    """État initial, avec quelques champs modifiés (ressources/bâtiments fusionnés)."""
    e = M.etat_initial(T0)
    for cle, valeur in modifs.items():
        if cle in ("ressources", "batiments"):
            e[cle].update(valeur)
        else:
            e[cle] = valeur
    return e


def types(rapport: dict) -> list[str]:
    return [ev["type"] for ev in rapport["evenements"]]


# --- État et calculs ---------------------------------------------------------

def test_etat_initial_serialisable_en_json():
    e = M.etat_initial(T0)
    assert json.loads(json.dumps(e)) == e


def test_cout_et_duree_par_niveau():
    assert M.cout("serre", 1) == 50
    assert M.cout("serre", 2) == 80
    assert M.duree("serre", 1) == 60
    assert M.duree("serre", 2) == 150


def test_taux_initiaux():
    c = M.calculer_taux(M.etat_initial(T0))
    assert c["taux"]["energie"] == pytest.approx(10 - 3 - 1)
    assert c["taux"]["oxygene"] == pytest.approx(12 - 4 * 2)
    assert c["taux"]["nourriture"] == pytest.approx(-4 * 1.5)
    assert c["taux"]["materiaux"] == pytest.approx(R.RECUPERATION_MATERIAUX)
    assert c["efficacite_energie"] == 1
    assert not c["famine"] and not c["asphyxie"]


def test_manque_de_colons_reduit_la_production():
    e = etat(colons=2.5, batiments={"generateur_o2": 5})  # 5 postes pour 2,5 colons
    c = M.calculer_taux(e)
    assert c["efficacite_ouvriers"] == pytest.approx(0.5)
    production = 12 * R.FACTEUR_PRODUCTION ** 4 * 0.5
    assert c["taux"]["oxygene"] == pytest.approx(production - 2.5 * 2)


# --- Production --------------------------------------------------------------

def test_production_pendant_une_heure():
    # 6 colons = habitat plein : population stable, calcul exact
    e, rapport = M.simuler(etat(colons=6.0, debloques=TOUS), T0 + H)
    assert e["ressources"]["energie"] == pytest.approx(50 + 6)
    assert e["ressources"]["oxygene"] == pytest.approx(100 + 12 - 12)
    assert e["ressources"]["nourriture"] == pytest.approx(60 - 9)
    assert e["ressources"]["materiaux"] == pytest.approx(150 + 3)
    assert e["colons"] == pytest.approx(6)
    assert e["derniere_maj"] == T0 + H
    assert rapport["duree"] == H
    assert rapport["evenements"] == []


def test_la_simulation_ne_modifie_pas_l_etat_d_origine():
    e = M.etat_initial(T0)
    copie = copy.deepcopy(e)
    M.simuler(e, T0 + 5 * H)
    assert e == copie


def test_croissance_des_colons_limitee_par_les_habitats():
    e, _ = M.simuler(etat(ressources={"nourriture": 300}), T0 + 20 * H)
    assert e["colons"] == pytest.approx(M.capacite_colons(e))


def test_capacite_de_stockage():
    e, _ = M.simuler(etat(colons=2.0, ressources={"oxygene": 299.0}), T0 + H)
    assert e["ressources"]["oxygene"] == pytest.approx(300)


def test_un_excedent_n_est_pas_detruit():
    e, _ = M.simuler(etat(ressources={"materiaux": 1000}), T0 + H)
    assert e["ressources"]["materiaux"] == pytest.approx(1000)


# --- Pénuries ----------------------------------------------------------------

def test_penurie_d_energie():
    e0 = etat(colons=6.0, debloques=TOUS, ressources={"energie": 0}, batiments={"panneau_solaire": 0})
    e, rapport = M.simuler(e0, T0 + H)
    # Sans énergie, le générateur ne produit plus : seuls les colons respirent
    assert e["ressources"]["oxygene"] == pytest.approx(100 - 12)
    assert "energie" in e["penuries"]
    assert types(rapport) == ["penurie_debut"]
    assert e["sans_penurie"] == 0


def test_famine_reduit_la_production_et_fait_partir_des_colons():
    e0 = etat(colons=6.0, debloques=TOUS, ressources={"nourriture": 0})
    c = M.calculer_taux(e0)
    assert c["famine"]
    assert c["taux"]["oxygene"] == pytest.approx(12 * R.MALUS_FAMINE - 12)
    e, rapport = M.simuler(e0, T0 + 10 * H)
    assert R.COLONS_MIN < e["colons"] < 6
    assert {"ressource": "nourriture", "type": "penurie_debut"}.items() <= rapport["evenements"][0].items()


def test_jamais_moins_que_le_noyau_de_colons():
    e0 = etat(colons=6.0, debloques=TOUS, ressources={"oxygene": 0, "nourriture": 0},
              batiments={"generateur_o2": 0})
    e, _ = M.simuler(e0, T0 + 7 * JOUR)
    assert R.COLONS_MIN <= e["colons"] < R.COLONS_MIN + 0.01


def test_fin_de_penurie_quand_le_chantier_se_termine():
    e0 = etat(colons=6.0, debloques=TOUS, ressources={"energie": 0}, batiments={"panneau_solaire": 0})
    e0 = M.demarrer_construction(e0, "panneau_solaire", T0)
    e, rapport = M.simuler(e0, T0 + H)
    assert types(rapport) == ["penurie_debut", "construction", "penurie_fin"]
    fin = rapport["evenements"][2]
    assert fin["ressource"] == "energie" and fin["debut"] == T0
    assert e["penuries"] == {}


# --- Rattrapage hors ligne ---------------------------------------------------

def test_une_longue_absence_equivaut_a_plusieurs_visites():
    e_long, r_long = M.simuler(M.etat_initial(T0), T0 + 12 * H)
    e_court = M.etat_initial(T0)
    evenements = []
    for h in range(1, 13):
        e_court, r = M.simuler(e_court, T0 + h * H)
        evenements += r["evenements"]
    for res in R.RESSOURCES:
        assert e_court["ressources"][res] == pytest.approx(e_long["ressources"][res])
    assert e_court["colons"] == pytest.approx(e_long["colons"])
    assert evenements == r_long["evenements"]  # dont la famine qui démarre


def test_plafond_d_absence_de_7_jours():
    e7, _ = M.simuler(M.etat_initial(T0), T0 + 7 * JOUR)
    e30, rapport = M.simuler(M.etat_initial(T0), T0 + 30 * JOUR)
    assert e30["ressources"] == pytest.approx(e7["ressources"])
    assert e30["derniere_maj"] == T0 + 30 * JOUR
    assert "hibernation" in types(rapport)


def test_un_chantier_se_termine_meme_pendant_l_hibernation():
    e0 = etat(chantier={"batiment": "habitat", "niveau": 2, "debut": T0, "fin": T0 + 10 * JOUR})
    e, rapport = M.simuler(e0, T0 + 30 * JOUR)
    assert e["batiments"]["habitat"] == 2
    assert e["chantier"] is None
    construction = [ev for ev in rapport["evenements"] if ev["type"] == "construction"]
    assert construction[0]["t"] == T0 + 10 * JOUR


def test_simuler_sans_temps_ecoule_ne_change_rien():
    e0 = M.etat_initial(T0)
    e, rapport = M.simuler(e0, T0)
    assert e == e0 and rapport["evenements"] == []


def test_performance_7_jours():
    debut = time.perf_counter()
    M.simuler(M.etat_initial(T0), T0 + 7 * JOUR)
    assert time.perf_counter() - debut < 2


# --- Construction ------------------------------------------------------------

def test_construction_deduit_le_cout_et_se_termine_a_l_heure():
    e = M.demarrer_construction(M.etat_initial(T0), "serre", T0)
    assert e["ressources"]["materiaux"] == 150 - 50
    assert e["chantier"]["fin"] == T0 + 60

    avant, _ = M.simuler(e, T0 + 59)
    assert avant["batiments"]["serre"] == 0

    apres, rapport = M.simuler(e, T0 + 60)
    assert apres["batiments"]["serre"] == 1
    assert apres["chantier"] is None
    assert types(rapport) == ["construction", "objectif"]
    assert rapport["evenements"][0]["message"] == "Construction terminée : Serre"


def test_amelioration_message_et_niveau():
    e = M.demarrer_construction(M.etat_initial(T0), "panneau_solaire", T0)
    assert e["chantier"]["niveau"] == 2
    e, rapport = M.simuler(e, T0 + M.duree("panneau_solaire", 2))
    assert e["batiments"]["panneau_solaire"] == 2
    assert rapport["evenements"][0]["message"] == "Amélioration terminée : Panneau solaire niveau 2"


@pytest.mark.parametrize("modifs, batiment, message", [
    ({"ressources": {"materiaux": 10}}, "serre", "Matériaux insuffisants"),
    ({"chantier": {"batiment": "serre", "niveau": 1, "debut": T0, "fin": T0 + 60}},
     "habitat", "déjà en cours"),
    ({}, "mine", "pas encore débloqué"),
    ({"batiments": {"habitat": R.NIVEAU_MAX}, "ressources": {"materiaux": 10**9}},
     "habitat", "Niveau maximal"),
    ({}, "fusee", "inconnu"),
])
def test_construction_refusee(modifs, batiment, message):
    with pytest.raises(M.ErreurJeu, match=message):
        M.demarrer_construction(etat(**modifs), batiment, T0)


def test_construction_exige_un_etat_a_jour():
    with pytest.raises(ValueError):
        M.demarrer_construction(M.etat_initial(T0), "serre", T0 + 10)


# --- Déblocages et objectifs -------------------------------------------------

def test_deblocage_de_la_mine_a_6_colons():
    e, rapport = M.simuler(etat(colons=5.9), T0 + H)
    assert "mine" in e["debloques"]
    assert "deblocage" in types(rapport)
    M.demarrer_construction(e, "mine", T0 + H)  # ne lève pas d'erreur


def test_objectifs_deja_remplis_s_enchainent():
    e, rapport = M.simuler(etat(batiments={"serre": 1, "panneau_solaire": 2}), T0 + 1)
    assert e["objectif"] == 2
    assert types(rapport) == ["objectif", "objectif"]
    assert e["ressources"]["materiaux"] == pytest.approx(150 + 50 + 100, abs=0.01)
    assert M.objectif_courant(e)["titre"] == "Sous la surface"


def test_objectif_colons():
    e = etat(objectif=3, colons=9.9, batiments={"habitat": 2}, ressources={"nourriture": 300})
    e, rapport = M.simuler(e, T0 + H)
    assert e["objectif"] == 4
    assert rapport["evenements"][-1]["recompense"] == 300


def test_objectif_24h_sans_penurie_puis_plus_d_objectif():
    e = etat(objectif=4, sans_penurie=24 * H - 30)
    e, rapport = M.simuler(e, T0 + 60)
    assert e["objectif"] == 5
    assert rapport["evenements"][-1]["recompense"] == 500
    assert M.objectif_courant(e) is None


def test_le_compteur_sans_penurie_demarre_avec_l_objectif():
    e = etat(objectif=3, colons=9.9, batiments={"habitat": 2}, ressources={"nourriture": 300},
             sans_penurie=30 * H)
    e, _ = M.simuler(e, T0 + H)
    assert e["objectif"] == 4  # « Une vraie colonie » accompli, pas « Autonomie »
    assert e["sans_penurie"] < H


def test_une_penurie_remet_le_compteur_a_zero():
    e = etat(objectif=4, sans_penurie=20 * H, ressources={"nourriture": 0})
    e, _ = M.simuler(e, T0 + 60)
    assert e["sans_penurie"] == 0
    assert e["objectif"] == 4
