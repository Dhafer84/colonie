"""Moteur de simulation de la colonie.

Module **pur** : aucune entrée/sortie, aucune horloge. Le temps est toujours
passé en paramètre (secondes depuis l'époque Unix), ce qui rend tout testable.

L'état de la partie est un simple dictionnaire sérialisable en JSON :
    version, derniere_maj, ressources{}, colons (réel), batiments{id: niveau},
    debloques[], chantier (None ou {batiment, niveau, debut, fin}),
    objectif (indice), sans_penurie (secondes), penuries{ressource: debut}
"""

import copy
import math

from app import regles as R

LIBELLES_PENURIE = {
    "energie": "d'énergie",
    "oxygene": "d'oxygène",
    "nourriture": "de nourriture",
}


class ErreurJeu(Exception):
    """Action refusée par les règles du jeu (message destiné au joueur)."""


# --- Création ----------------------------------------------------------------

def etat_initial(maintenant: float) -> dict:
    depart = copy.deepcopy(R.ETAT_DEPART)
    return {
        "version": 1,
        "derniere_maj": maintenant,
        "ressources": {r: float(v) for r, v in depart["ressources"].items()},
        "colons": float(depart["colons"]),
        "batiments": depart["batiments"],
        "debloques": [b for b, spec in R.BATIMENTS.items() if spec["deblocage"] is None],
        "chantier": None,
        "objectif": 0,
        "sans_penurie": 0.0,
        "penuries": {},
    }


# --- Calculs dérivés ---------------------------------------------------------

def cout(batiment: str, niveau: int) -> int:
    """Coût en matériaux pour atteindre `niveau`."""
    return round(R.BATIMENTS[batiment]["cout_base"] * R.FACTEUR_COUT ** (niveau - 1))


def duree(batiment: str, niveau: int) -> int:
    """Durée de construction (secondes) pour atteindre `niveau`."""
    return round(R.BATIMENTS[batiment]["duree_base"] * R.FACTEUR_DUREE ** (niveau - 1))


def capacite_stockage(etat: dict) -> float:
    return R.STOCKAGE_BASE + R.STOCKAGE_PAR_ENTREPOT * etat["batiments"]["entrepot"]


def capacite_colons(etat: dict) -> float:
    return R.COLONS_BASE + R.COLONS_PAR_HABITAT * etat["batiments"]["habitat"]


def postes_requis(etat: dict) -> int:
    return sum(R.BATIMENTS[b]["postes"] * niv for b, niv in etat["batiments"].items())


def calculer_taux(etat: dict, pas: float = R.PAS_SIMULATION) -> dict:
    """Taux nets par heure de chaque ressource, et état des pénuries.

    `pas` sert à estimer si le stock d'énergie suffit sur la durée du pas.
    """
    stocks = etat["ressources"]
    colons = etat["colons"]
    famine = stocks["nourriture"] <= 0
    asphyxie = stocks["oxygene"] <= 0

    postes = postes_requis(etat)
    eff_ouvriers = 1.0 if postes == 0 else min(1.0, colons / postes)
    mod_travail = eff_ouvriers * (R.MALUS_FAMINE if famine else 1.0)

    actifs = []  # (spec, facteur de production, facteur de consommation)
    production_energie = 0.0
    demande_energie = 0.0
    for b, niv in etat["batiments"].items():
        if niv <= 0:
            continue
        spec = R.BATIMENTS[b]
        f_prod = R.FACTEUR_PRODUCTION ** (niv - 1) * (mod_travail if spec["postes"] else 1.0)
        f_conso = R.FACTEUR_CONSOMMATION ** (niv - 1)
        actifs.append((spec, f_prod, f_conso))
        production_energie += spec["produit"].get("energie", 0) * f_prod
        demande_energie += spec["consomme"].get("energie", 0) * f_conso

    # Efficacité énergétique : part de la demande que l'on peut satisfaire sur ce pas
    heures = pas / 3600
    disponible = stocks["energie"] + production_energie * heures
    besoin = demande_energie * heures
    eff_energie = 1.0 if besoin <= 0 or besoin <= disponible else disponible / besoin

    taux = {r: 0.0 for r in R.RESSOURCES}
    for spec, f_prod, f_conso in actifs:
        alimente = eff_energie if "energie" in spec["consomme"] else 1.0
        for res, v in spec["produit"].items():
            taux[res] += v * f_prod * alimente
        for res, v in spec["consomme"].items():
            taux[res] -= v * f_conso * alimente

    for res, v in R.CONSO_COLON.items():
        taux[res] -= v * colons
    taux["materiaux"] += R.RECUPERATION_MATERIAUX

    return {
        "taux": taux,
        "efficacite_energie": eff_energie,
        "efficacite_ouvriers": eff_ouvriers,
        "postes": postes,
        "famine": famine,
        "asphyxie": asphyxie,
    }


