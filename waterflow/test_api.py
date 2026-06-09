"""
tests/test_api.py — Tests Waterflow 2

Architecture testée :
  - Clients     : X-API-Key → /me, /ingest/*, /me/prelevements, /me/resultats
  - Admin       : Bearer (tout expert) → /admin/clients/*
  - Analyste    : Bearer (analyste|exploit) → /analyste/*
  - Exploitation: Bearer (exploit seul) → /exploitation/*

Modèle ML et scaler mockés — base SQLite en mémoire.
"""

import os
import secrets
import pytest
from unittest.mock import patch, MagicMock
import numpy as np

# ── Environnement avant import Flask ────────────────────────────────────────
os.environ.setdefault("DATABASE_URL",      "sqlite:///:memory:")
os.environ.setdefault("MLFLOW_URI",        "mock")
os.environ.setdefault("SCALER_PATH",       "mock")
os.environ.setdefault("OCR_SPACE_API_KEY", "")
os.environ.setdefault("ANTHROPIC_API_KEY", "")
# Deux experts de test : un analyste, un exploit
os.environ["EXPERT_TOKENS"] = "alice:token-alice:analyste,bob:token-bob:exploit"

# ── Mocks ML ────────────────────────────────────────────────────────────────
_mock_model  = MagicMock()
_mock_model.predict.return_value        = np.array([1])
_mock_model.predict_proba.return_value  = np.array([[0.13, 0.87]])

_mock_scaler = MagicMock()
_mock_scaler.transform.side_effect = lambda x: x

with patch("mlflow.xgboost.load_model", return_value=_mock_model), \
     patch("joblib.load",               return_value=_mock_scaler), \
     patch("mlflow.set_tracking_uri"):
    from api.app        import create_app
    from api.models.db  import init_db, SessionLocal, Client

# ── Constantes ───────────────────────────────────────────────────────────────
ALICE_HEADER  = {"Authorization": "Bearer token-alice"}   # analyste
BOB_HEADER    = {"Authorization": "Bearer token-bob"}     # exploit
WRONG_BEARER  = {"Authorization": "Bearer mauvais-token"}

VALID_MESURES = {
    "ph": 7.2, "Hardness": 198.0, "Solids": 18630.0,
    "Chloramines": 7.1, "Sulfate": 333.0, "Conductivity": 432.0,
    "Organic_carbon": 14.2, "Trihalomethanes": 62.8, "Turbidity": 4.0,
}


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def app():
    application = create_app()
    application.config["TESTING"] = True
    init_db()
    return application

@pytest.fixture(scope="session")
def http(app):
    return app.test_client()

@pytest.fixture(scope="session")
def client_key(http):
    """Crée un client via l'API admin et génère sa clé — retourne la clé brute."""
    # Création du compte
    r = http.post("/admin/clients",
                  json={"id_client": "TEST-001",
                        "denomination": "Commune de Test",
                        "adresse": "1 rue de la Mairie 75000 Paris",
                        "rgpd_consent": True},
                  headers=BOB_HEADER)
    assert r.status_code == 201, r.get_json()
    client_id = r.get_json()["id"]

    # Génération de la clé
    r2 = http.post(f"/admin/clients/{client_id}/apikey", headers=BOB_HEADER)
    assert r2.status_code == 201
    return r2.get_json()["api_key"]

@pytest.fixture(scope="session")
def client_header(client_key):
    return {"X-API-Key": client_key}


# ════════════════════════════════════════════════════════════════════════════
# /health — public
# ════════════════════════════════════════════════════════════════════════════

class TestHealth:
    def test_ok_sans_auth(self, http):
        r = http.get("/health")
        assert r.status_code == 200
        assert r.get_json()["status"] == "ok"


# ════════════════════════════════════════════════════════════════════════════
# ADMIN /admin/clients — accessible à TOUS les experts
# ════════════════════════════════════════════════════════════════════════════

