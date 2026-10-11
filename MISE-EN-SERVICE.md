# Mise en service sur le serveur

Actions à faire **sur le serveur** (`ssh serveur`), depuis `~/homelab/colonie`.
Chaque bloc est expliqué avant d'être lancé ; rien ici n'est automatique.

## 1. Récupérer le code

```bash
cd ~/homelab/colonie
git fetch origin
git status                       # vérifier qu'il n'y a pas de modification locale
git merge --ff-only origin/main  # ou la branche de travail, une fois fusionnée dans main
```

## 2. Préparer le dossier des données

Si Docker crée lui-même `data/`, le dossier appartient à root et le conteneur
(utilisateur UID 1000) ne peut pas y écrire la base. On le crée donc soi-même :

```bash
mkdir -p data
ls -ld data                      # doit appartenir à dhafer (UID 1000)
```

## 3. Tester, construire et lancer

```bash
docker compose run --rm tests             # 74 tests, dans un conteneur sans réseau
docker compose up -d --build              # construit l'image et (re)lance le service
curl -s http://127.0.0.1:8085/api/sante   # attendu : {"statut":"ok"}
docker stats --no-stream colonie          # RAM : quelques dizaines de Mo (limite 128 Mo)
```

## 4. Étape 4 — HTTPS via Tailscale Serve (port 8086)

Tailscale Serve publie le service **uniquement sur le tailnet**, en HTTPS avec
un certificat valide (nécessaire pour la PWA et son service worker).
Le port 8085 reste lié à 127.0.0.1.

```bash
sudo tailscale serve --bg --https=8086 http://127.0.0.1:8085
tailscale serve status                    # vérifier la règle
```

`<tailnet>` : le nom de ton tailnet, affiché par `tailscale serve status`.

Puis ouvrir `https://serveur.<tailnet>.ts.net:8086` sur le téléphone (Tailscale actif) :
- **iPhone** (Safari) : Partager → « Sur l'écran d'accueil ».
- **Android** (Chrome) : menu ⋮ → « Installer l'application ».

Pour retirer la règle : `sudo tailscale serve --https=8086 off`.

## 5. Étape 6 — Tuile Homepage

Ajouter dans `~/homepage/config/services.yaml`, groupe « Loisirs » :

```yaml
- Loisirs:
    - Colonie spatiale:
        icon: mdi-rocket-launch
        href: https://serveur.<tailnet>.ts.net:8086
        description: Jeu de gestion idle
        siteMonitor: https://serveur.<tailnet>.ts.net:8086/api/sante
        container: colonie
```

`container: colonie` n'affiche l'état que si Homepage a accès à Docker
(`docker.yaml`) ; sinon, supprimer la ligne. Homepage relit le fichier tout seul.

WUD : rien à faire, `wud.watch=false` est déjà dans `docker-compose.yml`
(image locale ; l'image de base se met à jour avec `docker compose build --pull`).

## 6. Étape 6 — Sauvegarde automatique de la base

`python -m app.sauvegarde` fait une copie cohérente de la base (même si le jeu
tourne) dans `data/sauvegardes/` et garde les 14 dernières.

Essai manuel :

```bash
docker compose exec -T colonie python -m app.sauvegarde
ls -l data/sauvegardes/
```

Tous les jours à 4 h 17 (`crontab -e`, en tant que dhafer) :

```cron
17 4 * * * cd "$HOME/homelab/colonie" && docker compose exec -T colonie python -m app.sauvegarde >> data/sauvegardes.log 2>&1
```

> Ces copies sont sur le même disque : elles protègent d'une erreur ou d'une
> base abîmée, pas d'une panne du disque. L'export JSON depuis le menu du jeu
> permet d'en garder une copie ailleurs (sur le Mac, par exemple).

### Restaurer une sauvegarde

```bash
docker compose stop colonie
cp data/colonie.db data/colonie.db.avant-restauration
cp data/sauvegardes/colonie-AAAAMMJJ-HHMMSS-xxxxxx.db data/colonie.db
docker compose start colonie
```

## Mettre à jour plus tard

```bash
git pull
docker compose run --rm tests && docker compose up -d --build
```
