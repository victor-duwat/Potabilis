"""
scripts/register_model.py — enregistrement idempotent du modèle dans MLflow.

Rendu le conteneur AUTONOME : au démarrage, si le modèle n'est pas déjà
enregistré/chargeable dans le registre MLflow (volume /data vide au 1er run,
ou chemins d'artefacts non portables), on le (ré)enregistre depuis l'artefact
`model_artifacts/xgboost_model.json` copié dans l'image.

Idempotent : si le modèle est déjà chargeable, on ne fait rien.
"""

import os
import sys
import logging

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] register_model — %(message)s")
log = logging.getLogger(__name__)

TRACKING   = os.getenv("MLFLOW_TRACKING_URI", "sqlite:///mlflow_water.db")
MODEL_URI  = os.getenv("MLFLOW_URI",          "models:/WaterQualityXGBoost/1")
ARTIFACTS  = os.getenv("MLFLOW_ARTIFACT_DIR", "/data/mlflow_artifacts")
MODEL_JSON = os.getenv("XGBOOST_MODEL_JSON",  "model_artifacts/xgboost_model.json")
MODEL_NAME = "WaterQualityXGBoost"

import mlflow
import mlflow.xgboost
from mlflow import MlflowClient

mlflow.set_tracking_uri(TRACKING)

# 1) Déjà enregistré et chargeable ? -> rien à faire
try:
    mlflow.xgboost.load_model(MODEL_URI)
    log.info("Modèle déjà enregistré et chargeable (%s) — aucune action.", MODEL_URI)
    sys.exit(0)
except Exception as exc:  # noqa: BLE001
    log.info("Modèle non chargeable (%s) — enregistrement depuis %s",
             exc.__class__.__name__, MODEL_JSON)

# 2) Charger le modèle depuis l'artefact JSON
if not os.path.exists(MODEL_JSON):
    log.error("Artefact introuvable : %s — impossible d'enregistrer le modèle.", MODEL_JSON)
    sys.exit(1)

import xgboost as xgb
model = xgb.XGBClassifier()
model.load_model(MODEL_JSON)

# 3) (Ré)enregistrer dans le registre MLflow, avec un chemin d'artefacts portable
os.makedirs(ARTIFACTS, exist_ok=True)
client = MlflowClient()
experiment = "experiment_water_quality"
if client.get_experiment_by_name(experiment) is None:
    # Chemin local brut (portable Linux conteneur / Windows local) — pas de préfixe file://
    client.create_experiment(experiment, artifact_location=ARTIFACTS)
mlflow.set_experiment(experiment)

with mlflow.start_run(run_name="register_from_artifacts"):
    mlflow.xgboost.log_model(
        model,
        artifact_path="xgboost_model",
        registered_model_name=MODEL_NAME,
    )

log.info("Modèle '%s' enregistré avec succès (tracking=%s).", MODEL_NAME, TRACKING)