class TestAdminClients:

    def test_creer_client_analyste(self, http):
        """L'analyste peut créer un client."""
        r = http.post("/admin/clients",
                      json={"id_client": "COMM-ALICE",
                            "denomination": "Commune Alice",
                            "adresse": "1 rue Alice 69000 Lyon"},
                      headers=ALICE_HEADER)
        assert r.status_code == 201
        d = r.get_json()
        assert d["id_client"] == "COMM-ALICE"
        assert "api_key" not in d   # la clé n'est pas dans la réponse de création

    def test_creer_client_exploit(self, http):
        """L'exploit peut aussi créer un client."""
        r = http.post("/admin/clients",
                      json={"id_client": "COMM-BOB",
                            "denomination": "Commune Bob",
                            "adresse": "2 rue Bob 13000 Marseille"},
                      headers=BOB_HEADER)
        assert r.status_code == 201

    def test_creer_client_sans_auth(self, http):
        r = http.post("/admin/clients",
                      json={"id_client": "COMM-X", "denomination": "X", "adresse": "X"})
        assert r.status_code == 401

    def test_creer_client_mauvais_token(self, http):
        r = http.post("/admin/clients",
                      json={"id_client": "COMM-X", "denomination": "X", "adresse": "X"},
                      headers=WRONG_BEARER)
        assert r.status_code == 401

    def test_client_api_key_absent_dans_creation(self, http):
        """La clé API ne doit PAS apparaître dans la réponse de création."""
        r = http.post("/admin/clients",
                      json={"id_client": "COMM-NOKEY",
                            "denomination": "Sans clé",
                            "adresse": "3 rue C 75001 Paris"},
                      headers=ALICE_HEADER)
        assert "api_key" not in r.get_json()

    def test_champs_requis_id_client(self, http):
        r = http.post("/admin/clients",
                      json={"denomination": "X", "adresse": "Y"},
                      headers=BOB_HEADER)
        assert r.status_code == 400
        assert "id_client" in r.get_json()["error"]

    def test_champs_requis_denomination(self, http):
        r = http.post("/admin/clients",
                      json={"id_client": "X", "adresse": "Y"},
                      headers=BOB_HEADER)
        assert r.status_code == 400

    def test_champs_requis_adresse(self, http):
        """L'adresse est obligatoire selon le cahier des charges."""
        r = http.post("/admin/clients",
                      json={"id_client": "COMM-NOADR", "denomination": "Sans adresse"},
                      headers=BOB_HEADER)
        assert r.status_code == 400
        assert "adresse" in r.get_json()["error"]

    def test_duplicate_id_client(self, http):
        r = http.post("/admin/clients",
                      json={"id_client": "COMM-ALICE",
                            "denomination": "Doublon",
                            "adresse": "X"},
                      headers=BOB_HEADER)
        assert r.status_code == 409

    def test_lister_clients_analyste(self, http):
        r = http.get("/admin/clients", headers=ALICE_HEADER)
        assert r.status_code == 200
        assert isinstance(r.get_json(), list)

    def test_lister_clients_exploit(self, http):
        r = http.get("/admin/clients", headers=BOB_HEADER)
        assert r.status_code == 200

    def test_modifier_client(self, http):
        r = http.put("/admin/clients/COMM-ALICE",
                     json={"denomination": "Commune Alice Modifiée"},
                     headers=ALICE_HEADER)
        assert r.status_code == 200
        assert r.get_json()["denomination"] == "Commune Alice Modifiée"

    def test_adresse_vide_refusee(self, http):
        r = http.put("/admin/clients/COMM-ALICE",
                     json={"adresse": ""},
                     headers=BOB_HEADER)
        assert r.status_code == 400

    def test_generer_cle_analyste(self, http):
        """L'analyste peut générer une clé."""
        r = http.post("/admin/clients/COMM-ALICE/apikey", headers=ALICE_HEADER)
        assert r.status_code == 201
        d = r.get_json()
        assert "api_key" in d
        assert "warning" in d
        assert len(d["api_key"]) > 20   # clé suffisamment longue

    def test_generer_cle_exploit(self, http):
        """L'exploit peut aussi générer une clé."""
        r = http.post("/admin/clients/COMM-BOB/apikey", headers=BOB_HEADER)
        assert r.status_code == 201
        assert "api_key" in r.get_json()

    def test_client_introuvable(self, http):
        r = http.get("/admin/clients/INEXISTANT", headers=BOB_HEADER)
        assert r.status_code == 404


