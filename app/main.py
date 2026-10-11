"""Point d'entrée de l'application « Colonie spatiale ».

Aucune boucle serveur : chaque requête charge l'état, le simule jusqu'à
« maintenant », applique l'action éventuelle puis sauvegarde.
"""

import time

from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel

from app import moteur as M
from app import regles as R
from app import stockage as S

app = FastAPI(title="Colonie spatiale", docs_url=None, redoc_url=None)

# Remplacée dans les tests pour maîtriser le temps
horloge = time.time

JOURNAL_AFFICHE = 30


class DemandeConstruction(BaseModel):
    batiment: str


class DemandeNouvellePartie(BaseModel):
    confirmer: bool = False


@app.middleware("http")
async def pas_de_cache_pour_l_api(request, call_next):
    reponse = await call_next(request)
    if request.url.path.startswith("/api/"):
        reponse.headers["Cache-Control"] = "no-store"
    return reponse


# --- Outils ------------------------------------------------------------------

def _mettre_a_jour(conn, maintenant: float) -> tuple[dict, dict]:
    """Charge (ou crée) la partie et la simule jusqu'à `maintenant`."""
    etat = S.charger(conn)
    if etat is None:
        etat = M.etat_initial(maintenant)
    etat, rapport = M.simuler(etat, maintenant)
    S.ajouter_evenements(conn, rapport["evenements"])
    return etat, rapport


def _vue_batiment(etat: dict, b: str) -> dict:
    spec = R.BATIMENTS[b]
    niveau = etat["batiments"][b]
    prochain = None
    if niveau < R.NIVEAU_MAX:
        prochain = {
            "niveau": niveau + 1,
            "cout": M.cout(b, niveau + 1),
            "duree": M.duree(b, niveau + 1),
            "effets": M.effets(b, niveau + 1),
        }
    return {
        "id": b,
        "nom": spec["nom"],
        "description": spec["description"],
        "niveau": niveau,
        "niveau_max": R.NIVEAU_MAX,
        "debloque": b in etat["debloques"],
        "deblocage": spec["deblocage"],
        "effets": M.effets(b, niveau),
        "prochain": prochain,
    }


def _vue(etat: dict, rapport: dict | None, journal: list[dict], maintenant: float) -> dict:
    """Ce dont l'interface a besoin pour s'afficher (et extrapoler entre deux appels)."""
    calcul = M.calculer_taux(etat)
    return {
        "maintenant": maintenant,
        "ressources": etat["ressources"],
        "noms_ressources": R.NOMS_RESSOURCES,
        "capacite": M.capacite_stockage(etat),
        "taux": calcul["taux"],
        "efficacite_energie": calcul["efficacite_energie"],
        "efficacite_ouvriers": calcul["efficacite_ouvriers"],
        "postes": calcul["postes"],
        "colons": etat["colons"],
        "capacite_colons": M.capacite_colons(etat),
        "croissance_colons": R.CROISSANCE_COLONS,
        "batiments": [_vue_batiment(etat, b) for b in R.BATIMENTS],
        "chantier": etat["chantier"],
        "objectif": M.objectif_courant(etat),
        "objectifs_total": len(R.OBJECTIFS),
        "penuries": etat["penuries"],
        "sans_penurie": etat["sans_penurie"],
        "rapport": rapport,
        "journal": journal,
    }


# --- Routes ------------------------------------------------------------------

@app.get("/api/sante")
def sante(response: Response) -> dict:
    """Vérification de bon fonctionnement (utilisée par le HEALTHCHECK Docker)."""
    try:
        S.verifier()
    except Exception as erreur:  # noqa: BLE001 — on veut un 503 lisible, quelle que soit la cause
        response.status_code = 503
        return {"statut": "erreur", "detail": f"Base de données inutilisable : {erreur}"}
    return {"statut": "ok"}


@app.get("/api/etat")
def lire_etat() -> dict:
    maintenant = horloge()
    with S.transaction() as conn:
        etat, rapport = _mettre_a_jour(conn, maintenant)
        S.sauvegarder(conn, etat)
        journal = S.lire_journal(conn, JOURNAL_AFFICHE)
    return _vue(etat, rapport, journal, maintenant)


@app.post("/api/construire")
def construire(demande: DemandeConstruction) -> dict:
    maintenant = horloge()
    with S.transaction() as conn:
        etat, rapport = _mettre_a_jour(conn, maintenant)
        try:
            etat = M.demarrer_construction(etat, demande.batiment, maintenant)
        except M.ErreurJeu as erreur:
            raise HTTPException(status_code=400, detail=str(erreur)) from None
        S.sauvegarder(conn, etat)
        journal = S.lire_journal(conn, JOURNAL_AFFICHE)
    return _vue(etat, rapport, journal, maintenant)


@app.post("/api/nouvelle-partie")
def nouvelle_partie(demande: DemandeNouvellePartie) -> dict:
    if not demande.confirmer:
        raise HTTPException(status_code=400, detail="Confirmation nécessaire pour recommencer.")
    maintenant = horloge()
    with S.transaction() as conn:
        S.effacer(conn)
        etat = M.etat_initial(maintenant)
        S.sauvegarder(conn, etat)
    return _vue(etat, None, [], maintenant)
