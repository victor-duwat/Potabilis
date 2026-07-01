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
os.environ.setdefault("RATELIMIT_ENABLED", "false")

# NB : EXPERT_TOKENS (tokens de tous les fichiers, dont alice/bob et admin-*) est
# défini une seule fois dans le conftest.py RACINE, pour éviter tout écrasement.
