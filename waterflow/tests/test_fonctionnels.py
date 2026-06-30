"""
=============================================================
TESTS FONCTIONNELS — Waterflow 2 (architecture v2)
=============================================================
Objectif : tester les endpoints de l'API Flask de bout en bout,
           en mockant le modèle MLflow et le scaler.
Couverture :
  - GET  /health
  - GET  /
  - POST /ingest/manual  (anciennement /predict — nécessite X-API-Key)
  - Comportement HTTP (codes de statut, Content-Type, JSON)
  - Sécurité : accès sans clé → 401
=============================================================
"""

import os
import json
import pytest
import numpy as np
from unittest.mock import MagicMock, patch

# ── Env avant import Flask ────────────────────────────────────────────────────
os.environ.setdefault("DATABASE_URL",      "sqlite:///:memory:")
os.environ.setdefault("MLFLOW_URI",        "mock")
os.environ.setdefault("SCALER_PATH",       "mock")
os.environ.setdefault("OCR_SPACE_API_KEY", "")
os.environ.setdefault("ANTHROPIC_API_KEY", "")
# EXPERT_TOKENS est défini globalement dans conftest.py (jeu commun à toute la suite)

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

FEATURES = [
    "ph", "Hardness", "Solids", "Chloramines", "Sulfate",
    "Conductivity", "Organic_carbon", "Trihalomethanes", "Turbidity",
]

ADMIN_HEADER = {"Authorization": "Bearer token-admin-fonc"}

_mock_model = MagicMock()
_mock_model.predict.return_value       = np.array([1])
_mock_model.predict_proba.return_value = np.array([[0.13, 0.87]])

_mock_scaler = MagicMock()
_mock_scaler.transform.side_effect = lambda x: x


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def app():
    with patch("mlflow.xgboost.load_model", return_value=_mock_model), \
         patch("joblib.load",               return_value=_mock_scaler), \
         patch("mlflow.set_tracking_uri"):
        from api.app       import create_app
        from api.models.db import init_db
        application = create_app()
        application.config["TESTING"] = True
        init_db()
        return application


@pytest.fixture(scope="module")
def http(app):
    return app.test_client()


@pytest.fixture(scope="module")
def api_key(http):
    """Crée un client de test et retourne sa clé brute."""
    r = http.post(
        "/admin/clients",
        json={
            "id_client":    "FONC-001",
            "denomination": "Commune de Test Fonctionnel",
            "adresse":      "1 rue des Tests, 75000 Paris",
        },
        headers=ADMIN_HEADER,
    )
    assert r.status_code == 201, f"Création client échouée : {r.get_json()}"
    client_uuid = r.get_json()["id"]

    r2 = http.post(f"/admin/clients/{client_uuid}/apikey", headers=ADMIN_HEADER)
    assert r2.status_code == 201, f"Génération clé échouée : {r2.get_json()}"
    return r2.get_json()["api_key"]


@pytest.fixture(scope="module")
def client_header(api_key):
    return {"X-API-Key": api_key}


# ── SECTION 1 — Endpoint GET /health ─────────────────────────────────────────

class TestEndpointHealth:
    """Vérifie la disponibilité et la réponse du health-check."""

    def test_health_statut_200(self, http):
        assert http.get("/health").status_code == 200

    def test_health_retourne_json(self, http):
        assert http.get("/health").content_type == "application/json"

    def test_health_champ_status_ok(self, http):
        data = http.get("/health").get_json()
        assert data["status"] == "ok"

    def test_health_champ_model_present(self, http):
        data = http.get("/health").get_json()
        assert "model" in data
        # Le nom réel du modèle n'est vérifiable que hors mode mocké (CI).
        if os.getenv("MLFLOW_URI") != "mock":
            assert "WaterQualityXGBoost" in data["model"]

    def test_health_methode_post_retourne_405(self, http):
        assert http.post("/health").status_code == 405


# ── SECTION 2 — Endpoint GET / ────────────────────────────────────────────────

class TestEndpointIndex:
    """Vérifie que la page d'accueil est accessible."""

    def test_index_statut_valide(self, http):
        assert http.get("/").status_code in (200, 302, 404)


# ── SECTION 3 — Endpoint POST /ingest/manual — Cas nominaux ──────────────────

