# CLAUDE.md — Colonie spatiale

Jeu de gestion « idle » mono-joueur, auto-hébergé sur le serveur maison (voir `~/homelab/CLAUDE.md`).
Langue : **français** partout (interface, code, commentaires, docs, commits).

## Règles du jeu (v1)
- Une colonie, un joueur. Ressources : **oxygène, énergie, nourriture**, plus **matériaux** (construction) et **colons**.
- Bâtiments avec niveaux : panneau solaire, générateur d'O₂, serre, mine, habitat, entrepôt. Améliorer = coût ×~1,6, effet ×~1,5.
- Construction en temps réel, un seul chantier à la fois.
- Pénuries sans game over : énergie à 0 → efficacité réduite ; nourriture à 0 → production −50 % et départs lents ; O₂ à 0 → départs plus rapides. Jamais moins de 2 colons.
- Idle : la progression est rattrapée à partir du temps écoulé (plafond 7 jours), avec un résumé « Pendant ton absence ».
- Objectifs : chaîne de 5 objectifs progressifs récompensés en matériaux (définis dans `app/regles.py`).

## Architecture
- **FastAPI + uvicorn** (1 worker), Python 3.12, image `python:3.12-slim`, utilisateur non-root UID 1000.
- **Aucune boucle serveur** : chaque requête charge l'état, appelle la simulation pure (`app/moteur.py`) jusqu'à « maintenant », applique l'action, sauvegarde.
- **SQLite** (`sqlite3` standard, mode journal classique, pas WAL) : un seul fichier `data/colonie.db`.
- Frontend HTML/CSS/JS vanilla sans build, servi par FastAPI ; PWA (manifest + service worker).

## Réseau et intégrations
- Port **8085** lié à `127.0.0.1` uniquement — **jamais sur 0.0.0.0**.
- Accès : **Tailscale Serve** HTTPS port **8086** → `https://serveur.<tailnet>.ts.net:8086` (tailnet uniquement).
- Homepage : tuile dans `~/homepage/config/services.yaml` (groupe « Loisirs »).
- WUD : `wud.watch=false` (image locale, pas de registre) ; image de base mise à jour par rebuild avec `--pull`.

## Commandes utiles (depuis `~/homelab/colonie`)
```bash
docker compose up -d --build              # construire et lancer
docker compose logs -f colonie            # journaux
docker compose build --pull && docker compose up -d   # mettre à jour l'image de base
curl -s http://127.0.0.1:8085/api/sante   # santé
docker stats --no-stream colonie          # consommation RAM/CPU
```

## Arborescence
```
app/main.py      routes FastAPI
app/moteur.py    simulation pure (à venir)
app/regles.py    données d'équilibrage et objectifs (à venir)
app/stockage.py  SQLite (à venir)
app/static/      interface (à venir)
tests/           pytest (à venir)
data/            colonie.db — non versionné
```

## État d'avancement
- [x] Étape 1 — Initialisation : git, squelette FastAPI (`/api/sante`), Dockerfile, compose
- [ ] Étape 2 — Moteur de simulation + objectifs + tests
- [ ] Étape 3 — API + persistance SQLite
- [ ] Étape 4 — HTTPS via Tailscale Serve (8086)
- [ ] Étape 5 — Interface mobile + PWA
- [ ] Étape 6 — Homepage, WUD, sauvegarde/export/import
- [ ] Étape 7 — Enrichissements (événements, recherche, notifications…)

## Façon de travailler
- Petites étapes testables, un commit par étape (identité `Dhafer84`).
- Expliquer chaque commande avant de la lancer ; demander avant toute modification du système hôte.
- Mettre à jour la section « État d'avancement » à chaque étape.
