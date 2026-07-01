"""
conftest.py — RACINE du projet (même niveau que app.py).

Rôle :
  1. Ajouter la racine au sys.path pour que `import app`, `import routes`, etc. fonctionnent.
  2. Définir un environnement de test UNIQUE pour TOUTE la suite (racine + tests/),
     afin d'éviter les conflits de variables globales (EXPERT_TOKENS notamment) :
     chaque fichier utilise SON token, tous présents ici -> pas d'écrasement.

Ce fichier étant à la racine, il s'applique à l'ensemble des tests (y compris test_api.py).
"""

import os
import sys

# 1) Racine dans le sys.path (avant tout import applicatif)
sys.path.insert(0, os.path.dirname(__file__))

# 2) Environnement de test commun (défini avant l'import de l'application)
os.environ.setdefault("DATABASE_URL",      "sqlite:///:memory:")
os.environ.setdefault("MLFLOW_URI",        "mock")
os.environ.setdefault("SCALER_PATH",       "mock")
os.environ.setdefault("OCR_SPACE_API_KEY", "")
os.environ.setdefault("ANTHROPIC_API_KEY", "")
# La suite enchaîne de nombreuses requêtes sur des routes limitées : rate limiting off en test.
os.environ.setdefault("RATELIMIT_ENABLED", "false")

# Jeu de tokens experts UNIQUE couvrant tous les fichiers de tests :
#   - test_api.py         -> alice (analyste) / bob (exploit)  [teste la séparation des rôles]
#   - tests/test_bug_e5   -> admin (exploit)
#   - tests/test_e2e      -> admin (exploit)
#   - tests/test_fonctio. -> admin (exploit)
#   - tests/test_non_reg. -> admin (exploit)
os.environ["EXPERT_TOKENS"] = (
    "alice:token-alice:analyste,"
    "bob:token-bob:exploit,"
    "admin:token-admin-bug:exploit,"
    "admin:token-admin-e2e:exploit,"
    "admin:token-admin-fonc:exploit,"
    "admin:token-admin-noreg:exploit"
)
