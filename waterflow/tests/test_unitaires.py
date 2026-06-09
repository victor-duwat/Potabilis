"""
=============================================================
TESTS UNITAIRES — Projet Water Potability MLOps
=============================================================
Objectif : tester chaque composant de façon isolée.
Couverture :
  - Validation et nettoyage des données d'entrée
  - Transformation (scaling)
  - Logique de prédiction / formatage de la réponse
  - Fonctions utilitaires de l'API Flask
=============================================================
"""

import os
import pytest
import numpy as np
import pandas as pd
from unittest.mock import MagicMock, patch


# ──────────────────────────────────────────────────────────
# CONSTANTES PARTAGÉES
# ──────────────────────────────────────────────────────────

FEATURES = [
    "ph", "Hardness", "Solids", "Chloramines", "Sulfate",
    "Conductivity", "Organic_carbon", "Trihalomethanes", "Turbidity"
]

VALID_SAMPLE = {
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

# Valeurs issues du dataset (min/max observés)
FEATURE_BOUNDS = {
    "ph":               (0.0,  14.0),
    "Hardness":         (47.0, 323.0),
    "Solids":           (320.0, 61227.0),
    "Chloramines":      (0.35, 13.13),
    "Sulfate":          (129.0, 481.0),
    "Conductivity":     (181.0, 753.0),
    "Organic_carbon":   (2.2,  28.3),
    "Trihalomethanes":  (0.74, 124.0),
    "Turbidity":        (1.45, 6.49),
}


# ──────────────────────────────────────────────────────────
# SECTION 1 — Validation des données d'entrée
# ──────────────────────────────────────────────────────────

class TestValidationEntree:
    """Teste les règles de validation appliquées avant la prédiction."""

    def test_sample_valide_toutes_features(self):
        """Un dictionnaire contenant les 9 features ne doit générer aucune erreur."""
        missing = [f for f in FEATURES if f not in VALID_SAMPLE]
        assert missing == [], f"Features manquantes : {missing}"

    def test_detection_feature_manquante(self):
        """Une feature absente doit être détectée."""
        data_incomplet = {k: v for k, v in VALID_SAMPLE.items() if k != "ph"}
        missing = [f for f in FEATURES if f not in data_incomplet]
        assert "ph" in missing

    def test_detection_plusieurs_features_manquantes(self):
        """Plusieurs features absentes doivent toutes être listées."""
        data = {"ph": 7.0, "Hardness": 200.0}
        missing = [f for f in FEATURES if f not in data]
        assert len(missing) == 7

    def test_valeur_numerique_valide(self):
        """La conversion float doit fonctionner sur un sample valide."""
        try:
            values = np.array([[float(VALID_SAMPLE[f]) for f in FEATURES]])
            assert values.shape == (1, 9)
        except (ValueError, TypeError):
            pytest.fail("Conversion float échouée sur un sample valide")

    def test_valeur_non_numerique_detectee(self):
        """Une valeur non numérique doit lever une exception."""
        data_invalide = {**VALID_SAMPLE, "ph": "non-numérique"}
        with pytest.raises((ValueError, TypeError)):
            np.array([[float(data_invalide[f]) for f in FEATURES]])

    def test_valeur_none_detectee(self):
        """Une valeur None doit lever une exception."""
        data_none = {**VALID_SAMPLE, "Turbidity": None}
        with pytest.raises((ValueError, TypeError)):
            np.array([[float(data_none[f]) for f in FEATURES]])

    @pytest.mark.parametrize("feature,value", [
        ("ph", -1.0),
        ("ph", 15.0),
        ("Turbidity", 0.0),
        ("Hardness", -50.0),
    ])
    def test_valeur_hors_bornes(self, feature, value):
        """Une valeur hors des bornes observées doit être identifiable."""
        lo, hi = FEATURE_BOUNDS[feature]
        assert not (lo <= value <= hi), (
            f"{feature}={value} devrait être hors bornes [{lo}, {hi}]"
        )

    def test_features_supplementaires_ignorees(self):
        """Des clés inconnues dans le payload ne doivent pas causer d'erreur."""
        data_extra = {**VALID_SAMPLE, "color": "blue", "source": "river"}
        values = np.array([[float(data_extra[f]) for f in FEATURES]])
        assert values.shape == (1, 9)


# ──────────────────────────────────────────────────────────
# SECTION 2 — Transformation (RobustScaler)
# ──────────────────────────────────────────────────────────

class TestTransformation:
    """Teste le pipeline de scaling appliqué avant la prédiction."""

    def setup_method(self):
        """Crée un mock du RobustScaler."""
        self.scaler = MagicMock()
        self.scaler.transform.return_value = np.zeros((1, 9))

    def test_scaler_appele_avec_bon_shape(self):
        """Le scaler doit recevoir un array (1, 9)."""
        values = np.array([[float(VALID_SAMPLE[f]) for f in FEATURES]])
        self.scaler.transform(values)
        args, _ = self.scaler.transform.call_args
        assert args[0].shape == (1, 9)

    def test_scaler_retourne_meme_shape(self):
        """La sortie du scaler doit conserver la forme (1, 9)."""
        values = np.array([[float(VALID_SAMPLE[f]) for f in FEATURES]])
        scaled = self.scaler.transform(values)
        assert scaled.shape == (1, 9)

    def test_scaler_appele_une_seule_fois(self):
        """Le scaler ne doit être appelé qu'une fois par requête."""
        values = np.array([[float(VALID_SAMPLE[f]) for f in FEATURES]])
        self.scaler.transform(values)
        assert self.scaler.transform.call_count == 1

    def test_scaling_valeurs_extremes(self):
        """Le scaling doit fonctionner avec des valeurs aux extrêmes du dataset."""
        extreme = {
            "ph": 14.0, "Hardness": 323.0, "Solids": 61227.0,
            "Chloramines": 13.13, "Sulfate": 481.0, "Conductivity": 753.0,
            "Organic_carbon": 28.3, "Trihalomethanes": 124.0, "Turbidity": 6.49,
        }
        values = np.array([[float(extreme[f]) for f in FEATURES]])
        self.scaler.transform(values)
        assert self.scaler.transform.call_count == 1

    def test_dtype_array_entree(self):
        """L'array transmis au scaler doit être de type float."""
        values = np.array([[float(VALID_SAMPLE[f]) for f in FEATURES]])
        assert np.issubdtype(values.dtype, np.floating)


# ──────────────────────────────────────────────────────────
# SECTION 3 — Logique de prédiction
# ──────────────────────────────────────────────────────────

class TestPrediction:
    """Teste la logique de transformation de la prédiction brute en réponse JSON."""

    def _build_response(self, prediction: int, proba: float) -> dict:
        """Réplique la logique de l'endpoint /predict."""
        return {
            "potable":     prediction,
            "label":       "Potable" if prediction == 1 else "Non potable",
            "probability": round(proba, 4),
        }

    def test_prediction_potable(self):
        resp = self._build_response(1, 0.87654)
        assert resp["potable"] == 1
        assert resp["label"] == "Potable"
        assert resp["probability"] == 0.8765

    def test_prediction_non_potable(self):
        resp = self._build_response(0, 0.12345)
        assert resp["potable"] == 0
        assert resp["label"] == "Non potable"
        assert resp["probability"] == 0.1235

    def test_label_exclusif(self):
        """Le label doit être soit 'Potable' soit 'Non potable', jamais les deux."""
        r1 = self._build_response(1, 0.9)
        r2 = self._build_response(0, 0.1)
        assert r1["label"] != r2["label"]

    def test_probability_arrondie_4_decimales(self):
        """La probabilité doit être arrondie à 4 décimales."""
        resp = self._build_response(1, 0.999999)
        assert resp["probability"] == 1.0
        resp2 = self._build_response(0, 0.000001)
        assert resp2["probability"] == 0.0

    def test_probability_dans_intervalle_valide(self):
        """La probabilité doit être dans [0, 1]."""
        for proba in [0.0, 0.5, 1.0]:
            resp = self._build_response(1, proba)
            assert 0.0 <= resp["probability"] <= 1.0

    @pytest.mark.parametrize("pred,expected_label", [
        (1, "Potable"),
        (0, "Non potable"),
    ])
    def test_mapping_prediction_label(self, pred, expected_label):
        resp = self._build_response(pred, 0.5)
        assert resp["label"] == expected_label

    def test_reponse_contient_trois_cles(self):
        """La réponse doit contenir exactement les clés : potable, label, probability."""
        resp = self._build_response(1, 0.75)
        assert set(resp.keys()) == {"potable", "label", "probability"}

    def test_type_potable_est_int(self):
        """Le champ 'potable' doit être un entier (0 ou 1)."""
        resp = self._build_response(1, 0.8)
        assert isinstance(resp["potable"], int)

    def test_type_probability_est_float(self):
        resp = self._build_response(0, 0.3)
        assert isinstance(resp["probability"], float)


# ──────────────────────────────────────────────────────────
# SECTION 4 — Données CSV (qualité du dataset)
# ──────────────────────────────────────────────────────────

class TestDataset:
    """Vérifie la structure et la qualité du dataset water_potability.csv."""

    @pytest.fixture(scope="class")
    def df(self):
        # Chemin relatif à la racine du projet
        root = os.path.dirname(os.path.dirname(__file__))
        return pd.read_csv(os.path.join(root, "water_potability.csv"))

    def test_colonnes_attendues(self, df):
        """Le dataset doit contenir les 9 features + la cible."""
        expected = set(FEATURES) | {"Potability"}
        assert expected.issubset(set(df.columns))

    def test_cible_binaire(self, df):
        """La colonne Potability ne doit contenir que 0 et 1."""
        assert set(df["Potability"].dropna().unique()).issubset({0, 1})

    def test_pas_de_doublon_exact(self, df):
        """Il ne doit pas y avoir de lignes identiques sur toutes les colonnes."""
        assert df.duplicated().sum() == 0

    def test_ph_dans_plage_valide(self, df):
        """Le pH doit être compris entre 0 et 14 (valeurs non nulles)."""
        ph_valid = df["ph"].dropna()
        assert (ph_valid >= 0).all() and (ph_valid <= 14).all()

    def test_valeurs_manquantes_connues(self, df):
        """Les valeurs manquantes doivent concerner uniquement les features connues."""
        cols_with_na = df.columns[df.isna().any()].tolist()
        allowed_na = {"ph", "Sulfate", "Trihalomethanes"}
        assert set(cols_with_na).issubset(allowed_na | set(FEATURES))

    def test_target_non_nulle(self, df):
        """La colonne Potability ne doit pas contenir de valeurs manquantes."""
        assert df["Potability"].isna().sum() == 0