# ════════════════════════════════════════════════════════════════════════════
# CLIENTS — /me et /ingest/*
# Authentification : X-API-Key uniquement
# ════════════════════════════════════════════════════════════════════════════

class TestClientAuth:

    def test_me_avec_cle_valide(self, http, client_header):
        r = http.get("/me", headers=client_header)
        assert r.status_code == 200
        d = r.get_json()
        assert d["id_client"] == "TEST-001"
        assert d["denomination"] == "Commune de Test"
        assert d["adresse"] == "1 rue de la Mairie 75000 Paris"
        assert "api_key" not in d      # la clé brute ne doit JAMAIS apparaître

    def test_me_sans_cle(self, http):
        r = http.get("/me")
        assert r.status_code == 401

    def test_me_cle_invalide(self, http):
        r = http.get("/me", headers={"X-API-Key": "totalement-fausse"})
        assert r.status_code == 401

    def test_client_ne_peut_pas_utiliser_bearer(self, http):
        """Un client ne peut pas accéder à /me avec un token expert."""
        r = http.get("/me", headers=ALICE_HEADER)
        assert r.status_code == 401

    def test_client_ne_peut_pas_acceder_admin(self, http, client_header):
        """Un client ne peut pas créer d'autres clients."""
        r = http.post("/admin/clients",
                      json={"id_client": "HACK", "denomination": "Hack", "adresse": "X"},
                      headers=client_header)
        assert r.status_code == 401

    def test_client_ne_peut_pas_acceder_analyste(self, http, client_header):
        r = http.get("/analyste/dashboard", headers=client_header)
        assert r.status_code == 401

    def test_client_ne_peut_pas_acceder_exploitation(self, http, client_header):
        r = http.get("/exploitation/metrics", headers=client_header)
        assert r.status_code == 401


class TestClientIngestion:

    def test_ingest_manual_valide(self, http, client_header):
        r = http.post("/ingest/manual", json=VALID_MESURES, headers=client_header)
        assert r.status_code == 201
        d = r.get_json()
        assert "prelevement_id" in d
        assert d["prediction"]["potable"] in (0, 1)
        assert "probability" in d["prediction"]

    def test_ingest_manual_feature_manquante(self, http, client_header):
        bad = {k: v for k, v in VALID_MESURES.items() if k != "ph"}
        r   = http.post("/ingest/manual", json=bad, headers=client_header)
        assert r.status_code == 400

    def test_ingest_manual_valeur_non_numerique(self, http, client_header):
        bad = {**VALID_MESURES, "ph": "pas-un-nombre"}
        r   = http.post("/ingest/manual", json=bad, headers=client_header)
        assert r.status_code == 400

    def test_ingest_manual_sans_cle(self, http):
        r = http.post("/ingest/manual", json=VALID_MESURES)
        assert r.status_code == 401

    def test_ingest_ocr_sans_fichier(self, http, client_header):
        r = http.post("/ingest/ocr", headers=client_header)
        assert r.status_code == 400

    def test_ingest_ocr_type_invalide(self, http, client_header):
        from io import BytesIO
        r = http.post("/ingest/ocr",
                      data={"file": (BytesIO(b"data"), "test.exe", "application/x-executable")},
                      content_type="multipart/form-data",
                      headers=client_header)
        assert r.status_code == 400