class TestEndpointIngestManualNominal:
    """Teste les scénarios normaux de prédiction via /ingest/manual."""

    def _post(self, http, client_header, payload=None):
        return http.post(
            "/ingest/manual",
            json=payload or VALID_PAYLOAD,
            headers=client_header,
        )

    def test_ingest_manual_statut_201(self, http, client_header):
        assert self._post(http, client_header).status_code == 201

    def test_ingest_manual_retourne_json(self, http, client_header):
        assert "application/json" in self._post(http, client_header).content_type

    def test_ingest_manual_champs_presents(self, http, client_header):
        data = self._post(http, client_header).get_json()
        assert "prelevement_id" in data
        assert "prediction" in data

    def test_ingest_manual_prediction_champs(self, http, client_header):
        pred = self._post(http, client_header).get_json()["prediction"]
        assert "potable" in pred
        assert "label" in pred
        assert "probability" in pred

    def test_ingest_manual_label_potable(self, http, client_header):
        pred = self._post(http, client_header).get_json()["prediction"]
        assert pred["potable"] == 1
        assert pred["label"] == "Potable"

    def test_ingest_manual_probability_dans_intervalle(self, http, client_header):
        pred = self._post(http, client_header).get_json()["prediction"]
        assert 0.0 <= pred["probability"] <= 1.0

    def test_ingest_manual_sans_content_type(self, http, client_header):
        """L'API accepte le JSON même sans Content-Type explicite (force=True)."""
        r = http.post(
            "/ingest/manual",
            data=json.dumps(VALID_PAYLOAD),
            headers=client_header,
        )
        assert r.status_code == 201


# ── SECTION 4 — Endpoint POST /ingest/manual — Cas d'erreur ──────────────────

class TestEndpointIngestManualErreurs:
    """Teste que l'API renvoie des erreurs cohérentes pour des inputs invalides."""

    def _post(self, http, client_header, payload):
        return http.post("/ingest/manual", json=payload, headers=client_header)

    def test_feature_manquante_retourne_400(self, http, client_header):
        payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "ph"}
        assert self._post(http, client_header, payload).status_code == 400

    def test_feature_manquante_message_erreur(self, http, client_header):
        payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "ph"}
        data = self._post(http, client_header, payload).get_json()
        assert "error" in data

    def test_valeur_string_retourne_400(self, http, client_header):
        payload = {**VALID_PAYLOAD, "ph": "abc"}
        assert self._post(http, client_header, payload).status_code == 400

    def test_payload_vide_retourne_400(self, http, client_header):
        assert self._post(http, client_header, {}).status_code == 400

    def test_erreur_toujours_json(self, http, client_header):
        payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "Turbidity"}
        r = self._post(http, client_header, payload)
        try:
            r.get_json()
        except Exception:
            pytest.fail("La réponse d'erreur n'est pas du JSON valide")

    @pytest.mark.parametrize("missing_feature", FEATURES)
    def test_chaque_feature_manquante_detectee(self, http, client_header, missing_feature):
        payload = {k: v for k, v in VALID_PAYLOAD.items() if k != missing_feature}
        r = self._post(http, client_header, payload)
        assert r.status_code == 400, f"Feature '{missing_feature}' manquante non détectée"


# ── SECTION 5 — Sécurité : authentification ──────────────────────────────────

class TestAuthentification:
    """Vérifie que les routes protégées rejettent les requêtes sans clé valide."""

    def test_ingest_manual_sans_cle_retourne_401(self, http):
        assert http.post("/ingest/manual", json=VALID_PAYLOAD).status_code == 401

    def test_ingest_manual_cle_invalide_retourne_401(self, http):
        r = http.post(
            "/ingest/manual",
            json=VALID_PAYLOAD,
            headers={"X-API-Key": "cle-invalide-xyz"},
        )
        assert r.status_code == 401

    def test_admin_sans_token_retourne_401(self, http):
        assert http.get("/admin/clients").status_code == 401

    def test_analyste_sans_token_retourne_401(self, http):
        assert http.get("/analyste/prelevements").status_code == 401


# ── SECTION 6 — Intégration modèle + API ─────────────────────────────────────

class TestIntegrationModelAPI:
    """Tests de bout en bout : cohérence entre modèle et réponse."""

    @pytest.mark.parametrize("pred_val,proba_val,expected_label", [
        (1, 0.95, "Potable"),
        (1, 0.55, "Potable"),
        (0, 0.45, "Non potable"),
        (0, 0.05, "Non potable"),
    ])
    def test_coherence_prediction_label(
        self, http, client_header, pred_val, proba_val, expected_label
    ):
        mock = MagicMock()
        mock.predict.return_value       = np.array([pred_val])
        mock.predict_proba.return_value = np.array([[1 - proba_val, proba_val]])
        with patch("predict_service._model", mock):
            r    = http.post("/ingest/manual", json=VALID_PAYLOAD, headers=client_header)
            pred = r.get_json()["prediction"]
            assert pred["label"]   == expected_label
            assert pred["potable"] == pred_val
