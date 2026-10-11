"""Persistance de la partie dans SQLite.

Un seul fichier (`COLONIE_DB`, par défaut `data/colonie.db`), mode journal
classique (pas WAL) : la base reste un fichier unique, simple à copier.

Tables :
    partie  — une seule ligne (id = 1) : l'état du moteur en JSON
    journal — les événements de la simulation (pénuries, constructions…),
              limités aux JOURNAL_MAX plus récents
"""

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

CHEMIN_DEFAUT = "data/colonie.db"
JOURNAL_MAX = 500

SCHEMA = """
CREATE TABLE IF NOT EXISTS partie (
    id   INTEGER PRIMARY KEY CHECK (id = 1),
    etat TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS journal (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    t       REAL NOT NULL,
    type    TEXT NOT NULL,
    message TEXT NOT NULL,
    donnees TEXT NOT NULL
);
"""

# uvicorn exécute les routes synchrones dans plusieurs threads : sans ce verrou,
# deux requêtes simultanées pourraient faire « charger → simuler → sauvegarder »
# en même temps et la seconde écraserait la première.
_verrou = threading.Lock()


def chemin() -> Path:
    return Path(os.environ.get("COLONIE_DB", CHEMIN_DEFAUT))


def _connecter() -> sqlite3.Connection:
    fichier = chemin()
    fichier.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(fichier, isolation_level=None, timeout=10)
    conn.executescript(SCHEMA)
    return conn


@contextmanager
def transaction():
    """Connexion exclusive le temps d'une requête.

    Le verrou protège des autres threads du serveur, BEGIN IMMEDIATE d'un autre
    processus (ex. une sauvegarde). Tout est annulé en cas d'exception.
    """
    with _verrou:
        conn = _connecter()
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")
        finally:
            conn.close()


# --- Partie ------------------------------------------------------------------

def charger(conn: sqlite3.Connection) -> dict | None:
    ligne = conn.execute("SELECT etat FROM partie WHERE id = 1").fetchone()
    return json.loads(ligne[0]) if ligne else None


def sauvegarder(conn: sqlite3.Connection, etat: dict) -> None:
    conn.execute(
        "INSERT INTO partie (id, etat) VALUES (1, ?) "
        "ON CONFLICT (id) DO UPDATE SET etat = excluded.etat",
        (json.dumps(etat, ensure_ascii=False),),
    )


def effacer(conn: sqlite3.Connection) -> None:
    """Supprime la partie et son journal (nouvelle partie)."""
    conn.execute("DELETE FROM partie")
    conn.execute("DELETE FROM journal")


# --- Journal -----------------------------------------------------------------

def ajouter_evenements(conn: sqlite3.Connection, evenements: list[dict]) -> None:
    if not evenements:
        return
    conn.executemany(
        "INSERT INTO journal (t, type, message, donnees) VALUES (?, ?, ?, ?)",
        [
            (ev["t"], ev["type"], ev["message"],
             json.dumps({k: v for k, v in ev.items() if k not in ("t", "type", "message")},
                        ensure_ascii=False))
            for ev in evenements
        ],
    )
    conn.execute(
        "DELETE FROM journal WHERE id <= "
        "(SELECT id FROM journal ORDER BY id DESC LIMIT 1 OFFSET ?)",
        (JOURNAL_MAX,),
    )


def lire_journal(conn: sqlite3.Connection, limite: int = 50) -> list[dict]:
    """Événements les plus récents d'abord."""
    lignes = conn.execute(
        "SELECT t, type, message, donnees FROM journal ORDER BY t DESC, id DESC LIMIT ?",
        (limite,),
    ).fetchall()
    return [{"t": t, "type": type_, "message": message, **json.loads(donnees)}
            for t, type_, message, donnees in lignes]


# --- Santé -------------------------------------------------------------------

def verifier() -> None:
    """Lève une exception si la base n'est pas utilisable."""
    with _verrou:
        conn = _connecter()
        try:
            conn.execute("SELECT 1 FROM partie LIMIT 1").fetchall()
        finally:
            conn.close()
