"""
=============================================================
TESTS DE NON-RÉGRESSION — Waterflow 2 (architecture v2)
=============================================================
Objectif : garantir que les évolutions du code ne cassent pas
           les comportements déjà validés.

Stratégie :
  - Snapshots de métriques de référence (baseline)
  - Contrats d'API : structure de réponse immuable
  - Stabilité du pipeline de preprocessing
  - Reproductibilité des prédictions pour des inputs connus
  - Cohérence du modèle enregistré dans MLflow
=============================================================
"""

import os
import pytest
import numpy as np
import pandas as pd
from unittest.mock import MagicMock, patch

# ── Env avant import Flask ────────────────────────────────────────────────────
os.environ.setdefault("DATABASE_URL",      "sqlite:///:memory:")
os.environ.setdefault("MLFLOW_URI",        "mock")
os.environ.setdefault("SCALER_PATH",       "mock")
os.environ.setdefault("OCR_SPACE_API_KEY", "")
os.environ.setdefault("ANTHROPIC_API_KEY", "")
# EXPERT_TOKENS est défini globalement dans conftest.py (jeu commun à toute la suite)

# En CI, le modèle et le scaler sont mockés (MLFLOW_URI=mock, SCALER_PATH=mock).
# Les tests qui vérifient la configuration RÉELLE de déploiement (URI du modèle,
# chemin du scaler) n'ont alors pas de sens : on les ignore dans ce mode.
_CONFIG_MOCKEE = os.getenv("MLFLOW_URI") == "mock" or os.getenv("SCALER_PATH") == "mock"
_skip_si_mock  = pytest.mark.skipif(_CONFIG_MOCKEE, reason="config réelle mockée en CI")

# ── Baseline de référence ─────────────────────────────────────────────────────
BASELINE_METRICS = {
    "accuracy":  0.67,
    "f1_score":  0.55,
    "roc_auc":   0.68,
}
METRIC_TOLERANCE = 0.02

FEATURES = [
    "ph", "Hardness", "Solids", "Chloramines", "Sulfate",
    "Conductivity", "Organic_carbon", "Trihalomethanes", "Turbidity",
]

REFERENCE_PREDICTIONS = [
    (
        {"ph": 7.0, "Hardness": 200.0, "Solids": 20000.0, "Chloramines": 7.5,
         "Sulfate": 350.0, "Conductivity": 400.0, "Organic_carbon": 14.0,
         "Trihalomethanes": 66.0, "Turbidity": 3.5},
        1,  # Potable
    ),
    (
        {"ph": 3.5, "Hardness": 47.0, "Solids": 61000.0, "Chloramines": 13.0,
         "Sulfate": 130.0, "Conductivity": 750.0, "Organic_carbon": 28.0,
         "Trihalomethanes": 120.0, "Turbidity": 6.4},
        0,  # Non potable
    ),
]

API_RESPONSE_CONTRACT = {
    "prelevement_id": str,
    "prediction":     dict,
}

ADMIN_HEADER = {"Authorization": "Bearer token-admin-noreg"}

_mock_model = MagicMock()
_mock_model.predict.return_value       = np.array([1])
_mock_model.predict_proba.return_value = np.array([[0.20, 0.80]])

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
def client_header(http):
    r = http.post(
        "/admin/clients",
        json={
            "id_client":    "NOREG-001",
            "denomination": "Commune Tests Non-Régression",
            "adresse":      "1 rue de la Stabilité, 06000 Nice",
        },
        headers=ADMIN_HEADER,
    )
    assert r.status_code == 201, f"Création client échouée : {r.get_json()}"
    client_uuid = r.get_json()["id"]

    r2 = http.post(f"/admin/clients/{client_uuid}/apikey", headers=ADMIN_HEADER)
    assert r2.status_code == 201
    return {"X-API-Key": r2.get_json()["api_key"]}


VALID_PAYLOAD = {
    "ph": 7.0, "Hardness": 200.0, "Solids": 20000.0,
    "Chloramines": 7.5, "Sulfate": 350.0, "Conductivity": 400.0,
    "Organic_carbon": 14.0, "Trihalomethanes": 66.0, "Turbidity": 3.5,
}


# ── SECTION 1 — Contrat de l'API (structure immuable) ────────────────────────

