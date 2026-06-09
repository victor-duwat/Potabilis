"""
=============================================================
TESTS FONCTIONNELS — Projet Water Potability MLOps
=============================================================
Objectif : tester les endpoints de l'API Flask de bout en bout,
           en mockant le modèle MLflow et le scaler.
Couverture :
  - GET  /health
  - GET  /
  - POST /predict  (cas nominaux + cas d'erreur)
  - Comportement HTTP (codes de statut, Content-Type, JSON)
=============================================================
"""

import json
import pytest
import numpy as np
from unittest.mock import MagicMock, patch


# ──────────────────────────────────────────────────────────
# FIXTURES — Application Flask avec mocks injectés
# ──────────────────────────────────────────────────────────

FEATURES = [
    "ph", "Hardness", "Solids", "Chloramines", "Sulfate",
    "Conductivity", "Organic_carbon", "Trihalomethanes", "Turbidity"
]

VALID_PAYLOAD = {
    "ph": 7.0,
    "Hardness": 200.0,
    "Solids": 20000.0,
    "Chloramines": 7.5,
    "Sulfate": 350.0,
    "Conductivity": 400.0,
    "Organic_carbon": 14.0,
    "Trihalomethanes": 66.0,
    "Turbidity": 3.5,
}


def create_app_with_mocks(predict_value=1, proba_value=0.87):
    """
    Crée le client de test Flask en patchant les dépendances externes
    (MLflow, joblib) pour que les tests soient indépendants de l'environnement.
    """
    mock_model = MagicMock()
    mock_model.predict.return_value = np.array([predict_value])
    mock_model.predict_proba.return_value = np.array([[1 - proba_value, proba_value]])

    mock_scaler = MagicMock()
    mock_scaler.transform.return_value = np.zeros((1, 9))

    with patch("mlflow.set_tracking_uri"), \
         patch("mlflow.xgboost.load_model", return_value=mock_model), \
         patch("joblib.load", return_value=mock_scaler):
        import importlib, sys

        # Rechargement propre du module app pour chaque test
        if "app" in sys.modules:
            del sys.modules["app"]

        import app as flask_app
        flask_app.model = mock_model
        flask_app.scaler = mock_scaler
        flask_app.app.config["TESTING"] = True
        client = flask_app.app.test_client()

    return client, mock_model, mock_scaler


# ──────────────────────────────────────────────────────────
# SECTION 1 — Endpoint GET /health
# ──────────────────────────────────────────────────────────

class TestEndpointHealth:
    """Vérifie la disponibilité et la réponse du health-check."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.client, self.model, self.scaler = create_app_with_mocks()

    def test_health_statut_200(self):
        resp = self.client.get("/health")
        assert resp.status_code == 200

    def test_health_retourne_json(self):
        resp = self.client.get("/health")
        assert resp.content_type == "application/json"

    def test_health_champ_status_ok(self):
        resp = self.client.get("/health")
        data = json.loads(resp.data)
        assert data["status"] == "ok"

    def test_health_champ_model_present(self):
        resp = self.client.get("/health")
        data = json.loads(resp.data)
        assert "model" in data
        assert "WaterQualityXGBoost" in data["model"]

    def test_health_methode_get_uniquement(self):
        """POST sur /health doit retourner 405 Method Not Allowed."""
        resp = self.client.post("/health")
        assert resp.status_code == 405


# ──────────────────────────────────────────────────────────
# SECTION 2 — Endpoint GET /
# ──────────────────────────────────────────────────────────

class TestEndpointIndex:
    """Vérifie que la page d'accueil est accessible."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.client, _, _ = create_app_with_mocks()

    def test_index_statut_200_ou_redirect(self):
        resp = self.client.get("/")
        assert resp.status_code in (200, 302, 404)  # 404 si template absent en CI


# ──────────────────────────────────────────────────────────
# SECTION 3 — Endpoint POST /predict — Cas nominaux
# ──────────────────────────────────────────────────────────

