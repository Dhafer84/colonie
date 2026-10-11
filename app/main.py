"""Point d'entrée de l'application « Colonie spatiale »."""

from fastapi import FastAPI

app = FastAPI(title="Colonie spatiale", docs_url=None, redoc_url=None)


@app.get("/api/sante")
def sante() -> dict:
    """Vérification de bon fonctionnement (utilisée par le HEALTHCHECK Docker)."""
    return {"statut": "ok"}
