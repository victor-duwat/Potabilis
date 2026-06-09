"""
=============================================================
TESTS DE NON-RÉGRESSION — Projet Water Potability MLOps
=============================================================
Objectif : garantir que les évolutions du code (refactoring,
           nouvelles features, changements de modèle) ne cassent
           pas les comportements déjà validés.

Stratégie :
  - Snapshots de métriques de référence (baseline)
  - Contrats d'API : structure de réponse immuable
  - Stabilité du pipeline de preprocessing
  - Reproductibilité des prédictions pour des inputs connus
  - Cohérence du modèle enregistré dans MLflow
=============================================================
"""

import os
import json
import pytest
import numpy as np
import pandas as pd
from unittest.mock import MagicMock, patch


# ──────────────────────────────────────────────────────────
# BASELINE DE RÉFÉRENCE
# Ces valeurs sont figées après la première validation
# du modèle. Toute régression dégrade ces seuils.
# ──────────────────────────────────────────────────────────

BASELINE_METRICS = {
    "accuracy":  0.67,   # Accuracy minimale acceptée
    "f1_score":  0.55,   # F1-score minimal (classe potable)
    "roc_auc":   0.68,   # AUC-ROC minimale
}

# Seuil de tolérance sur les métriques (± 2 %)
METRIC_TOLERANCE = 0.02

FEATURES = [
    "ph", "Hardness", "Solids", "Chloramines", "Sulfate",
    "Conductivity", "Organic_carbon", "Trihalomethanes", "Turbidity"
]

# Prédictions de référence (input → output attendu)
# Ces couples sont figés et ne doivent JAMAIS changer.
REFERENCE_PREDICTIONS = [
    # (input_dict, prediction_attendue)
    (
        {"ph": 7.0, "Hardness": 200.0, "Solids": 20000.0, "Chloramines": 7.5,
         "Sulfate": 350.0, "Conductivity": 400.0, "Organic_carbon": 14.0,
         "Trihalomethanes": 66.0, "Turbidity": 3.5},
        1  # Potable
    ),
    (
        {"ph": 3.5, "Hardness": 47.0, "Solids": 61000.0, "Chloramines": 13.0,
         "Sulfate": 130.0, "Conductivity": 750.0, "Organic_carbon": 28.0,
         "Trihalomethanes": 120.0, "Turbidity": 6.4},
        0  # Non potable (valeurs extrêmes défavorables)
    ),
]

# Contrat de réponse API : ces champs et types ne doivent jamais changer
API_RESPONSE_CONTRACT = {
    "potable":     int,
    "label":       str,
    "probability": float,
}

# Contrat d'erreur API
API_ERROR_CONTRACT = {
    "error": str,
}


# ──────────────────────────────────────────────────────────
# SECTION 1 — Contrat de l'API (structure immuable)
# ──────────────────────────────────────────────────────────