# --- Objectifs ---------------------------------------------------------------

def progression_objectif(etat: dict, objectif: dict) -> tuple[float, float]:
    """(valeur actuelle, valeur cible) d'un objectif."""
    if objectif["type"] == "niveau":
        return etat["batiments"][objectif["batiment"]], objectif["niveau"]
    if objectif["type"] == "colons":
        return math.floor(etat["colons"] + 1e-9), objectif["valeur"]
    if objectif["type"] == "sans_penurie":
        return etat["sans_penurie"], objectif["duree"]
    raise ValueError(f"Type d'objectif inconnu : {objectif['type']}")


def objectif_courant(etat: dict) -> dict | None:
    """Objectif actif avec sa progression, ou None si tous sont accomplis."""
    if etat["objectif"] >= len(R.OBJECTIFS):
        return None
    objectif = R.OBJECTIFS[etat["objectif"]]
    actuel, cible = progression_objectif(etat, objectif)
    return {**objectif, "numero": etat["objectif"] + 1, "actuel": actuel, "cible": cible}


# --- Simulation --------------------------------------------------------------

def _evenement(evenements: list, t: float, type_: str, message: str, **extra) -> None:
    evenements.append({"t": t, "type": type_, "message": message, **extra})


def _avancer(etat: dict, t: float, pas: float, evenements: list) -> None:
    """Fait avancer la colonie de `pas` secondes, sans changement de bâtiment."""
    calcul = calculer_taux(etat, pas)
    heures = pas / 3600
    stocks = etat["ressources"]
    capacite = capacite_stockage(etat)

    for res, v in calcul["taux"].items():
        nouveau = stocks[res] + v * heures
        if v > 0:
            # La production ne dépasse pas la capacité, mais un excédent déjà
            # présent (ex. récompense) n'est pas détruit.
            nouveau = min(nouveau, max(capacite, stocks[res]))
        stocks[res] = max(0.0, nouveau)

    famine, asphyxie = calcul["famine"], calcul["asphyxie"]
    colons = etat["colons"]
    if not famine and not asphyxie and colons < capacite_colons(etat):
        colons = min(capacite_colons(etat), colons + R.CROISSANCE_COLONS * heures)
    taux_depart = (R.DEPART_FAMINE if famine else 0) + (R.DEPART_ASPHYXIE if asphyxie else 0)
    if taux_depart and colons > R.COLONS_MIN:
        colons = R.COLONS_MIN + (colons - R.COLONS_MIN) * math.exp(-taux_depart * heures)
    etat["colons"] = colons

    actives = set()
    if calcul["efficacite_energie"] < 1:
        actives.add("energie")
    if famine:
        actives.add("nourriture")
    if asphyxie:
        actives.add("oxygene")
    for res in sorted(actives - etat["penuries"].keys()):
        etat["penuries"][res] = t
        _evenement(evenements, t, "penurie_debut", f"Pénurie {LIBELLES_PENURIE[res]}", ressource=res)
    for res in sorted(etat["penuries"].keys() - actives):
        debut = etat["penuries"].pop(res)
        _evenement(evenements, t, "penurie_fin", f"Fin de la pénurie {LIBELLES_PENURIE[res]}",
                   ressource=res, debut=debut)
    etat["sans_penurie"] = 0.0 if actives else etat["sans_penurie"] + pas


def _terminer_chantier(etat: dict, t: float, evenements: list) -> None:
    chantier = etat["chantier"]
    if chantier is None or chantier["fin"] > t:
        return
    b, niveau = chantier["batiment"], chantier["niveau"]
    etat["batiments"][b] = niveau
    etat["chantier"] = None
    nom = R.BATIMENTS[b]["nom"]
    message = (f"Construction terminée : {nom}" if niveau == 1
               else f"Amélioration terminée : {nom} niveau {niveau}")
    _evenement(evenements, chantier["fin"], "construction", message, batiment=b, niveau=niveau)


