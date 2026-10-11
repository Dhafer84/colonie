"""Données d'équilibrage du jeu.

Tous les taux sont exprimés **par heure**, les durées en **secondes**.
C'est ce fichier qu'on modifie pour rééquilibrer le jeu ; le moteur ne contient
aucun chiffre « magique ».
"""

RESSOURCES = ("oxygene", "energie", "nourriture", "materiaux")

NOMS_RESSOURCES = {
    "oxygene": "oxygène",
    "energie": "énergie",
    "nourriture": "nourriture",
    "materiaux": "matériaux",
}

# --- Progression des niveaux -------------------------------------------------
FACTEUR_COUT = 1.6         # coût du niveau n = cout_base × 1,6^(n-1)
FACTEUR_DUREE = 2.5        # durée du niveau n = duree_base × 2,5^(n-1)
FACTEUR_PRODUCTION = 1.5   # production au niveau n = base × 1,5^(n-1)
FACTEUR_CONSOMMATION = 1.3 # consommation d'énergie au niveau n = base × 1,3^(n-1)
NIVEAU_MAX = 10

# --- Bâtiments ---------------------------------------------------------------
# produit / consomme : ressources par heure au niveau 1
# postes : colons nécessaires par niveau pour tourner à plein régime
# deblocage : condition pour pouvoir le construire (None = disponible dès le départ)
BATIMENTS = {
    "panneau_solaire": {
        "nom": "Panneau solaire",
        "description": "Produit de l'énergie.",
        "cout_base": 40,
        "duree_base": 30,
        "produit": {"energie": 10},
        "consomme": {},
        "postes": 0,
        "deblocage": None,
    },
    "generateur_o2": {
        "nom": "Générateur d'oxygène",
        "description": "Produit de l'oxygène, consomme de l'énergie.",
        "cout_base": 50,
        "duree_base": 45,
        "produit": {"oxygene": 12},
        "consomme": {"energie": 3},
        "postes": 1,
        "deblocage": None,
    },
    "serre": {
        "nom": "Serre",
        "description": "Produit de la nourriture et un peu d'oxygène.",
        "cout_base": 50,
        "duree_base": 60,
        "produit": {"nourriture": 10, "oxygene": 2},
        "consomme": {"energie": 3},
        "postes": 1,
        "deblocage": None,
    },
    "mine": {
        "nom": "Mine",
        "description": "Extrait des matériaux de construction.",
        "cout_base": 80,
        "duree_base": 90,
        "produit": {"materiaux": 15},
        "consomme": {"energie": 4},
        "postes": 1,
        "deblocage": {"colons": 6},
    },
    "habitat": {
        "nom": "Habitat",
        "description": "Loge les colons (+4 places par niveau).",
        "cout_base": 100,
        "duree_base": 120,
        "produit": {},
        "consomme": {"energie": 1},
        "postes": 0,
        "deblocage": None,
    },
    "entrepot": {
        "nom": "Entrepôt",
        "description": "Augmente la capacité de stockage de chaque ressource.",
        "cout_base": 70,
        "duree_base": 60,
        "produit": {},
        "consomme": {},
        "postes": 0,
        "deblocage": None,
    },
}

# --- Capacités ---------------------------------------------------------------
STOCKAGE_BASE = 300          # par ressource
STOCKAGE_PAR_ENTREPOT = 250  # par niveau d'entrepôt
COLONS_BASE = 2              # places hors habitat
COLONS_PAR_HABITAT = 4       # par niveau d'habitat

# --- Colons ------------------------------------------------------------------
CONSO_COLON = {"oxygene": 2.0, "nourriture": 1.5}  # par colon et par heure
CROISSANCE_COLONS = 0.25     # colons gagnés par heure quand tout va bien
COLONS_MIN = 2               # noyau qui ne part jamais
DEPART_FAMINE = 0.04         # part des colons (au-delà du noyau) qui part par heure
DEPART_ASPHYXIE = 0.10
MALUS_FAMINE = 0.5           # multiplicateur de production en cas de famine

# Récupération sur l'épave du vaisseau : évite tout blocage faute de matériaux
RECUPERATION_MATERIAUX = 3   # par heure

# --- Temps -------------------------------------------------------------------
PAS_SIMULATION = 60                # secondes
ABSENCE_MAX = 7 * 24 * 3600        # au-delà, la colonie « hiberne »

# --- Départ ------------------------------------------------------------------
ETAT_DEPART = {
    "ressources": {"oxygene": 100, "energie": 50, "nourriture": 60, "materiaux": 150},
    "colons": 4,
    "batiments": {
        "panneau_solaire": 1,
        "generateur_o2": 1,
        "serre": 0,
        "mine": 0,
        "habitat": 1,
        "entrepot": 0,
    },
}

# --- Objectifs ---------------------------------------------------------------
# Un seul objectif actif à la fois, dans l'ordre. type :
#   "niveau"       → batiment atteint au moins `niveau`
#   "colons"       → au moins `valeur` colons
#   "sans_penurie" → `duree` secondes consécutives sans aucune pénurie
OBJECTIFS = [
    {"titre": "Premières récoltes", "description": "Construire une serre.",
     "type": "niveau", "batiment": "serre", "niveau": 1, "recompense": 50},
    {"titre": "Plus de courant", "description": "Améliorer le panneau solaire au niveau 2.",
     "type": "niveau", "batiment": "panneau_solaire", "niveau": 2, "recompense": 100},
    {"titre": "Sous la surface", "description": "Débloquer la mine (6 colons) et la construire.",
     "type": "niveau", "batiment": "mine", "niveau": 1, "recompense": 150},
    {"titre": "Une vraie colonie", "description": "Atteindre 10 colons.",
     "type": "colons", "valeur": 10, "recompense": 300},
    {"titre": "Autonomie", "description": "Tenir 24 h sans aucune pénurie.",
     "type": "sans_penurie", "duree": 24 * 3600, "recompense": 500},
]