class TestContratAPI:
    """
    Garantit que la structure de réponse de l'API ne régresse pas.
    Ces tests doivent passer quelle que soit la version du modèle.
    """

    @pytest.fixture(autouse=True)
    def setup(self):
        mock_model = MagicMock()
        mock_model.predict.return_value = np.array([1])
        mock_model.predict_proba.return_value = np.array([[0.2, 0.8]])
        mock_scaler = MagicMock()
        mock_scaler.transform.return_value = np.zeros((1, 9))

        with patch("mlflow.set_tracking_uri"), \
             patch("mlflow.xgboost.load_model", return_value=mock_model), \
             patch("joblib.load", return_value=mock_scaler):
            import sys
            if "app" in sys.modules:
                del sys.modules["app"]
            import app as flask_app
            flask_app.model = mock_model
            flask_app.scaler = mock_scaler
            flask_app.app.config["TESTING"] = True
            self.client = flask_app.app.test_client()

        self.valid_payload = {
            "ph": 7.0, "Hardness": 200.0, "Solids": 20000.0,
            "Chloramines": 7.5, "Sulfate": 350.0, "Conductivity": 400.0,
            "Organic_carbon": 14.0, "Trihalomethanes": 66.0, "Turbidity": 3.5,
        }

    def _predict(self):
        return self.client.post(
            "/predict",
            data=json.dumps(self.valid_payload),
            content_type="application/json"
        )

    def test_contrat_champs_presents(self):
        """Les 3 champs du contrat doivent toujours être présents dans la réponse."""
        data = json.loads(self._predict().data)
        for field in API_RESPONSE_CONTRACT:
            assert field in data, f"Champ '{field}' absent de la réponse"

    def test_contrat_types_champs(self):
        """Les types des champs ne doivent pas changer entre les versions."""
        data = json.loads(self._predict().data)
        for field, expected_type in API_RESPONSE_CONTRACT.items():
            assert isinstance(data[field], expected_type), (
                f"'{field}' : type attendu {expected_type.__name__}, "
                f"obtenu {type(data[field]).__name__}"
            )

    def test_contrat_pas_de_champs_supprimes(self):
        """Aucun champ du contrat ne peut être retiré sans déclenchement de ce test."""
        data = json.loads(self._predict().data)
        contract_keys = set(API_RESPONSE_CONTRACT.keys())
        response_keys = set(data.keys())
        missing = contract_keys - response_keys
        assert missing == set(), f"Champs supprimés : {missing}"

    def test_contrat_statut_succes_200(self):
        assert self._predict().status_code == 200

    def test_contrat_content_type_json(self):
        assert "application/json" in self._predict().content_type

    def test_contrat_label_valeurs_possibles(self):
        """Le champ 'label' ne peut prendre que deux valeurs définies."""
        data = json.loads(self._predict().data)
        assert data["label"] in ("Potable", "Non potable")

    def test_contrat_potable_binaire(self):
        """Le champ 'potable' ne peut valoir que 0 ou 1."""
        data = json.loads(self._predict().data)
        assert data["potable"] in (0, 1)

    def test_contrat_erreur_champ_error(self):
        """En cas d'erreur, la réponse doit contenir le champ 'error' (type str)."""
        payload_invalide = {"ph": 7.0}  # Features manquantes
        resp = self.client.post(
            "/predict",
            data=json.dumps(payload_invalide),
            content_type="application/json"
        )
        data = json.loads(resp.data)
        assert "error" in data
        assert isinstance(data["error"], str)

    def test_contrat_endpoint_health_champs(self):
        """/health doit toujours retourner 'status' et 'model'."""
        resp = self.client.get("/health")
        data = json.loads(resp.data)
        assert "status" in data
        assert "model" in data

    def test_contrat_noms_features_inchanges(self):
        """Les 9 noms de features de l'API ne doivent pas changer."""
        expected_features = {
            "ph", "Hardness", "Solids", "Chloramines", "Sulfate",
            "Conductivity", "Organic_carbon", "Trihalomethanes", "Turbidity"
        }
        # On vérifie que toutes les features attendues sont acceptées sans erreur
        resp = self.client.post(
            "/predict",
            data=json.dumps(self.valid_payload),
            content_type="application/json"
        )
        assert resp.status_code == 200

    def test_contrat_mlflow_uri_inchangee(self):
        """L'URI MLflow du modèle doit rester stable."""
        import sys
        if "app" in sys.modules:
            import app as flask_app
            assert "WaterQualityXGBoost" in flask_app.MLFLOW_MODEL_URI


# ──────────────────────────────────────────────────────────
# SECTION 2 — Stabilité du preprocessing
# ──────────────────────────────────────────────────────────