def _verifier_deblocages(etat: dict, t: float, evenements: list) -> None:
    for b, spec in R.BATIMENTS.items():
        condition = spec["deblocage"]
        if condition is None or b in etat["debloques"]:
            continue
        if etat["colons"] + 1e-9 >= condition["colons"]:
            etat["debloques"].append(b)
            _evenement(evenements, t, "deblocage", f"Nouveau bâtiment disponible : {spec['nom']}",
                       batiment=b)


def _verifier_objectifs(etat: dict, t: float, evenements: list) -> None:
    # Boucle : plusieurs objectifs peuvent être déjà remplis à la suite
    while (courant := objectif_courant(etat)) and courant["actuel"] >= courant["cible"]:
        etat["ressources"]["materiaux"] += courant["recompense"]
        etat["objectif"] += 1
        _evenement(evenements, t, "objectif",
                   f"Objectif « {courant['titre']} » accompli : +{courant['recompense']} matériaux",
                   recompense=courant["recompense"])
        # Un objectif « sans pénurie » se compte à partir du moment où il devient actif
        suivant = objectif_courant(etat)
        if suivant and suivant["type"] == "sans_penurie":
            etat["sans_penurie"] = 0.0


def _verifications(etat: dict, t: float, evenements: list) -> None:
    _terminer_chantier(etat, t, evenements)
    _verifier_deblocages(etat, t, evenements)
    _verifier_objectifs(etat, t, evenements)


def simuler(etat: dict, maintenant: float) -> tuple[dict, dict]:
    """Rattrape le temps écoulé depuis `derniere_maj` jusqu'à `maintenant`.

    Renvoie (nouvel état, rapport). L'état d'origine n'est pas modifié.
    Au-delà de ABSENCE_MAX, la colonie « hiberne » : seul le début de
    l'absence est simulé, mais un chantier en cours se termine quand même.
    """
    etat = copy.deepcopy(etat)
    debut = etat["derniere_maj"]
    rapport = {
        "debut": debut,
        "fin": max(debut, maintenant),
        "duree": max(0.0, maintenant - debut),
        "ressources_avant": dict(etat["ressources"]),
        "colons_avant": etat["colons"],
        "evenements": [],
    }
    evenements = rapport["evenements"]

    fin_simulee = min(maintenant, debut + R.ABSENCE_MAX)
    t = debut
    _verifications(etat, t, evenements)
    while t < fin_simulee:
        pas = min(R.PAS_SIMULATION, fin_simulee - t)
        if etat["chantier"]:
            pas = min(pas, etat["chantier"]["fin"] - t)  # > 0 : chantier fini traité avant
        _avancer(etat, t, pas, evenements)
        t += pas
        _verifications(etat, t, evenements)

    if maintenant > fin_simulee:
        _evenement(evenements, fin_simulee, "hibernation",
                   "Absence trop longue : la colonie a hiberné après 7 jours")
        _verifications(etat, maintenant, evenements)

    etat["derniere_maj"] = max(debut, maintenant)
    rapport["ressources_apres"] = dict(etat["ressources"])
    rapport["colons_apres"] = etat["colons"]
    return etat, rapport


# --- Actions du joueur -------------------------------------------------------

def demarrer_construction(etat: dict, batiment: str, maintenant: float) -> dict:
    """Lance la construction (niveau 0 → 1) ou l'amélioration d'un bâtiment.

    L'état doit avoir été simulé jusqu'à `maintenant` au préalable.
    """
    if abs(etat["derniere_maj"] - maintenant) > 1e-6:
        raise ValueError("L'état doit être simulé jusqu'à maintenant avant une action.")
    if batiment not in R.BATIMENTS:
        raise ErreurJeu("Bâtiment inconnu.")
    nom = R.BATIMENTS[batiment]["nom"]
    if etat["chantier"] is not None:
        raise ErreurJeu("Un chantier est déjà en cours.")
    if batiment not in etat["debloques"]:
        raise ErreurJeu(f"Bâtiment pas encore débloqué : {nom}.")
    niveau = etat["batiments"][batiment] + 1
    if niveau > R.NIVEAU_MAX:
        raise ErreurJeu(f"Niveau maximal déjà atteint : {nom}.")
    prix = cout(batiment, niveau)
    if etat["ressources"]["materiaux"] < prix:
        raise ErreurJeu(f"Matériaux insuffisants : il en faut {prix}.")

    etat = copy.deepcopy(etat)
    etat["ressources"]["materiaux"] -= prix
    etat["chantier"] = {
        "batiment": batiment,
        "niveau": niveau,
        "debut": maintenant,
        "fin": maintenant + duree(batiment, niveau),
    }
    return etat


