"""Sauvegarde de la base SQLite, à lancer depuis l'hôte (ex. par cron) :

    docker compose exec -T colonie python -m app.sauvegarde

Copie cohérente (API de sauvegarde de SQLite, même si le jeu tourne) dans
`sauvegardes/` à côté de la base, en ne gardant que les plus récentes.
"""

import argparse
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

from app import stockage as S

GARDER = 14


def sauvegarder(dossier: Path | None = None, garder: int = GARDER) -> Path:
    source = S.chemin()
    if not source.exists():
        raise FileNotFoundError(f"Base introuvable : {source}")
    dossier = dossier or source.parent / "sauvegardes"
    dossier.mkdir(parents=True, exist_ok=True)
    # Microsecondes dans le nom : ordre alphabétique = ordre chronologique, sans collision
    destination = dossier / datetime.now().strftime("colonie-%Y%m%d-%H%M%S-%f.db")

    with closing(sqlite3.connect(source)) as src, closing(sqlite3.connect(destination)) as dst:
        src.backup(dst)

    anciennes = sorted(dossier.glob("colonie-*.db"))[:-garder]
    for fichier in anciennes:
        fichier.unlink()
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description="Sauvegarde de la base de la colonie.")
    parser.add_argument("--garder", type=int, default=GARDER,
                        help=f"nombre de sauvegardes conservées (défaut : {GARDER})")
    args = parser.parse_args()
    print(f"Sauvegarde créée : {sauvegarder(garder=max(1, args.garder))}")


if __name__ == "__main__":
    main()
