"""Tests de l'API et de la persistance SQLite."""

import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import main
from app import regles as R
from app import stockage as S

T0 = 1_700_000_000.0
H = 3600


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Client de test avec une base temporaire et une horloge réglable (client.t)."""
    monkeypatch.setenv("COLONIE_DB", str(tmp_path / "colonie.db"))
    c = TestClient(main.app)
    c.t = T0
    monkeypatch.setattr(main, "horloge", lambda: c.t)
    return c


def ok(reponse) -> dict:
    assert reponse.status_code == 200, reponse.text
    return reponse.json()


def batiment(vue: dict, b: str) -> dict:
    return next(x for x in vue["batiments"] if x["id"] == b)


# --- Santé -------------------------------------------------------------------

def test_sante(client):
    assert ok(client.get("/api/sante")) == {"statut": "ok"}


def test_sante_signale_une_base_inutilisable(client, tmp_path, monkeypatch):
    (tmp_path / "pas_une_base.db").write_text("ceci n'est pas une base SQLite " * 100)
    monkeypatch.setenv("COLONIE_DB", str(tmp_path / "pas_une_base.db"))
    reponse = client.get("/api/sante")
    assert reponse.status_code == 503
    assert reponse.json()["statut"] == "erreur"


# --- Lecture -----------------------------------------------------------------

def test_premiere_visite_cree_la_partie(client, tmp_path):
    vue = ok(client.get("/api/etat"))
    assert vue["colons"] == R.ETAT_DEPART["colons"]
    assert vue["ressources"]["materiaux"] == 150
    assert vue["capacite"] == R.STOCKAGE_BASE
    assert vue["objectif"]["numero"] == 1
    assert vue["chantier"] is None
    assert len(vue["batiments"]) == len(R.BATIMENTS)
    serre = batiment(vue, "serre")
    assert serre["niveau"] == 0 and serre["debloque"]
    assert serre["prochain"] == {"niveau": 1, "cout": 50, "duree": 60,
                                 "effets": {"produit": {"nourriture": 10, "oxygene": 2},
                                            "consomme": {"energie": 3}, "postes": 1}}
    assert not batiment(vue, "mine")["debloque"]
    assert (tmp_path / "colonie.db").exists()


def test_l_api_n_est_pas_mise_en_cache(client):
    assert client.get("/api/etat").headers["cache-control"] == "no-store"


def test_le_temps_passe_entre_deux_visites(client):
    ok(client.get("/api/etat"))
    client.t = T0 + H
    vue = ok(client.get("/api/etat"))
    # Taux initial d'oxygène : +12 (générateur) − 4 colons × 2 = +4/h (les colons
    # grandissent un peu pendant l'heure, d'où l'approximation)
    assert vue["ressources"]["oxygene"] == pytest.approx(104, abs=0.5)
    assert vue["rapport"]["duree"] == H
    assert vue["rapport"]["ressources_avant"]["oxygene"] == 100


def test_la_partie_est_sauvegardee_dans_sqlite(client):
    ok(client.get("/api/etat"))
    ok(client.post("/api/construire", json={"batiment": "serre"}))
    with S.transaction() as conn:
        etat = S.charger(conn)
    assert etat["chantier"]["batiment"] == "serre"
    assert etat["ressources"]["materiaux"] == 100


# --- Construction ------------------------------------------------------------

def test_construire(client):
    vue = ok(client.post("/api/construire", json={"batiment": "serre"}))
    assert vue["ressources"]["materiaux"] == 100
    assert vue["chantier"] == {"batiment": "serre", "niveau": 1, "debut": T0, "fin": T0 + 60}


@pytest.mark.parametrize("corps, message", [
    ({"batiment": "fusee"}, "Bâtiment inconnu."),
    ({"batiment": "mine"}, "Bâtiment pas encore débloqué : Mine."),
])
def test_construction_refusee(client, corps, message):
    reponse = client.post("/api/construire", json=corps)
    assert reponse.status_code == 400
    assert reponse.json()["detail"] == message


def test_un_seul_chantier_a_la_fois(client):
    ok(client.post("/api/construire", json={"batiment": "serre"}))
    reponse = client.post("/api/construire", json={"batiment": "panneau_solaire"})
    assert reponse.status_code == 400
    assert reponse.json()["detail"] == "Un chantier est déjà en cours."


def test_une_action_refusee_ne_modifie_rien(client):
    ok(client.post("/api/construire", json={"batiment": "serre"}))
    client.post("/api/construire", json={"batiment": "serre"})
    vue = ok(client.get("/api/etat"))
    assert vue["ressources"]["materiaux"] == 100


def test_fin_de_chantier_objectif_et_journal(client):
    ok(client.post("/api/construire", json={"batiment": "serre"}))
    client.t = T0 + 61
    vue = ok(client.get("/api/etat"))
    assert batiment(vue, "serre")["niveau"] == 1
    assert vue["chantier"] is None
    assert vue["objectif"]["numero"] == 2
    assert vue["ressources"]["materiaux"] == pytest.approx(100 + 50 + 3 * 61 / H)
    assert [ev["type"] for ev in vue["journal"]] == ["objectif", "construction"]
    assert vue["journal"][1]["batiment"] == "serre"
    assert vue["rapport"]["evenements"][0]["type"] == "construction"


def test_journal_limite(client, monkeypatch):
    monkeypatch.setattr(S, "JOURNAL_MAX", 3)
    with S.transaction() as conn:
        S.ajouter_evenements(conn, [{"t": T0 + i, "type": "test", "message": f"n°{i}"}
                                    for i in range(10)])
        journal = S.lire_journal(conn)
    assert [ev["message"] for ev in journal] == ["n°9", "n°8", "n°7"]


# --- Nouvelle partie ---------------------------------------------------------

def test_nouvelle_partie_demande_confirmation(client):
    ok(client.post("/api/construire", json={"batiment": "serre"}))
    assert client.post("/api/nouvelle-partie", json={}).status_code == 400
    assert ok(client.get("/api/etat"))["chantier"] is not None


def test_nouvelle_partie(client):
    ok(client.post("/api/construire", json={"batiment": "serre"}))
    client.t = T0 + 120
    ok(client.get("/api/etat"))
    vue = ok(client.post("/api/nouvelle-partie", json={"confirmer": True}))
    assert vue["chantier"] is None and vue["journal"] == []
    assert batiment(vue, "serre")["niveau"] == 0
    vue = ok(client.get("/api/etat"))
    assert vue["journal"] == [] and vue["ressources"]["materiaux"] == 150


# --- Stockage ----------------------------------------------------------------

def test_base_en_mode_journal_classique(client, tmp_path):
    ok(client.get("/api/etat"))
    with sqlite3.connect(tmp_path / "colonie.db") as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"


def test_transaction_annulee_en_cas_d_erreur(client):
    ok(client.get("/api/etat"))
    with pytest.raises(RuntimeError):
        with S.transaction() as conn:
            S.effacer(conn)
            raise RuntimeError("panne")
    with S.transaction() as conn:
        assert S.charger(conn) is not None


def test_requetes_simultanees_serialisees(client):
    """Sans verrou, des « charger → modifier → sauvegarder » concurrents perdraient des mises à jour."""
    import threading
    import time

    with S.transaction() as conn:
        S.sauvegarder(conn, {"compteur": 0})

    def incrementer():
        with S.transaction() as conn:
            etat = S.charger(conn)
            time.sleep(0.005)
            S.sauvegarder(conn, {"compteur": etat["compteur"] + 1})

    fils = [threading.Thread(target=incrementer) for _ in range(10)]
    for f in fils:
        f.start()
    for f in fils:
        f.join()
    with S.transaction() as conn:
        assert S.charger(conn) == {"compteur": 10}


# --- Interface ---------------------------------------------------------------

def test_interface_servie(client):
    reponse = client.get("/")
    assert reponse.status_code == 200
    assert "Colonie spatiale" in reponse.text


@pytest.mark.parametrize("chemin, type_", [
    ("/app.js", "javascript"),
    ("/style.css", "text/css"),
    ("/sw.js", "javascript"),
    ("/manifest.webmanifest", "application/manifest+json"),
    ("/icones/icone-192.png", "image/png"),
])
def test_fichiers_de_la_pwa(client, chemin, type_):
    reponse = client.get(chemin)
    assert reponse.status_code == 200
    assert type_ in reponse.headers["content-type"]


def test_route_api_inconnue(client):
    assert client.get("/api/inexistante").status_code == 404


# --- Export / import ---------------------------------------------------------

def test_export(client):
    ok(client.post("/api/construire", json={"batiment": "serre"}))
    client.t = T0 + 120
    reponse = client.get("/api/export")
    assert reponse.status_code == 200
    assert "attachment" in reponse.headers["content-disposition"]
    donnees = reponse.json()
    assert donnees["format"] == main.FORMAT_EXPORT
    assert donnees["etat"]["derniere_maj"] == T0 + 120
    assert donnees["etat"]["batiments"]["serre"] == 1
    assert [ev["type"] for ev in donnees["journal"]] == ["objectif", "construction"]


def test_export_puis_import(client):
    ok(client.post("/api/construire", json={"batiment": "serre"}))
    client.t = T0 + 120
    export = client.get("/api/export").json()
    ok(client.post("/api/nouvelle-partie", json={"confirmer": True}))

    client.t = T0 + 120 + H
    vue = ok(client.post("/api/import", json=export))
    assert batiment(vue, "serre")["niveau"] == 1
    assert vue["objectif"]["numero"] == 2
    # L'heure écoulée depuis l'export est rattrapée
    assert vue["rapport"]["duree"] == H
    assert [ev["type"] for ev in vue["journal"]] == ["import", "objectif", "construction"]


def test_import_d_un_fichier_quelconque(client):
    reponse = client.post("/api/import", json={"bonjour": 1})
    assert reponse.status_code == 400
    assert reponse.json()["detail"] == "Ce fichier n'est pas un export de la Colonie spatiale."


@pytest.mark.parametrize("modifier, raison", [
    (lambda e: e.update(version=2), "version inconnue"),
    (lambda e: e.pop("colons"), "champs attendus"),
    (lambda e: e["ressources"].update(oxygene=-5), "quantité de ressource incorrecte"),
    (lambda e: e["ressources"].update(oxygene="beaucoup"), "quantité de ressource incorrecte"),
    (lambda e: e["batiments"].update(serre=11), "niveau de bâtiment incorrect"),
    (lambda e: e["batiments"].update(serre=1.5), "niveau de bâtiment incorrect"),
    (lambda e: e["batiments"].pop("mine"), "liste des bâtiments incorrecte"),
    (lambda e: e.update(debloques=["fusee"]), "bâtiments débloqués incorrects"),
    (lambda e: e.update(chantier={"batiment": "serre", "niveau": 3, "debut": 0, "fin": 1}),
     "chantier incorrect"),
    (lambda e: e.update(objectif=99), "objectif incorrect"),
    (lambda e: e.update(penuries={"materiaux": 0}), "pénuries incorrectes"),
    (lambda e: e.update(derniere_maj=T0 + 10 * H), "datée du futur"),
])
def test_import_refuse_un_etat_incoherent(client, modifier, raison):
    export = client.get("/api/export").json()
    modifier(export["etat"])
    reponse = client.post("/api/import", json=export)
    assert reponse.status_code == 400
    assert raison in reponse.json()["detail"]
    # La partie en cours n'est pas touchée
    assert ok(client.get("/api/etat"))["ressources"]["materiaux"] == 150


def test_import_refuse_un_journal_incorrect(client):
    export = client.get("/api/export").json()
    export["journal"] = [{"t": "hier"}]
    assert client.post("/api/import", json=export).status_code == 400


# --- Sauvegarde de la base ---------------------------------------------------

def test_sauvegarde_de_la_base(client, tmp_path):
    from app import sauvegarde

    ok(client.post("/api/construire", json={"batiment": "serre"}))
    fichiers = [sauvegarde.sauvegarder(garder=3) for _ in range(5)]
    restants = sorted((tmp_path / "sauvegardes").glob("*.db"))
    assert restants == fichiers[-3:]
    with sqlite3.connect(restants[-1]) as conn:
        etat = json.loads(conn.execute("SELECT etat FROM partie").fetchone()[0])
    assert etat["chantier"]["batiment"] == "serre"