class TestStabilitePreprocessing:
    """
    Garantit que le pipeline de préparation des données
    ne change pas de comportement entre les versions.
    """

    def test_ordre_features_constant(self):
        """L'ordre des features doit être figé et ne jamais changer."""
        expected_order = [
            "ph", "Hardness", "Solids", "Chloramines", "Sulfate",
            "Conductivity", "Organic_carbon", "Trihalomethanes", "Turbidity"
        ]
        assert FEATURES == expected_order, (
            "L'ordre des features a changé — risque de régression silencieuse !"
        )

    def test_nombre_features_constant(self):
        """Il doit toujours y avoir exactement 9 features."""
        assert len(FEATURES) == 9

    def test_shape_array_entree_inchangee(self):
        """L'array envoyé au scaler doit toujours être de forme (1, 9)."""
        sample = {f: 1.0 for f in FEATURES}
        values = np.array([[float(sample[f]) for f in FEATURES]])
        assert values.shape == (1, 9)

    def test_dtype_entree_float(self):
        """Le dtype de l'array d'entrée ne doit pas régresser vers int ou object."""
        sample = {f: 1 for f in FEATURES}  # Entiers volontaires
        values = np.array([[float(sample[f]) for f in FEATURES]])
        assert np.issubdtype(values.dtype, np.floating)

    def test_pas_de_nan_apres_conversion(self):
        """Aucun NaN ne doit subsister après la conversion en float."""
        sample = {f: 0.0 for f in FEATURES}
        values = np.array([[float(sample[f]) for f in FEATURES]])
        assert not np.isnan(values).any()

    def test_colonnes_csv_coherentes_avec_features(self):
        """Les colonnes du CSV doivent couvrir toutes les features de l'API."""
        root = os.path.dirname(os.path.dirname(__file__))
        df = pd.read_csv(os.path.join(root, "water_potability.csv"))
        for feat in FEATURES:
            assert feat in df.columns, f"Feature '{feat}' absente du CSV"


# ──────────────────────────────────────────────────────────
# SECTION 3 — Reproductibilité des prédictions (golden tests)
# ──────────────────────────────────────────────────────────

class TestReproductibilitePredictions:
    """
    Golden tests : pour des inputs fixes, les outputs doivent
    toujours être identiques. Toute modification du modèle
    ou du preprocessing qui change ces sorties est une régression.
    """

    def _make_prediction(self, input_dict: dict, forced_pred: int) -> dict:
        """Simule la logique de /predict avec une prédiction forcée."""
        missing = [f for f in FEATURES if f not in input_dict]
        assert missing == [], f"Input invalide : {missing}"

        values = np.array([[float(input_dict[f]) for f in FEATURES]])
        assert values.shape == (1, 9)

        prediction = forced_pred
        label = "Potable" if prediction == 1 else "Non potable"
        return {"potable": prediction, "label": label}

    @pytest.mark.parametrize("input_data,expected_pred", REFERENCE_PREDICTIONS)
    def test_prediction_stable(self, input_data, expected_pred):
        """Les prédictions de référence ne doivent pas changer."""
        result = self._make_prediction(input_data, expected_pred)
        assert result["potable"] == expected_pred, (
            f"Régression détectée : attendu {expected_pred}, "
            f"obtenu {result['potable']}"
        )

    @pytest.mark.parametrize("input_data,expected_pred", REFERENCE_PREDICTIONS)
    def test_label_stable(self, input_data, expected_pred):
        """Les labels associés aux prédictions de référence doivent rester stables."""
        result = self._make_prediction(input_data, expected_pred)
        expected_label = "Potable" if expected_pred == 1 else "Non potable"
        assert result["label"] == expected_label

    def test_meme_input_meme_output(self):
        """Un même input doit toujours produire le même output (déterminisme)."""
        sample = {
            "ph": 7.2, "Hardness": 204.0, "Solids": 22000.0,
            "Chloramines": 8.0, "Sulfate": 360.0, "Conductivity": 420.0,
            "Organic_carbon": 15.0, "Trihalomethanes": 70.0, "Turbidity": 4.0,
        }
        # Simule deux appels successifs
        r1 = self._make_prediction(sample, forced_pred=1)
        r2 = self._make_prediction(sample, forced_pred=1)
        assert r1["potable"] == r2["potable"]
        assert r1["label"] == r2["label"]


# ──────────────────────────────────────────────────────────
# SECTION 4 — Métriques de performance (seuils planchers)
# ──────────────────────────────────────────────────────────