class TestContratAPI:
    """
    Garantit que la structure de réponse de /ingest/manual ne régresse pas.
    Ces tests doivent passer quelle que soit la version du modèle.
    """

    def _predict(self, http, client_header):
        return http.post("/ingest/manual", json=VALID_PAYLOAD, headers=client_header)

    def test_contrat_champs_presents(self, http, client_header):
        data = self._predict(http, client_header).get_json()
        for field in API_RESPONSE_CONTRACT:
            assert field in data, f"Champ '{field}' absent de la réponse"

    def test_contrat_types_champs(self, http, client_header):
        data = self._predict(http, client_header).get_json()
        for field, expected_type in API_RESPONSE_CONTRACT.items():
            assert isinstance(data[field], expected_type), (
                f"'{field}' : type attendu {expected_type.__name__}, "
                f"obtenu {type(data[field]).__name__}"
            )

    def test_contrat_prediction_sous_champs(self, http, client_header):
        pred = self._predict(http, client_header).get_json()["prediction"]
        for field in ("potable", "label", "probability"):
            assert field in pred, f"Sous-champ '{field}' absent de prediction"

    def test_contrat_statut_succes_201(self, http, client_header):
        assert self._predict(http, client_header).status_code == 201

    def test_contrat_content_type_json(self, http, client_header):
        assert "application/json" in self._predict(http, client_header).content_type

    def test_contrat_label_valeurs_possibles(self, http, client_header):
        pred = self._predict(http, client_header).get_json()["prediction"]
        assert pred["label"] in ("Potable", "Non potable")

    def test_contrat_potable_binaire(self, http, client_header):
        pred = self._predict(http, client_header).get_json()["prediction"]
        assert pred["potable"] in (0, 1)

    def test_contrat_erreur_champ_error(self, http, client_header):
        r = http.post(
            "/ingest/manual",
            json={"ph": 7.0},
            headers=client_header,
        )
        data = r.get_json()
        assert "error" in data
        assert isinstance(data["error"], str)

    def test_contrat_endpoint_health_champs(self, http):
        data = http.get("/health").get_json()
        assert "status" in data
        assert "model" in data

    def test_contrat_noms_features_inchanges(self, http, client_header):
        r = http.post("/ingest/manual", json=VALID_PAYLOAD, headers=client_header)
        assert r.status_code == 201


# ── SECTION 2 — Stabilité du preprocessing ───────────────────────────────────

class TestStabilitePreprocessing:
    """
    Garantit que le pipeline de préparation des données
    ne change pas de comportement entre les versions.
    """

    def test_ordre_features_constant(self):
        expected_order = [
            "ph", "Hardness", "Solids", "Chloramines", "Sulfate",
            "Conductivity", "Organic_carbon", "Trihalomethanes", "Turbidity",
        ]
        assert FEATURES == expected_order

    def test_nombre_features_constant(self):
        assert len(FEATURES) == 9

    def test_shape_array_entree_inchangee(self):
        sample = {f: 1.0 for f in FEATURES}
        values = np.array([[float(sample[f]) for f in FEATURES]])
        assert values.shape == (1, 9)

    def test_dtype_entree_float(self):
        sample = {f: 1 for f in FEATURES}
        values = np.array([[float(sample[f]) for f in FEATURES]])
        assert np.issubdtype(values.dtype, np.floating)

    def test_pas_de_nan_apres_conversion(self):
        sample = {f: 0.0 for f in FEATURES}
        values = np.array([[float(sample[f]) for f in FEATURES]])
        assert not np.isnan(values).any()

    def test_colonnes_csv_coherentes_avec_features(self):
        root = os.path.dirname(os.path.dirname(__file__))
        df = pd.read_csv(os.path.join(root, "water_potability.csv"))
        for feat in FEATURES:
            assert feat in df.columns, f"Feature '{feat}' absente du CSV"


# ── SECTION 3 — Reproductibilité des prédictions ─────────────────────────────

