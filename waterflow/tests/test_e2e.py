"""
tests/test_e2e.py — Test de bout en bout Waterflow 2

Pipeline testé :
    Fiche labo (image/PDF) → POST /ingest/ocr-and-predict
    → OCR extrait les mesures (mocké)
    → Prélèvement structuré créé en DB
    → Modèle XGBoost prédit la potabilité (mocké)
    → Résultat récupérable via GET /me/prelevements

Ce test couvre l'exigence du cahier des charges :
  « au moins un test de bout en bout »
"""

import os
import io
import pytest
import numpy as np
from unittest.mock import patch, MagicMock

# ── Variables d'environnement avant tout import Flask ────────────────────────
os.environ.setdefault("DATABASE_URL",      "sqlite:///:memory:")
os.environ.setdefault("MLFLOW_URI",        "mock")
os.environ.setdefault("SCALER_PATH",       "mock")
os.environ.setdefault("OCR_SPACE_API_KEY", "")
os.environ.setdefault("ANTHROPIC_API_KEY", "")
os.environ["EXPERT_TOKENS"] = "admin:token-admin-e2e:exploit"

# ── OCR simulé — résultat d'une fiche labo correctement extraite ─────────────
MOCK_OCR_RESULT = {
    "date_prelevement": "2025-03-18",
    "id_client":        "E2E-001",
    "lieu":             "Puits privé — Laboratoire AquaTest",
    "mesures": {
        "ph":              7.6,
        "Hardness":        182.3,
        "Solids":          18450.0,
        "Chloramines":     8.1,
        "Sulfate":         310.0,
        "Conductivity":    415.0,
        "Organic_carbon":  14.2,
        "Trihalomethanes": 66.4,
        "Turbidity":       3.8,
    },
    "observations": "Eau claire, prélèvement matinal.",
    "warnings":     [],
    "raw_text":     "Laboratoire AquaTest Provence\npH : 7,6\nConductivité : 415 µS/cm",
}

# ── Mocks ML ─────────────────────────────────────────────────────────────────
_mock_model  = MagicMock()
_mock_model.predict.return_value       = np.array([1])
_mock_model.predict_proba.return_value = np.array([[0.14, 0.86]])

_mock_scaler = MagicMock()
_mock_scaler.transform.side_effect = lambda x: x

ADMIN_HEADER = {"Authorization": "Bearer token-admin-e2e"}


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
def client_api_key(http):
    """Crée un client E2E et retourne sa clé brute."""
    r = http.post("/admin/clients",
                  json={"id_client":    "E2E-001",
                        "denomination": "Laboratoire AquaTest Provence",
                        "adresse":      "12 rue des Sources, 13009 Marseille"},
                  headers=ADMIN_HEADER)
    assert r.status_code == 201, f"Création client échouée : {r.get_json()}"
    client_uuid = r.get_json()["id"]

    r2 = http.post(f"/admin/clients/{client_uuid}/apikey", headers=ADMIN_HEADER)
    assert r2.status_code == 201, f"Génération clé échouée : {r2.get_json()}"
    return r2.get_json()["api_key"]


@pytest.fixture(scope="module")
def client_header(client_api_key):
    return {"X-API-Key": client_api_key}


# ── Test E2E principal ────────────────────────────────────────────────────────

