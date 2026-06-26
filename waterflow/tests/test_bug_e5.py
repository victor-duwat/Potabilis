"""
=============================================================
TEST E5 — Bug INC-2025-002 : Probabilité inversée
=============================================================
Ce test a été écrit pour détecter la régression introduite
dans predict_service.py le 2025-12-03 (commit 7f3a2b1).

Bug : la ligne
    probability = float(_model.predict_proba(values_scaled)[0][1])
avait été modifiée en
    probability = float(_model.predict_proba(values_scaled)[0][0])
retournant la probabilité de NON-potabilité au lieu de potabilité.

Impact : pour un échantillon classifié potable (potable=1),
la probabilité affichée était celle de la classe 0 (non-potable),
ce qui induisait les clients en erreur (ex: "Potable à 18 %").

Détection : ce test échouait sur la branche buggy, CI rouge.
Correction : restaurer [0][1] dans predict_service.py.
=============================================================
"""

import os
import pytest
import numpy as np
from unittest.mock import MagicMock, patch

os.environ.setdefault("DATABASE_URL",      "sqlite:///:memory:")
os.environ.setdefault("MLFLOW_URI",        "mock")
os.environ.setdefault("SCALER_PATH",       "mock")
os.environ.setdefault("OCR_SPACE_API_KEY", "")
os.environ.setdefault("ANTHROPIC_API_KEY", "")
os.environ["EXPERT_TOKENS"] = "admin:token-admin-bug:exploit"

ADMIN_HEADER  = {"Authorization": "Bearer token-admin-bug"}

VALID_PAYLOAD = {
    "ph": 7.0, "Hardness": 200.0, "Solids": 20000.0,
    "Chloramines": 7.5, "Sulfate": 350.0, "Conductivity": 400.0,
    "Organic_carbon": 14.0, "Trihalomethanes": 66.0, "Turbidity": 3.5,
}


@pytest.fixture(scope="module")
def client_http():
    """Application Flask avec modèle qui retourne potable=1 avec proba 0.87."""
    mock_model = MagicMock()
    # Le modèle retourne : [P(non-potable)=0.13, P(potable)=0.87]
    mock_model.predict.return_value       = np.array([1])
    mock_model.predict_proba.return_value = np.array([[0.13, 0.87]])

    mock_scaler = MagicMock()
    mock_scaler.transform.side_effect = lambda x: x

    with patch("mlflow.xgboost.load_model", return_value=mock_model), \
         patch("joblib.load",               return_value=mock_scaler), \
         patch("mlflow.set_tracking_uri"):
        from api.app       import create_app
        from api.models.db import init_db
        app = create_app()
        app.config["TESTING"] = True
        init_db()
        http = app.test_client()

    # Créer un client de test
    r = http.post("/admin/clients",
                  json={"id_client": "BUG-001", "denomination": "Test Bug E5", "adresse": "1 rue du Bug"},
                  headers=ADMIN_HEADER)
    client_id = r.get_json()["id"]
    r2 = http.post(f"/admin/clients/{client_id}/apikey", headers=ADMIN_HEADER)
    api_key = r2.get_json()["api_key"]

    return http, {"X-API-Key": api_key}


class TestBugProbabiliteInversee:
    """
    Teste que la probabilité retournée correspond bien à P(potable=1).

    Bug INC-2025-002 : si predict_proba()[0][0] est utilisé au lieu de [0][1],
    la probabilité de NON-potabilité est retournée comme si c'était la potabilité.
    Ce test échouerait avec le bug : il obtiendrait 0.13 au lieu de 0.87.
    """

    def test_probabilite_correspond_a_classe_positive(self, client_http):
        """La probabilité doit être P(potable=1) = 0.87, pas P(non-potable=0) = 0.13."""
        http, header = client_http
        r = http.post("/ingest/manual", json=VALID_PAYLOAD, headers=header)
        assert r.status_code == 201
        pred = r.get_json()["prediction"]

        # Le modèle retourne [[0.13, 0.87]] — potable=1 → proba doit être 0.87
        # Avec le bug ([0][0] au lieu de [0][1]), on obtient 0.13 → test ECHOUE
        assert pred["potable"] == 1, f"Prédiction inattendue : {pred['potable']}"
        assert pred["probability"] >= 0.5, (
            f"Bug détecté : probabilité {pred['probability']:.4f} < 0.5 "
            f"pour un échantillon classifié potable. "
            f"Vérifier predict_service.py ligne predict_proba()[0][1] vs [0][0]."
        )
        assert abs(pred["probability"] - 0.87) < 0.01, (
            f"Probabilité incorrecte : attendu ~0.87, obtenu {pred['probability']}. "
            f"La probabilité retournée doit être P(classe=1), pas P(classe=0)."
        )

    def test_probabilite_non_potable_correcte(self, client_http):
        """Pour potable=0, la probabilité doit aussi correspondre à P(potable=1)."""
        http, header = client_http

        mock_np = MagicMock()
        mock_np.predict.return_value       = np.array([0])
        mock_np.predict_proba.return_value = np.array([[0.78, 0.22]])

        with patch("predict_service._model", mock_np):
            r = http.post("/ingest/manual", json=VALID_PAYLOAD, headers=header)

        pred = r.get_json()["prediction"]
        assert pred["potable"] == 0
        # P(potable=1) = 0.22 → doit être < 0.5 pour un résultat non-potable
        assert pred["probability"] < 0.5, (
            f"Bug potentiel : probabilité {pred['probability']} >= 0.5 "
            f"pour un résultat non-potable."
        )
        assert abs(pred["probability"] - 0.22) < 0.01

    def test_coherence_prediction_probabilite(self, client_http):
        """Règle invariante : potable=1 ↔ probability >= 0.5."""
        http, header = client_http
        r = http.post("/ingest/manual", json=VALID_PAYLOAD, headers=header)
        pred = r.get_json()["prediction"]
        if pred["potable"] == 1:
            assert pred["probability"] >= 0.5, "Incohérence : potable=1 mais probability < 0.5"
        else:
            assert pred["probability"] < 0.5, "Incohérence : potable=0 mais probability >= 0.5"