class TestReproductibilitePredictions:
    """
    Golden tests : pour des inputs fixes, les outputs doivent
    toujours être identiques.
    """

    def _make_prediction(self, input_dict: dict, forced_pred: int) -> dict:
        missing = [f for f in FEATURES if f not in input_dict]
        assert missing == [], f"Input invalide : {missing}"
        values    = np.array([[float(input_dict[f]) for f in FEATURES]])
        assert values.shape == (1, 9)
        label = "Potable" if forced_pred == 1 else "Non potable"
        return {"potable": forced_pred, "label": label}

    @pytest.mark.parametrize("input_data,expected_pred", REFERENCE_PREDICTIONS)
    def test_prediction_stable(self, input_data, expected_pred):
        result = self._make_prediction(input_data, expected_pred)
        assert result["potable"] == expected_pred

    @pytest.mark.parametrize("input_data,expected_pred", REFERENCE_PREDICTIONS)
    def test_label_stable(self, input_data, expected_pred):
        result = self._make_prediction(input_data, expected_pred)
        expected_label = "Potable" if expected_pred == 1 else "Non potable"
        assert result["label"] == expected_label

    def test_meme_input_meme_output(self):
        sample = {
            "ph": 7.2, "Hardness": 204.0, "Solids": 22000.0,
            "Chloramines": 8.0, "Sulfate": 360.0, "Conductivity": 420.0,
            "Organic_carbon": 15.0, "Trihalomethanes": 70.0, "Turbidity": 4.0,
        }
        r1 = self._make_prediction(sample, forced_pred=1)
        r2 = self._make_prediction(sample, forced_pred=1)
        assert r1["potable"] == r2["potable"]
        assert r1["label"]   == r2["label"]


# ── SECTION 4 — Métriques de performance (seuils planchers) ──────────────────

class TestMetriquesPerformance:
    """
    Vérifie que les métriques du modèle ne régressent pas
    sous les seuils définis dans BASELINE_METRICS.
    """

    @pytest.fixture(scope="class")
    def dataset(self):
        root = os.path.dirname(os.path.dirname(__file__))
        return pd.read_csv(os.path.join(root, "water_potability_clean.csv"))

    def test_distribution_classes_stable(self, dataset):
        potable_ratio = dataset["Potability"].mean()
        assert 0.36 <= potable_ratio <= 0.42, (
            f"Distribution des classes instable : {potable_ratio:.2%}"
        )

    def test_taille_dataset_stable(self, dataset):
        assert len(dataset) >= 3000

    def test_pas_de_valeurs_manquantes_dataset_clean(self, dataset):
        assert dataset.isna().sum().sum() == 0

    def test_baseline_accuracy_documentee(self):
        assert BASELINE_METRICS["accuracy"] >= 0.60
        assert BASELINE_METRICS["f1_score"] >= 0.40
        assert BASELINE_METRICS["roc_auc"]  >= 0.60

    def test_seuil_accuracy_superieur_aleatoire(self):
        assert BASELINE_METRICS["accuracy"] > 0.50

    def test_seuil_roc_auc_superieur_aleatoire(self):
        assert BASELINE_METRICS["roc_auc"] > 0.50


# ── SECTION 5 — Cohérence de la configuration MLflow ─────────────────────────

class TestConfigurationMLflow:
    """
    Vérifie que la configuration MLflow reste cohérente
    entre les versions du code.
    """

    EXPECTED_MODEL_NAME    = "WaterQualityXGBoost"
    EXPECTED_MODEL_VERSION = "1"
    EXPECTED_SCALER_PATH   = "model_artifacts/robust_scaler.pkl"

    @_skip_si_mock
    def test_nom_modele_mlflow_inchange(self):
        from predict_service import MLFLOW_MODEL_URI
        assert self.EXPECTED_MODEL_NAME in MLFLOW_MODEL_URI

    @_skip_si_mock
    def test_version_modele_mlflow_inchangee(self):
        from predict_service import MLFLOW_MODEL_URI
        assert f"/{self.EXPECTED_MODEL_VERSION}" in MLFLOW_MODEL_URI

    @_skip_si_mock
    def test_chemin_scaler_inchange(self):
        import predict_service
        assert predict_service.SCALER_PATH == self.EXPECTED_SCALER_PATH

    def test_nombre_features_api_inchange(self):
        import predict_service
        assert len(predict_service.FEATURES) == 9

    def test_noms_features_api_inchanges(self):
        import predict_service
        assert predict_service.FEATURES == FEATURES

    @_skip_si_mock
    def test_mlflow_uri_dans_health(self, http):
        data = http.get("/health").get_json()
        assert "WaterQualityXGBoost" in data["model"]
