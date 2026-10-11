# CLAUDE.md — Colonie spatiale

Jeu de gestion « idle » mono-joueur, auto-hébergé sur le serveur maison.

Contexte du serveur (copie de `~/homelab/CLAUDE.md`, à resynchroniser si l'original change) :
Langue : **français** partout (interface, code, commentaires, docs, commits).

## Règles du jeu (v1)
Tous les chiffres sont dans `app/regles.py` (taux par heure, durées en secondes).
- Une colonie, un joueur. Ressources : **oxygène, énergie, nourriture, matériaux** (stock plafonné : 300 + 250 par niveau d'entrepôt), et **colons**.
- Bâtiments : panneau solaire, générateur d'O₂, serre, mine (débloquée à 6 colons), habitat (2 + 4 places par niveau), entrepôt. Niveau n : coût ×1,6ⁿ⁻¹, durée ×2,5ⁿ⁻¹, production ×1,5ⁿ⁻¹, conso d'énergie ×1,3ⁿ⁻¹. Niveau max 10.
- **Postes** : générateur d'O₂, serre et mine demandent 1 colon par niveau ; s'il en manque, ils produisent au prorata.
- Colons : consomment 2 O₂ + 1,5 nourriture /h ; +0,25 colon/h s'il y a de la place et ni famine ni asphyxie.
- Construction en temps réel, un seul chantier à la fois, payée en matériaux. +3 matériaux/h de récupération (évite tout blocage).
- Pénuries sans game over : énergie insuffisante → les consommateurs tournent au prorata ; nourriture à 0 → production −50 % et 4 %/h des colons partent ; O₂ à 0 → 10 %/h partent. Jamais moins de 2 colons.
- La production ne dépasse pas la capacité de stockage, mais un excédent (récompense) n'est pas détruit.
- Idle : rattrapage par pas de 60 s depuis `derniere_maj`, plafonné à 7 jours (« hibernation » ; un chantier en cours se termine quand même).
- Objectifs (un actif à la fois) : serre (+50), panneau solaire niv. 2 (+100), mine (+150), 10 colons (+300), 24 h sans pénurie comptées à partir de l'activation (+500).

## Architecture
- **FastAPI + uvicorn** (1 worker), Python 3.12, image `python:3.12-slim`, utilisateur non-root UID 1000.
- **Aucune boucle serveur** : chaque requête charge l'état, appelle la simulation pure (`app/moteur.py`) jusqu'à « maintenant », applique l'action, sauvegarde.
- **SQLite** (`sqlite3` standard, mode journal classique, pas WAL) : un seul fichier `data/colonie.db`.
- Frontend HTML/CSS/JS vanilla sans build, servi par FastAPI ; PWA (manifest + service worker).

## API
- `GET /api/etat` : simule jusqu'à maintenant, sauvegarde, renvoie tout ce qu'il faut à l'interface (ressources, taux/h, capacités, bâtiments avec coût/durée/effets du prochain niveau, chantier, objectif, pénuries, `rapport` du rattrapage, 30 derniers événements du journal).
- `POST /api/construire` `{"batiment": "serre"}` : 400 avec message en français si l'action est refusée.
- `POST /api/nouvelle-partie` `{"confirmer": true}` : efface la partie et le journal.
- Toutes les réponses `/api/*` sont en `Cache-Control: no-store`.

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
docker compose run --rm tests             # tests pytest (dans un conteneur, sans réseau)
curl -s http://127.0.0.1:8085/api/sante   # santé
docker stats --no-stream colonie          # consommation RAM/CPU
```

## Arborescence
```
app/main.py      routes FastAPI
app/moteur.py    simulation pure : etat_initial, calculer_taux, simuler, demarrer_construction
app/regles.py    données d'équilibrage et objectifs
app/stockage.py  SQLite : table partie (état JSON, 1 ligne) + journal des événements
app/static/      interface (à venir)
tests/           pytest (moteur, API + stockage)
Dockerfile       étapes base → test (pytest) → prod (cible par défaut)
data/            colonie.db — non versionné
```

## État d'avancement
- [x] Étape 1 — Initialisation : git, squelette FastAPI (`/api/sante`), Dockerfile, compose
- [x] Étape 2 — Moteur de simulation + objectifs + tests (32 tests)
  - Équilibrage à affiner en jouant : sur une partie scriptée, aucune pénurie en 48 h (probablement trop facile), matériaux rares avant 24 h puis 700+ après les récompenses.
- [x] Étape 3 — API + persistance SQLite (50 tests)
  - Routes : `GET /api/etat`, `POST /api/construire {batiment}`, `POST /api/nouvelle-partie {confirmer: true}` ; `/api/sante` vérifie aussi la base (503 sinon).
  - Un verrou + `BEGIN IMMEDIATE` sérialisent « charger → simuler → sauvegarder » ; une action refusée annule tout (rollback).
  - Avant le premier `up` : `mkdir -p data` (sinon Docker crée `data/` en root et l'utilisateur UID 1000 ne peut pas écrire la base).
- [ ] Étape 4 — HTTPS via Tailscale Serve (8086)
- [ ] Étape 5 — Interface mobile + PWA
- [ ] Étape 6 — Homepage, WUD, sauvegarde/export/import
- [ ] Étape 7 — Enrichissements (événements, recherche, notifications…)

## Façon de travailler
- Dépôt : https://github.com/Dhafer84/colonie (remote `origin` en SSH, branche `main`).
- Petites étapes testables, un commit par étape (identité `Dhafer84`), poussé sur GitHub.
- Expliquer chaque commande avant de la lancer ; demander avant toute modification du système hôte.
- Mettre à jour la section « État d'avancement » à chaque étape.
