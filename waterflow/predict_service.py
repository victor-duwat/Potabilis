"""
api/services/predict_service.py — Service de prédiction XGBoost

Chargement unique du modèle au démarrage.
Expose run_prediction() utilisé par toutes les routes.
"""

import os
import logging

import joblib
import numpy as np
import mlflow.xgboost

logger = logging.getLogger(__name__)

MLFLOW_MODEL_URI = os.getenv("MLFLOW_URI",   "models:/WaterQualityXGBoost/1")
SCALER_PATH      = os.getenv("SCALER_PATH",  "model_artifacts/robust_scaler.pkl")

FEATURES = [
    "ph", "Hardness", "Solids", "Chloramines", "Sulfate",
    "Conductivity", "Organic_carbon", "Trihalomethanes", "Turbidity",
]

# Chargement au démarrage du module
mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI", "sqlite:///mlflow_water.db"))
logger.info("Chargement modèle MLflow : %s", MLFLOW_MODEL_URI)
_model  = mlflow.xgboost.load_model(MLFLOW_MODEL_URI)
logger.info("Chargement scaler : %s", SCALER_PATH)
_scaler = joblib.load(SCALER_PATH)
logger.info("Modèle prêt.")


def run_prediction(mesures: dict) -> dict:
    """
    Applique le scaler et le modèle sur un dict de mesures.

    Paramètres
    ----------
    mesures : dict avec les 9 features (valeurs float ou None)

    Retourne
    --------
    dict { potable, label, probability, missing_features }

    Lève ValueError si des features critiques sont nulles.
    """
    missing = [f for f in FEATURES if mesures.get(f) is None]
    if missing:
        raise ValueError(f"Features manquantes ou nulles : {missing}")

    try:
        values = np.array([[float(mesures[f]) for f in FEATURES]])
    except (TypeError, ValueError) as e:
        raise ValueError(f"Valeur non numérique dans les mesures : {e}") from e

    values_scaled = _scaler.transform(values)
    prediction    = int(_model.predict(values_scaled)[0])
    probability   = float(_model.predict_proba(values_scaled)[0][1])

    return {
        "potable":     prediction,
        "label":       "Potable" if prediction == 1 else "Non potable",
        "probability": round(probability, 4),
        "model_version": MLFLOW_MODEL_URI,
    }