class TestE2EPipelineOcrPredict:
    """
    Pipeline complet : fiche labo → OCR → prélèvement → prédiction.
    Le service OCR est mocké pour que le test soit reproductible sans clé API.
    """

    @pytest.fixture(autouse=True)
    def patch_ocr(self):
        """Remplace l'appel OCR réel par le résultat simulé."""
        with patch(
            "api.services.ocr_service.extract_from_document",
            return_value=MOCK_OCR_RESULT,
        ):
            yield

    def _fake_pdf(self) -> io.BytesIO:
        """Fichier PDF minimal valide (1 ko) pour le test multipart."""
        content = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\nxref\n0 1\n0000000000 65535 f\n"
        return io.BytesIO(content)

    # ── Étape 1 : soumission de la fiche labo ────────────────────────────────

    def test_e2e_ocr_and_predict_retourne_201(self, http, client_header):
        r = http.post(
            "/ingest/ocr-and-predict",
            data={"file": (self._fake_pdf(), "fiche_labo.pdf", "application/pdf")},
            content_type="multipart/form-data",
            headers=client_header,
        )
        assert r.status_code == 201, f"Réponse inattendue : {r.get_json()}"

    def test_e2e_prelevement_id_present(self, http, client_header):
        r = http.post(
            "/ingest/ocr-and-predict",
            data={"file": (self._fake_pdf(), "fiche_labo.pdf", "application/pdf")},
            content_type="multipart/form-data",
            headers=client_header,
        )
        d = r.get_json()
        assert "prelevement_id" in d, f"Clé 'prelevement_id' absente : {d}"

    def test_e2e_prediction_presente(self, http, client_header):
        r = http.post(
            "/ingest/ocr-and-predict",
            data={"file": (self._fake_pdf(), "fiche_labo.pdf", "application/pdf")},
            content_type="multipart/form-data",
            headers=client_header,
        )
        d = r.get_json()
        assert d.get("prediction_possible") is True, f"prediction_possible != True : {d}"
        pred = d.get("prediction")
        assert pred is not None, "Prédiction absente de la réponse"
        assert pred["potable"] in (0, 1)
        assert 0.0 <= pred["probability"] <= 1.0

    def test_e2e_prediction_label_coherent(self, http, client_header):
        r = http.post(
            "/ingest/ocr-and-predict",
            data={"file": (self._fake_pdf(), "fiche_labo.pdf", "application/pdf")},
            content_type="multipart/form-data",
            headers=client_header,
        )
        pred = r.get_json()["prediction"]
        expected_label = "Potable" if pred["potable"] == 1 else "Non potable"
        assert pred["label"] == expected_label

    # ── Étape 2 : vérification en base via GET /me/prelevements ──────────────

    def test_e2e_prelevement_recuperable(self, http, client_header):
        """Le prélèvement créé via OCR est visible dans la liste du client."""
        # Crée un prélèvement
        r_post = http.post(
            "/ingest/ocr-and-predict",
            data={"file": (self._fake_pdf(), "fiche_labo.pdf", "application/pdf")},
            content_type="multipart/form-data",
            headers=client_header,
        )
        assert r_post.status_code == 201
        prelevement_id = r_post.get_json()["prelevement_id"]

        # Récupère la liste
        r_list = http.get("/me/prelevements", headers=client_header)
        assert r_list.status_code == 200
        ids = [p["id"] for p in r_list.get_json()["items"]]
        assert prelevement_id in ids, (
            f"Prélèvement {prelevement_id} introuvable dans la liste : {ids}"
        )

    def test_e2e_detail_prelevement_source_ocr(self, http, client_header):
        """Le prélèvement créé via OCR a source='ocr'."""
        r_post = http.post(
            "/ingest/ocr-and-predict",
            data={"file": (self._fake_pdf(), "fiche_labo.pdf", "application/pdf")},
            content_type="multipart/form-data",
            headers=client_header,
        )
        prelevement_id = r_post.get_json()["prelevement_id"]

        r_detail = http.get(f"/me/prelevements/{prelevement_id}", headers=client_header)
        assert r_detail.status_code == 200
        detail = r_detail.get_json()
        assert detail["source"] == "ocr", f"Source attendue 'ocr', obtenu '{detail['source']}'"

    def test_e2e_mesures_extraites_correctement(self, http, client_header):
        """Les mesures extraites par l'OCR sont bien stockées."""
        r_post = http.post(
            "/ingest/ocr-and-predict",
            data={"file": (self._fake_pdf(), "fiche_labo.pdf", "application/pdf")},
            content_type="multipart/form-data",
            headers=client_header,
        )
        prelevement_id = r_post.get_json()["prelevement_id"]

        r_detail = http.get(f"/me/prelevements/{prelevement_id}", headers=client_header)
        mesures = r_detail.get_json().get("mesures", {})
        assert mesures.get("ph") == pytest.approx(7.6, abs=0.01)
        assert mesures.get("Turbidity") == pytest.approx(3.8, abs=0.01)

    # ── Étape 3 : cas dégradé (mesures partielles) ────────────────────────────

    def test_e2e_ocr_mesures_partielles_prediction_impossible(self, http, client_header):
        """Si l'OCR ne retourne pas toutes les mesures, prediction_possible=False."""
        ocr_partiel = {**MOCK_OCR_RESULT, "mesures": {"ph": 7.0}}  # mesures incomplètes
        with patch(
            "api.services.ocr_service.extract_from_document",
            return_value=ocr_partiel,
        ):
            r = http.post(
                "/ingest/ocr",
                data={"file": (self._fake_pdf(), "fiche_labo.pdf", "application/pdf")},
                content_type="multipart/form-data",
                headers=client_header,
            )
        assert r.status_code == 201
        d = r.get_json()
        assert d.get("prediction_possible") is False
        assert "prelevement_id" in d   # le prélèvement est quand même sauvegardé

    # ── Étape 4 : sécurité ───────────────────────────────────────────────────

    def test_e2e_sans_cle_retourne_401(self, http):
        r = http.post(
            "/ingest/ocr-and-predict",
            data={"file": (self._fake_pdf(), "fiche_labo.pdf", "application/pdf")},
            content_type="multipart/form-data",
        )
        assert r.status_code == 401

    def test_e2e_sans_fichier_retourne_400(self, http, client_header):
        r = http.post("/ingest/ocr-and-predict", headers=client_header)
        assert r.status_code == 400
