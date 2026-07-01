#!/bin/sh
# Point d'entrée du conteneur Waterflow 2.
# 1) Enregistre le modèle dans MLflow si nécessaire (conteneur autonome).
# 2) Démarre le serveur applicatif Gunicorn.
set -e

echo "[entrypoint] Vérification/enregistrement du modèle MLflow..."
python scripts/register_model.py || echo "[entrypoint] AVERTISSEMENT : enregistrement du modèle échoué, tentative de démarrage quand même."

echo "[entrypoint] Démarrage de Gunicorn..."
exec gunicorn --bind 0.0.0.0:8080 --workers 2 --timeout 120 \
     --access-logfile - --error-logfile - main:app
