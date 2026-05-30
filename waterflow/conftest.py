"""
conftest.py — à placer à la RACINE du projet (même niveau que app.py)
Ajoute automatiquement la racine au sys.path pour que 'import app' fonctionne.
"""

import sys
import os

# Ajoute la racine du projet au chemin Python
sys.path.insert(0, os.path.dirname(__file__))
