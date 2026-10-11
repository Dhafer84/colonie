# 🚀 Colonie spatiale

Petit jeu de gestion **idle** mono-joueur, à auto-héberger. On pose une base sur une
planète, on équilibre l'oxygène, l'énergie et la nourriture, et la colonie continue de
vivre pendant qu'on n'est pas là.

Pensé pour des sessions courtes sur téléphone (installable en PWA) et des choix plus
longs sur ordinateur, avec une seule partie partagée entre les appareils.

## Le jeu

- **Ressources** : oxygène, énergie, nourriture, matériaux, et des **colons** qui
  consomment de l'oxygène et de la nourriture, et font tourner les bâtiments.
- **Bâtiments** à construire et améliorer (jusqu'au niveau 10) : panneau solaire,
  générateur d'oxygène, serre, mine, habitat, entrepôt. La construction se fait en
  temps réel, un chantier à la fois.
- **Pénuries sans game over** : manque d'énergie, famine ou manque d'oxygène font baisser
  la production et partir des colons, mais un noyau reste toujours pour repartir.
- **Jeu idle** : en revenant, un résumé « Pendant ton absence » raconte ce qui s'est
  passé (constructions terminées, pénuries, colons arrivés ou partis…).
- **Objectifs** : une chaîne d'objectifs progressifs, récompensés en matériaux.
- **Sauvegarde** : export / import de la partie en JSON depuis le menu.

Toutes les valeurs d'équilibrage sont regroupées dans [`app/regles.py`](app/regles.py).

## Fonctionnement

Le serveur ne fait **rien** quand personne ne joue : il n'y a pas de boucle de jeu.
À chaque requête, l'état est chargé, la simulation rattrape le temps écoulé depuis la
dernière visite (par pas de 60 s, plafonnée à 7 jours d'absence), l'action éventuelle
est appliquée, puis l'état est sauvegardé.

| Élément | Choix |
|---|---|
| Backend | Python 3.12, FastAPI, uvicorn (un seul worker) |
| Stockage | SQLite, un seul fichier `data/colonie.db` |
| Interface | HTML / CSS / JavaScript sans framework ni étape de build, PWA |
| Déploiement | Docker Compose, utilisateur non-root, ~40 Mo de RAM |

```
app/
├── moteur.py      simulation pure (aucune entrée/sortie), testée
├── regles.py      données d'équilibrage et objectifs
├── main.py        API FastAPI + fichiers statiques
├── stockage.py    persistance SQLite
├── sauvegarde.py  copie cohérente de la base (pour cron)
└── static/        interface et PWA
tests/             pytest (moteur, API, stockage)
```

## Installation

Prérequis : Docker avec Docker Compose.

```bash
git clone https://github.com/Dhafer84/colonie.git
cd colonie
mkdir -p data                 # à créer soi-même : le conteneur tourne en UID 1000
docker compose up -d --build
curl -s http://127.0.0.1:8085/api/sante   # {"statut":"ok"}
```

Le jeu écoute sur `127.0.0.1:8085` uniquement. Il n'a **pas d'authentification** :
ne l'exposez pas sur Internet. Publiez-le plutôt sur un réseau privé, par exemple avec
Tailscale Serve, qui fournit aussi le HTTPS nécessaire à l'installation en PWA :

```bash
sudo tailscale serve --bg --https=8086 http://127.0.0.1:8085
```

Le `docker-compose.yml` rattache aussi le conteneur au réseau Docker `homepage_default`
(pour la tuile [Homepage](https://gethomepage.dev/)). Sans Homepage, supprimez les
lignes `networks` correspondantes.

Si votre UID n'est pas 1000, adaptez le `Dockerfile` (utilisateur `colonie`).

## Tests

```bash
docker compose run --rm tests
```

Les tests tournent dans un conteneur dédié, sans réseau. L'image de production
n'embarque ni pytest ni les tests.

## Sauvegarde

```bash
# Copie cohérente, même pendant que le jeu tourne (14 conservées dans data/sauvegardes/)
docker compose exec -T colonie python -m app.sauvegarde

# Exemple de tâche cron quotidienne
17 4 * * * cd "$HOME/colonie" && docker compose exec -T colonie python -m app.sauvegarde >> data/sauvegardes.log 2>&1
```

Restauration, mise à jour et intégration détaillée : voir
[`MISE-EN-SERVICE.md`](MISE-EN-SERVICE.md).

## Mise à jour

```bash
git pull
docker compose run --rm tests && docker compose up -d --build
docker compose build --pull && docker compose up -d   # mettre à jour l'image de base
```