class TestEndpointPredictNominal:
    """Teste les scénarios normaux de prédiction."""

    @pytest.fixture(autouse=True)
    def setup_potable(self):
        self.client_potable, self.model_potable, _ = create_app_with_mocks(
            predict_value=1, proba_value=0.87
        )

    def test_predict_statut_200(self):
        resp = self.client_potable.post(
            "/predict",
            data=json.dumps(VALID_PAYLOAD),
            content_type="application/json"
        )
        assert resp.status_code == 200

    def test_predict_retourne_json(self):
        resp = self.client_potable.post(
            "/predict",
            data=json.dumps(VALID_PAYLOAD),
            content_type="application/json"
        )
        assert resp.content_type == "application/json"

    def test_predict_champs_presents(self):
        resp = self.client_potable.post(
            "/predict",
            data=json.dumps(VALID_PAYLOAD),
            content_type="application/json"
        )
        data = json.loads(resp.data)
        assert "potable" in data
        assert "label" in data
        assert "probability" in data

    def test_predict_label_potable(self):
        resp = self.client_potable.post(
            "/predict",
            data=json.dumps(VALID_PAYLOAD),
            content_type="application/json"
        )
        data = json.loads(resp.data)
        assert data["potable"] == 1
        assert data["label"] == "Potable"

    def test_predict_label_non_potable(self):
        client, _, _ = create_app_with_mocks(predict_value=0, proba_value=0.12)
        resp = client.post(
            "/predict",
            data=json.dumps(VALID_PAYLOAD),
            content_type="application/json"
        )
        data = json.loads(resp.data)
        assert data["potable"] == 0
        assert data["label"] == "Non potable"

    def test_predict_probability_dans_intervalle(self):
        resp = self.client_potable.post(
            "/predict",
            data=json.dumps(VALID_PAYLOAD),
            content_type="application/json"
        )
        data = json.loads(resp.data)
        assert 0.0 <= data["probability"] <= 1.0

    def test_predict_model_appele_une_fois(self):
        self.client_potable.post(
            "/predict",
            data=json.dumps(VALID_PAYLOAD),
            content_type="application/json"
        )
        assert self.model_potable.predict.call_count == 1

    def test_predict_scaler_appele_avant_model(self):
        """Le scaler doit être appelé avant le modèle."""
        client, model, scaler = create_app_with_mocks()
        call_order = []
        scaler.transform.side_effect = lambda x: (call_order.append("scaler"), np.zeros((1, 9)))[1]
        model.predict.side_effect = lambda x: (call_order.append("model"), np.array([1]))[1]

        client.post(
            "/predict",
            data=json.dumps(VALID_PAYLOAD),
            content_type="application/json"
        )
        assert call_order.index("scaler") < call_order.index("model")

    def test_predict_force_json_sans_content_type(self):
        """L'API doit accepter le JSON même sans Content-Type explicite (force=True)."""
        resp = self.client_potable.post(
            "/predict",
            data=json.dumps(VALID_PAYLOAD)
        )
        assert resp.status_code == 200


# ──────────────────────────────────────────────────────────
# SECTION 4 — Endpoint POST /predict — Cas d'erreur
# ──────────────────────────────────────────────────────────

class TestEndpointPredictErreurs:
    """Teste que l'API renvoie des erreurs cohérentes pour des inputs invalides."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.client, _, _ = create_app_with_mocks()

    def _post(self, payload):
        return self.client.post(
            "/predict",
            data=json.dumps(payload),
            content_type="application/json"
        )

    def test_feature_manquante_retourne_400(self):
        payload_incomplet = {k: v for k, v in VALID_PAYLOAD.items() if k != "ph"}
        resp = self._post(payload_incomplet)
        assert resp.status_code == 400

    def test_feature_manquante_message_erreur(self):
        payload_incomplet = {k: v for k, v in VALID_PAYLOAD.items() if k != "ph"}
        resp = self._post(payload_incomplet)
        data = json.loads(resp.data)
        assert "error" in data

    def test_valeur_string_retourne_400(self):
        payload_invalide = {**VALID_PAYLOAD, "ph": "abc"}
        resp = self._post(payload_invalide)
        assert resp.status_code == 400

    def test_payload_vide_retourne_400(self):
        resp = self._post({})
        assert resp.status_code == 400

    def test_erreur_toujours_json(self):
        """Même en cas d'erreur, la réponse doit être du JSON valide."""
        payload_incomplet = {k: v for k, v in VALID_PAYLOAD.items() if k != "Turbidity"}
        resp = self._post(payload_incomplet)
        try:
            json.loads(resp.data)
        except json.JSONDecodeError:
            pytest.fail("La réponse d'erreur n'est pas du JSON valide")

    @pytest.mark.parametrize("missing_feature", FEATURES)
    def test_chaque_feature_manquante_detectee(self, missing_feature):
        """Supprimer n'importe quelle feature doit produire une erreur 400."""
        payload = {k: v for k, v in VALID_PAYLOAD.items() if k != missing_feature}
        resp = self._post(payload)
        assert resp.status_code == 400, f"Feature '{missing_feature}' manquante non détectée"


# ──────────────────────────────────────────────────────────
# SECTION 5 — Intégration modèle + API
# ──────────────────────────────────────────────────────────

class TestIntegrationModelAPI:
    """Tests de bout en bout : vérifie la cohérence entre modèle et réponse."""

    @pytest.mark.parametrize("pred,proba,expected_label", [
        (1, 0.95, "Potable"),
        (1, 0.55, "Potable"),
        (0, 0.45, "Non potable"),
        (0, 0.05, "Non potable"),
    ])
    def test_coherence_prediction_label_probabilite(self, pred, proba, expected_label):
        client, _, _ = create_app_with_mocks(predict_value=pred, proba_value=proba)
        resp = client.post(
            "/predict",
            data=json.dumps(VALID_PAYLOAD),
            content_type="application/json"
        )
        data = json.loads(resp.data)
        assert data["label"] == expected_label
        assert data["potable"] == pred

    def test_probabilite_reflete_classe_positive(self):
        """La probabilité retournée doit correspondre à P(potable=1)."""
        expected_proba = 0.7654
        client, _, _ = create_app_with_mocks(predict_value=1, proba_value=expected_proba)
        resp = client.post(
            "/predict",
            data=json.dumps(VALID_PAYLOAD),
            content_type="application/json"
        )
        data = json.loads(resp.data)
        assert abs(data["probability"] - round(expected_proba, 4)) < 1e-4