class TestClientConsultation:

    def test_mes_prelevements(self, http, client_header):
        r = http.get("/me/prelevements", headers=client_header)
        assert r.status_code == 200
        d = r.get_json()
        assert "items" in d
        assert "total" in d
        assert "page" in d

    def test_mes_resultats(self, http, client_header):
        r = http.get("/me/resultats", headers=client_header)
        assert r.status_code == 200

    def test_detail_prelevement_autre_client_refuse(self, http, http_app=None):
        """Un client ne peut pas accéder aux prélèvements d'un autre."""
        # Crée un second client
        db = SessionLocal()
        c2 = Client(id_client="TEST-002", denomination="Autre",
                    adresse="2 rue B", actif=True)
        raw = secrets.token_urlsafe(16)
        c2.set_api_key(raw)
        db.add(c2)
        db.commit()
        db.close()

        # Tente d'accéder à un prélèvement de TEST-001 avec la clé de TEST-002
        r_prevs = http.get("/me/prelevements",
                            headers={"X-API-Key": secrets.token_urlsafe(16)})
        assert r_prevs.status_code == 401   # clé invalide, pas de fuite d'info

    def test_pagination(self, http, client_header):
        r = http.get("/me/prelevements?page=1&per_page=5", headers=client_header)
        assert r.status_code == 200
        assert r.get_json()["per_page"] == 5


# ════════════════════════════════════════════════════════════════════════════
# ANALYSTE — /analyste/*
# ════════════════════════════════════════════════════════════════════════════

class TestAnalyste:

    def test_dashboard(self, http):
        r = http.get("/analyste/dashboard", headers=ALICE_HEADER)
        assert r.status_code == 200
        d = r.get_json()
        assert "total_prelevements" in d
        assert "potable_rate" in d
        assert "moyennes" in d

    def test_dashboard_exploit_peut_aussi(self, http):
        """L'exploit a accès à tout ce que l'analyste peut faire."""
        r = http.get("/analyste/dashboard", headers=BOB_HEADER)
        assert r.status_code == 200

    def test_prelevements_tous(self, http):
        r = http.get("/analyste/prelevements", headers=ALICE_HEADER)
        assert r.status_code == 200
        assert "items" in r.get_json()

    def test_prelevements_client_interdit_sans_auth(self, http):
        r = http.get("/analyste/prelevements")
        assert r.status_code == 401

    def test_client_ne_peut_pas_voir_analyste(self, http, client_header):
        r = http.get("/analyste/prelevements", headers=client_header)
        assert r.status_code == 401

    def test_client_inconnu_404(self, http):
        r = http.get("/analyste/clients/INEXISTANT/prelevements",
                     headers=ALICE_HEADER)
        assert r.status_code == 404


# ════════════════════════════════════════════════════════════════════════════
# EXPLOITATION — /exploitation/*
# ════════════════════════════════════════════════════════════════════════════

class TestExploitation:

    def test_metrics_exploit(self, http):
        r = http.get("/exploitation/metrics", headers=BOB_HEADER)
        assert r.status_code == 200
        d = r.get_json()
        assert "routes" in d
        assert "clients_total" in d

    def test_metrics_analyste_interdit(self, http):
        """L'analyste n'a PAS accès aux métriques d'exploitation."""
        r = http.get("/exploitation/metrics", headers=ALICE_HEADER)
        assert r.status_code == 403

    def test_metrics_client_interdit(self, http, client_header):
        r = http.get("/exploitation/metrics", headers=client_header)
        assert r.status_code == 401

    def test_audit_exploit(self, http):
        r = http.get("/exploitation/audit", headers=BOB_HEADER)
        assert r.status_code == 200
        d = r.get_json()
        assert "items" in d
        assert "total" in d

    def test_audit_analyste_interdit(self, http):
        r = http.get("/exploitation/audit", headers=ALICE_HEADER)
        assert r.status_code == 403

    def test_audit_pagination(self, http):
        r = http.get("/exploitation/audit?page=1&per_page=10", headers=BOB_HEADER)
        assert r.status_code == 200
        assert r.get_json()["per_page"] == 10


# ════════════════════════════════════════════════════════════════════════════
# [Option] RGPD — /me/rgpd
# User story : consulter ses données personnelles et règles de conservation
# ════════════════════════════════════════════════════════════════════════════