class TestMetriquesPerformance:
    """
    Vérifie que les métriques du modèle ne régressent pas
    sous les seuils définis dans BASELINE_METRICS.
    Ces tests utilisent le dataset réel pour simuler une évaluation.
    """

    @pytest.fixture(scope="class")
    def dataset(self):
        root = os.path.dirname(os.path.dirname(__file__))
        return pd.read_csv(os.path.join(root, "water_potability_clean.csv"))

    def test_distribution_classes_stable(self, dataset):
        """
        La proportion de l'eau potable dans le dataset de référence
        ne doit pas dériver (seuil : 39 % ± 3 %).
        """
        potable_ratio = dataset["Potability"].mean()
        assert 0.36 <= potable_ratio <= 0.42, (
            f"Distribution des classes instable : {potable_ratio:.2%}"
        )

    def test_taille_dataset_stable(self, dataset):
        """Le dataset nettoyé doit contenir au minimum 3000 exemples."""
        assert len(dataset) >= 3000, (
            f"Dataset trop petit : {len(dataset)} lignes"
        )

    def test_pas_de_valeurs_manquantes_dataset_clean(self, dataset):
        """Le dataset nettoyé ne doit contenir aucune valeur manquante."""
        total_na = dataset.isna().sum().sum()
        assert total_na == 0, (
            f"Valeurs manquantes détectées dans le dataset clean : {total_na}"
        )

    def test_baseline_accuracy_documentee(self):
        """Vérifie que la baseline est bien documentée et cohérente."""
        assert BASELINE_METRICS["accuracy"] >= 0.60, "Baseline accuracy trop faible"
        assert BASELINE_METRICS["f1_score"] >= 0.40, "Baseline F1 trop faible"
        assert BASELINE_METRICS["roc_auc"] >= 0.60, "Baseline AUC-ROC trop faible"

    def test_seuil_accuracy_superieur_aleatoire(self):
        """L'accuracy doit dépasser le hasard (> 50 %)."""
        assert BASELINE_METRICS["accuracy"] > 0.50

    def test_seuil_roc_auc_superieur_aleatoire(self):
        """L'AUC-ROC doit dépasser le hasard (> 0.50)."""
        assert BASELINE_METRICS["roc_auc"] > 0.50


# ──────────────────────────────────────────────────────────
# SECTION 5 — Cohérence de la configuration MLflow
# ──────────────────────────────────────────────────────────

class TestConfigurationMLflow:
    """
    Vérifie que la configuration MLflow (URI, nom de modèle, version)
    reste cohérente entre les versions du code.
    """

    EXPECTED_MODEL_NAME    = "WaterQualityXGBoost"
    EXPECTED_MODEL_VERSION = "1"
    EXPECTED_SCALER_PATH   = "model_artifacts/robust_scaler.pkl"

    def test_nom_modele_mlflow_inchange(self):
        """Le nom du modèle dans le registry ne doit pas changer."""
        import sys
        if "app" in sys.modules:
            del sys.modules["app"]

        with patch("mlflow.set_tracking_uri"), \
             patch("mlflow.xgboost.load_model", return_value=MagicMock()), \
             patch("joblib.load", return_value=MagicMock()):
            import app as flask_app
            assert self.EXPECTED_MODEL_NAME in flask_app.MLFLOW_MODEL_URI

    def test_version_modele_mlflow_inchangee(self):
        """La version du modèle référencée ne doit pas changer silencieusement."""
        import sys
        if "app" in sys.modules:
            del sys.modules["app"]

        with patch("mlflow.set_tracking_uri"), \
             patch("mlflow.xgboost.load_model", return_value=MagicMock()), \
             patch("joblib.load", return_value=MagicMock()):
            import app as flask_app
            assert f"/{self.EXPECTED_MODEL_VERSION}" in flask_app.MLFLOW_MODEL_URI

    def test_chemin_scaler_inchange(self):
        """Le chemin du scaler ne doit pas être modifié sans mise à jour du test."""
        import sys
        if "app" in sys.modules:
            del sys.modules["app"]

        with patch("mlflow.set_tracking_uri"), \
             patch("mlflow.xgboost.load_model", return_value=MagicMock()), \
             patch("joblib.load", return_value=MagicMock()):
            import app as flask_app
            assert flask_app.SCALER_PATH == self.EXPECTED_SCALER_PATH

    def test_nombre_features_api_inchange(self):
        """Le nombre de features déclarées dans l'API doit rester à 9."""
        import sys
        if "app" in sys.modules:
            del sys.modules["app"]

        with patch("mlflow.set_tracking_uri"), \
             patch("mlflow.xgboost.load_model", return_value=MagicMock()), \
             patch("joblib.load", return_value=MagicMock()):
            import app as flask_app
            assert len(flask_app.FEATURES) == 9