# --- Affichage ---------------------------------------------------------------

def effets(batiment: str, niveau: int) -> dict:
    """Effets nominaux d'un bâtiment à `niveau` (à plein régime, sans pénurie)."""
    spec = R.BATIMENTS[batiment]
    if niveau <= 0:
        return {"produit": {}, "consomme": {}, "postes": 0}
    f_prod = R.FACTEUR_PRODUCTION ** (niveau - 1)
    f_conso = R.FACTEUR_CONSOMMATION ** (niveau - 1)
    resultat = {
        "produit": {r: v * f_prod for r, v in spec["produit"].items()},
        "consomme": {r: v * f_conso for r, v in spec["consomme"].items()},
        "postes": spec["postes"] * niveau,
    }
    if batiment == "habitat":
        resultat["places"] = R.COLONS_PAR_HABITAT * niveau
    if batiment == "entrepot":
        resultat["stockage"] = R.STOCKAGE_PAR_ENTREPOT * niveau
    return resultat


# --- Import ------------------------------------------------------------------

def _nombre(valeur) -> bool:
    return (isinstance(valeur, (int, float)) and not isinstance(valeur, bool)
            and math.isfinite(valeur))


def _entier(valeur) -> bool:
    return isinstance(valeur, int) and not isinstance(valeur, bool)


def valider_etat(etat) -> None:
    """Vérifie qu'un état importé est cohérent ; lève ErreurJeu sinon."""
    def refuser(raison: str):
        raise ErreurJeu(f"Sauvegarde invalide : {raison}.")

    if not isinstance(etat, dict):
        refuser("l'état n'est pas un objet")
    if etat.get("version") != 1:
        refuser("version inconnue")
    attendues = set(etat_initial(0))
    if set(etat) != attendues:
        refuser(f"champs attendus : {', '.join(sorted(attendues))}")
    if not _nombre(etat["derniere_maj"]):
        refuser("date de mise à jour incorrecte")

    ressources = etat["ressources"]
    if not isinstance(ressources, dict) or set(ressources) != set(R.RESSOURCES):
        refuser("liste des ressources incorrecte")
    if not all(_nombre(v) and v >= 0 for v in ressources.values()):
        refuser("quantité de ressource incorrecte")
    if not _nombre(etat["colons"]) or etat["colons"] < 0:
        refuser("nombre de colons incorrect")

    batiments = etat["batiments"]
    if not isinstance(batiments, dict) or set(batiments) != set(R.BATIMENTS):
        refuser("liste des bâtiments incorrecte")
    if not all(_entier(n) and 0 <= n <= R.NIVEAU_MAX for n in batiments.values()):
        refuser("niveau de bâtiment incorrect")
    debloques = etat["debloques"]
    if (not isinstance(debloques, list) or len(set(debloques)) != len(debloques)
            or not set(debloques) <= set(R.BATIMENTS)):
        refuser("bâtiments débloqués incorrects")

    chantier = etat["chantier"]
    if chantier is not None:
        if not isinstance(chantier, dict) or set(chantier) != {"batiment", "niveau", "debut", "fin"}:
            refuser("chantier incorrect")
        if (chantier["batiment"] not in R.BATIMENTS
                or chantier["niveau"] != batiments[chantier["batiment"]] + 1
                or chantier["niveau"] > R.NIVEAU_MAX
                or not (_nombre(chantier["debut"]) and _nombre(chantier["fin"]))
                or chantier["debut"] > chantier["fin"]):
            refuser("chantier incorrect")

    if not _entier(etat["objectif"]) or not 0 <= etat["objectif"] <= len(R.OBJECTIFS):
        refuser("objectif incorrect")
    if not _nombre(etat["sans_penurie"]) or etat["sans_penurie"] < 0:
        refuser("durée sans pénurie incorrecte")
    penuries = etat["penuries"]
    if (not isinstance(penuries, dict) or not set(penuries) <= set(LIBELLES_PENURIE)
            or not all(_nombre(v) for v in penuries.values())):
        refuser("pénuries incorrectes")