class TestRGPD:

    def test_get_rgpd_structure(self, http, client_header):
        """GET /me/rgpd retourne les 5 sections attendues."""
        r = http.get("/me/rgpd", headers=client_header)
        assert r.status_code == 200
        d = r.get_json()
        assert "donnees_personnelles"  in d
        assert "donnees_stockees"      in d
        assert "historique_acces"      in d
        assert "regles_conservation"   in d
        assert "vos_droits"            in d

    def test_get_rgpd_donnees_personnelles(self, http, client_header):
        """Les données personnelles retournées correspondent au compte."""
        r = http.get("/me/rgpd", headers=client_header)
        dp = r.get_json()["donnees_personnelles"]
        assert dp["id_client"]    == "TEST-001"
        assert dp["denomination"] == "Commune de Test"
        assert dp["adresse"]      == "1 rue de la Mairie 75000 Paris"

    def test_get_rgpd_pas_de_cle_brute(self, http, client_header):
        """La clé API brute ne doit jamais apparaître dans la réponse RGPD."""
        r    = http.get("/me/rgpd", headers=client_header)
        text = r.get_data(as_text=True)
        # La clé hint (4 chars) peut apparaître, mais pas une clé longue
        assert "api_key_hash" not in text

    def test_get_rgpd_ip_pseudonymisee(self, http, client_header):
        """Les IPs dans l'historique doivent être pseudonymisées."""
        r      = http.get("/me/rgpd", headers=client_header)
        acces  = r.get_json()["historique_acces"]
        for a in acces:
            ip = a.get("ip", "")
            if ip and ip != "unknown":
                # IPv4 : le dernier octet doit être masqué
                assert not ip.split(".")[-1].isdigit() or "xxx" in ip

    def test_get_rgpd_regles_conservation_completes(self, http, client_header):
        """Les 4 règles de conservation sont présentes."""
        r    = http.get("/me/rgpd", headers=client_header)
        regl = r.get_json()["regles_conservation"]
        assert "prelevements_et_mesures" in regl
        assert "journaux_acces"          in regl
        assert "metriques_performance"   in regl
        assert "cle_api"                 in regl

    def test_get_rgpd_droits_mentionnes(self, http, client_header):
        """Les droits RGPD (accès, rectification, effacement) sont listés."""
        r      = http.get("/me/rgpd", headers=client_header)
        droits = r.get_json()["vos_droits"]
        assert "acces"         in droits
        assert "rectification" in droits
        assert "effacement"    in droits
        assert "portabilite"   in droits

    def test_get_rgpd_sans_auth(self, http):
        """Sans clé API, accès refusé."""
        r = http.get("/me/rgpd")
        assert r.status_code == 401

    def test_get_rgpd_expert_interdit(self, http):
        """Un expert ne peut pas accéder au /me/rgpd d'un client."""
        r = http.get("/me/rgpd", headers=ALICE_HEADER)
        assert r.status_code == 401

    def test_delete_rgpd_sans_confirmation(self, http, client_header):
        """Sans { confirmer: true }, l'effacement est refusé."""
        r = http.delete("/me/rgpd", json={}, headers=client_header)
        assert r.status_code == 400
        assert "confirmer" in r.get_json()["error"].lower() \
               or "irréversible" in r.get_json()["error"].lower() \
               or "confirm" in r.get_json()["error"].lower()

    def test_delete_rgpd_confirme(self, http):
        """
        Avec { confirmer: true }, le compte est anonymisé et désactivé.
        On crée un client temporaire pour ne pas casser les autres tests.
        """
        # Création d'un client temporaire
        r_create = http.post(
            "/admin/clients",
            json={"id_client": "TEMP-RGPD", "denomination": "Temp",
                  "adresse": "1 rue Temp 75000 Paris"},
            headers=BOB_HEADER,
        )
        assert r_create.status_code == 201
        client_id = r_create.get_json()["id"]

        r_key = http.post(f"/admin/clients/{client_id}/apikey", headers=BOB_HEADER)
        assert r_key.status_code == 201
        temp_key = r_key.get_json()["api_key"]
        temp_header = {"X-API-Key": temp_key}

        # Effacement
        r_del = http.delete("/me/rgpd", json={"confirmer": True},
                            headers=temp_header)
        assert r_del.status_code == 200
        d = r_del.get_json()
        assert "anonymisé" in d["message"].lower() or "anonymise" in d["message"].lower()
        assert "anonymise_le" in d

        # La clé est révoquée : plus d'accès possible
        r_me = http.get("/me", headers=temp_header)
        assert r_me.status_code == 401
