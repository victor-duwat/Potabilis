"""
conftest.py — configuration partagée de la suite de tests.

Chargé par pytest AVANT l'import de tout module de test. On y définit un
unique jeu de tokens experts couvrant tous les fichiers de tests, ce qui évite
les conflits d'isolation (chaque fichier partageait auparavant la même variable
globale EXPERT_TOKENS avec des valeurs différentes — seul le dernier l'emportait).
"""

import os

# Variables d'environnement communes (avant tout import de l'application)
os.environ.setdefault("DATABASE_URL",      "sqlite:///:memory:")
os.environ.setdefault("MLFLOW_URI",        "mock")
os.environ.setdefault("SCALER_PATH",       "mock")
os.environ.setdefault("OCR_SPACE_API_KEY", "")
os.environ.setdefault("ANTHROPIC_API_KEY", "")
# La suite enchaîne volontairement de nombreuses requêtes sur des routes
# limitées (ex. /ingest/manual 20/min) : on désactive le rate limiting en test.
os.environ.setdefault("RATELIMIT_ENABLED", "false")

# Jeu de tokens experts unique pour toute la suite : un token par fichier de test.
os.environ["EXPERT_TOKENS"] = (
    "admin:token-admin-bug:exploit,"
    "admin:token-admin-e2e:exploit,"
    "admin:token-admin-fonc:exploit,"
    "admin:token-admin-noreg:exploit"
)
