"""
api/routes/routes.py — Routes Waterflow 2

Deux mondes d'authentification, périmètres strictement séparés :

━━━━ CLIENTS (clé API — header X-API-Key) ━━━━━━━━━━━━━━━━━━━
  GET  /me                       Profil du client authentifié
  GET  /me/prelevements          Mes prélèvements (paginés)
  GET  /me/prelevements/<id>     Détail d'un prélèvement
  GET  /me/resultats             Mes résultats de prédiction

  POST /ingest/manual            Déposer mesures JSON + prédiction
  POST /ingest/ocr               Déposer fiche PDF/image (OCR seul)
  POST /ingest/ocr-and-predict   OCR + prédiction pipeline complet

━━━━ ADMIN (token Bearer — tout expert) ━━━━━━━━━━━━━━━━━━━━━
  Gestion des comptes clients (analyste ET exploit) :
  GET  /admin/clients                    Lister tous les comptes
  POST /admin/clients                    Créer un compte client
  GET  /admin/clients/<id>               Détail d'un compte
  PUT  /admin/clients/<id>               Modifier denomination/adresse/actif
  POST /admin/clients/<id>/apikey        Générer ou régénérer la clé API

━━━━ ANALYSTE (token Bearer — rôle analyste ou exploit) ━━━━━
  GET  /analyste/prelevements            Tous les prélèvements
  GET  /analyste/prelevements/<id>       Détail complet (+ OCR brut)
  GET  /analyste/clients/<id>/prelevements  Prélèvements d'un client
  GET  /analyste/dashboard               KPIs qualité agrégés

━━━━ EXPLOITATION (token Bearer — rôle exploit uniquement) ━━
  GET  /exploitation/metrics             Volumes, temps de réponse, erreurs
  GET  /exploitation/audit               Journal d'accès RGPD paginé

━━━━ PUBLIC ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  GET  /health
"""

import json
import secrets
import logging
from datetime import datetime

from flask import Blueprint, request, jsonify, g
from sqlalchemy import func

from api.models.db import (
    Client, Prelevement, Mesure, Prediction,
    AuditLog, RequestMetric, IngestionSource, get_db, utcnow,
)
from api.middleware.auth import (
    require_client_key, require_expert, timed, log_audit,
)
from api.services.ocr_service     import extract_from_document, ACCEPTED_MIME
from api.services.predict_service import run_prediction, MLFLOW_MODEL_URI

logger           = logging.getLogger(__name__)
bp               = Blueprint("api", __name__)
MAX_UPLOAD_BYTES = 20 * 1024 * 1024   # 20 Mo


# ════════════════════════════════════════════════════════════════════════════
# UTILITAIRES INTERNES
# ════════════════════════════════════════════════════════════════════════════

def _read_upload():
    if "file" not in request.files:
        raise ValueError("Champ 'file' manquant (multipart/form-data).")
    upload = request.files["file"]
    mime   = (upload.content_type or "").lower().split(";")[0].strip()
    if mime not in ACCEPTED_MIME:
        raise ValueError(
            f"Type non supporté : '{mime}'. "
            f"Acceptés : {', '.join(sorted(ACCEPTED_MIME))}."
        )
    data = upload.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("Fichier trop volumineux (max 20 Mo).")
    return data, mime, upload.filename or "document"


def _save_prelevement(db, client: Client, mesures_dict: dict,
                      source: IngestionSource,
                      ocr_data: dict | None = None,
                      filename: str | None = None,
                      mime: str | None = None) -> Prelevement:
    """Persiste Prelevement + Mesure en une transaction."""
    date_obj = None
    if ocr_data and ocr_data.get("date_prelevement"):
        try:
            date_obj = datetime.fromisoformat(ocr_data["date_prelevement"])
        except ValueError:
            pass

    prev = Prelevement(
        client_id        = client.id,
        date_prelevement = date_obj,
        lieu             = (ocr_data or {}).get("lieu"),
        source           = source,
        fichier_nom      = filename,
        fichier_type     = mime,
        ocr_raw_text     = (ocr_data or {}).get("raw_text"),
        ocr_warnings     = json.dumps((ocr_data or {}).get("warnings", []),
                                      ensure_ascii=False),
        observations     = (ocr_data or {}).get("observations"),
    )
    db.add(prev)
    db.flush()

    m = mesures_dict
    db.add(Mesure(
        prelevement_id  = prev.id,
        ph              = m.get("ph"),
        hardness        = m.get("Hardness"),
        solids          = m.get("Solids"),
        chloramines     = m.get("Chloramines"),
        sulfate         = m.get("Sulfate"),
        conductivity    = m.get("Conductivity"),
        organic_carbon  = m.get("Organic_carbon"),
        trihalomethanes = m.get("Trihalomethanes"),
        turbidity       = m.get("Turbidity"),
    ))
    db.commit()
    db.refresh(prev)
    return prev


def _save_prediction(db, prev: Prelevement, result: dict) -> Prediction:
    pred = Prediction(
        prelevement_id = prev.id,
        potable        = result["potable"],
        probability    = result["probability"],
        model_version  = result.get("model_version"),
    )
    db.add(pred)
    db.commit()
    return pred


def _client_dict(c: Client, detail: bool = False) -> dict:
    """Sérialise un client. detail=True ajoute les champs exploitation."""
    out = {
        "id":              c.id,
        "id_client":       c.id_client,
        "denomination":    c.denomination,
        "adresse":         c.adresse,
        "actif":           c.actif,
        "api_key_hint":    c.api_key_hint,
        "key_generated_at": c.key_generated_at.isoformat()
                            if c.key_generated_at else None,
        "created_at":      c.created_at.isoformat() if c.created_at else None,
        "nb_prelevements": len(c.prelevements),
    }
    if detail:
        out["created_by"]   = c.created_by
        out["rgpd_consent"] = c.rgpd_consent
    return out


def _prev_dict(p: Prelevement, include_ocr: bool = False) -> dict:
    """Sérialise un prélèvement."""
    m    = p.mesures
    pred = p.predictions[-1] if p.predictions else None
    out  = {
        "id":               p.id,
        "client_id":        p.client.id_client if p.client else None,
        "date_prelevement": p.date_prelevement.isoformat()
                            if p.date_prelevement else None,
        "lieu":             p.lieu,
        "source":           p.source.value if p.source else None,
        "observations":     p.observations,
        "created_at":       p.created_at.isoformat() if p.created_at else None,
        "warnings":         json.loads(p.ocr_warnings) if p.ocr_warnings else [],
        "mesures":          m.to_feature_dict() if m else {},
        "prediction": {
            "potable":     pred.potable,
            "label":       "Potable" if pred.potable == 1 else "Non potable",
            "probability": pred.probability,
            "model":       pred.model_version,
            "at":          pred.created_at.isoformat(),
        } if pred else None,
    }
    if include_ocr and p.ocr_raw_text:
        out["ocr_raw_text"] = p.ocr_raw_text
    return out


def _paginate(query, page: int, per_page: int) -> dict:
    total = query.count()
    items = query.offset((page - 1) * per_page).limit(per_page).all()
    return {
        "total":    total,
        "page":     page,
        "per_page": per_page,
        "pages":    max(1, -(-total // per_page)),
        "items":    items,
    }


def _page_params() -> tuple[int, int]:
    page     = max(1, int(request.args.get("page", 1)))
    per_page = min(100, max(1, int(request.args.get("per_page", 20))))
    return page, per_page


# ════════════════════════════════════════════════════════════════════════════
# PUBLIC
# ════════════════════════════════════════════════════════════════════════════

@bp.route("/", methods=["GET"])
def index():
    from flask import render_template
    return render_template("index.html")


@bp.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "model":  MLFLOW_MODEL_URI,
        "ts":     utcnow().isoformat(),
    })


# ════════════════════════════════════════════════════════════════════════════
# CLIENTS — consultation de leurs propres données
# Authentification : X-API-Key
# ════════════════════════════════════════════════════════════════════════════

@bp.route("/me", methods=["GET"])
@require_client_key
def me():
    """Profil du client authentifié (sans la clé brute, jamais)."""
    c = g.client
    return jsonify({
        "id_client":       c.id_client,
        "denomination":    c.denomination,
        "adresse":         c.adresse,
        "actif":           c.actif,
        "api_key_hint":    c.api_key_hint,
        "key_generated_at": c.key_generated_at.isoformat()
                            if c.key_generated_at else None,
    })


@bp.route("/me/rgpd", methods=["GET"])
@require_client_key
def me_rgpd():
    """
    [Option RGPD] Données personnelles associées au compte du client.

    Retourne :
      - les données personnelles stockées (ID, dénomination, adresse)
      - l'historique des 50 derniers accès à ce compte (audit_log)
      - les règles de conservation appliquées par la plateforme
      - les droits disponibles (rectification, effacement)

    Conformité RGPD art. 13-15 : droit d'accès et d'information.
    """
    c  = g.client
    db = g.db

    # 50 derniers accès de ce client (par id_client dans actor_id)
    acces = (
        db.query(AuditLog)
          .filter(AuditLog.actor_id == c.id_client,
                  AuditLog.actor_type == "client")
          .order_by(AuditLog.timestamp.desc())
          .limit(50)
          .all()
    )

    log_audit("client_rgpd_acces", status_code=200)
    return jsonify({
        "donnees_personnelles": {
            "id_client":    c.id_client,
            "denomination": c.denomination,
            "adresse":      c.adresse,
            "compte_cree_le": c.created_at.isoformat() if c.created_at else None,
            "cle_api_generee_le": c.key_generated_at.isoformat()
                                  if c.key_generated_at else None,
            "consentement_rgpd":    c.rgpd_consent,
            "consentement_donne_le": c.rgpd_consent_at.isoformat()
                                     if c.rgpd_consent_at else None,
        },
        "donnees_stockees": {
            "prelevements": db.query(Prelevement)
                              .filter(Prelevement.client_id == c.id)
                              .count(),
            "predictions":  db.query(Prediction)
                              .join(Prelevement)
                              .filter(Prelevement.client_id == c.id)
                              .count(),
            "note": (
                "Les mesures physico-chimiques sont associées à votre ID client. "
                "Aucune donnée biométrique ou de santé directement identifiante n'est stockée."
            ),
        },
        "historique_acces": [
            {
                "date":   a.timestamp.isoformat(),
                "action": a.action,
                "ip":     a.ip_address,   # déjà pseudonymisée /24
                "statut": a.status_code,
            }
            for a in acces
        ],
        "regles_conservation": {
            "prelevements_et_mesures": "Conservés sans limitation de durée tant que le compte est actif.",
            "journaux_acces":          "Conservés 12 mois glissants, puis purgés automatiquement.",
            "metriques_performance":   "Agrégées et anonymisées après 90 jours.",
            "cle_api":                 "Jamais stockée en clair. Seul un hash SHA-256 est conservé.",
        },
        "vos_droits": {
            "acces":       "Exercé via ce endpoint GET /me/rgpd.",
            "rectification": "Contactez un administrateur pour modifier dénomination ou adresse.",
            "effacement":  "Envoyez DELETE /me/rgpd pour anonymiser votre compte (irréversible).",
            "portabilite": "Vos prélèvements sont accessibles via GET /me/prelevements.",
            "contact_dpo": "dpo@waterflow.example.com",
        },
    })


@bp.route("/me/rgpd", methods=["DELETE"])
@require_client_key
def me_rgpd_effacement():
    """
    [Option RGPD] Droit à l'effacement (art. 17 RGPD).

    Anonymise le compte : denomination et adresse sont écrasés,
    la clé API est révoquée, le compte est désactivé.
    Les prélèvements et mesures sont conservés sous forme anonymisée
    (association au compte coupée par pseudonyme générique).

    ⚠ Action irréversible — confirmez avec { "confirmer": true } dans le corps.
    """
    data = request.get_json(force=True) or {}
    if not data.get("confirmer"):
        return jsonify({
            "error": (
                "Action irréversible. "
                "Renvoyez la requête avec { \"confirmer\": true } pour confirmer."
            )
        }), 400

    db = g.db
    c  = g.client

    # Anonymisation : on écrase les données personnelles
    c.denomination  = f"[ANONYMISÉ-{c.id_client}]"
    c.adresse       = "[ANONYMISÉ]"
    c.api_key_hash  = None
    c.api_key_hint  = None
    c.actif         = False
    c.anonymised_at = utcnow()

    db.commit()

    log_audit("client_rgpd_effacement", status_code=200,
              detail="Compte anonymisé à la demande du client.")
    return jsonify({
        "message": (
            "Votre compte a été anonymisé. "
            "Vos données personnelles (dénomination, adresse) ont été supprimées. "
            "Vos prélèvements sont conservés sous forme anonymisée conformément "
            "à nos obligations légales de traçabilité."
        ),
        "anonymise_le": c.anonymised_at.isoformat(),
    })


@bp.route("/me/prelevements", methods=["GET"])
@require_client_key
@timed
def me_prelevements():
    """
    Prélèvements du client authentifié — paginés.
    Filtres optionnels : date_from, date_to
    """
    db         = g.db
    page, ppp  = _page_params()
    q = (db.query(Prelevement)
           .filter(Prelevement.client_id == g.client.id)
           .order_by(Prelevement.created_at.desc()))

    for param, col in (("date_from", "__ge__"), ("date_to", "__le__")):
        if request.args.get(param):
            try:
                dt = datetime.fromisoformat(request.args[param])
                q  = q.filter(getattr(Prelevement.date_prelevement, col)(dt))
            except ValueError:
                pass

    paged = _paginate(q, page, ppp)
    log_audit("client_read_prelevements", status_code=200)
    return jsonify({**paged, "items": [_prev_dict(p) for p in paged["items"]]})


@bp.route("/me/prelevements/<string:prev_id>", methods=["GET"])
@require_client_key
@timed
def me_prelevement_detail(prev_id: str):
    """Détail d'un prélèvement — vérifie l'appartenance au client."""
    p = g.db.query(Prelevement).filter(Prelevement.id == prev_id).first()
    if not p:
        return jsonify({"error": "Prélèvement introuvable."}), 404
    if p.client_id != g.client.id:
        return jsonify({"error": "Accès refusé."}), 403
    log_audit("client_read_prelevement", resource_id=prev_id)
    return jsonify(_prev_dict(p, include_ocr=True))


@bp.route("/me/resultats", methods=["GET"])
@require_client_key
@timed
def me_resultats():
    """
    Résultats d'analyse du modèle pour le client authentifié.
    Retourne uniquement les prélèvements ayant une prédiction.
    """
    db        = g.db
    page, ppp = _page_params()
    q = (db.query(Prelevement)
           .join(Prediction)
           .filter(Prelevement.client_id == g.client.id)
           .order_by(Prelevement.created_at.desc()))

    paged = _paginate(q, page, ppp)
    log_audit("client_read_resultats", status_code=200)
    return jsonify({**paged, "items": [_prev_dict(p) for p in paged["items"]]})


# ════════════════════════════════════════════════════════════════════════════
# CLIENTS — ingestion de prélèvements
# ════════════════════════════════════════════════════════════════════════════

@bp.route("/ingest/manual", methods=["POST"])
@require_client_key
@timed
def ingest_manual():
    """
    Dépôt de mesures JSON + prédiction immédiate.

    Corps JSON :
      { "ph": 7.2, "Hardness": 198.0, "Solids": 18630.0,
        "Chloramines": 7.1, "Sulfate": 333.0, "Conductivity": 432.0,
        "Organic_carbon": 14.2, "Trihalomethanes": 62.8, "Turbidity": 4.0 }
    """
    data = request.get_json(force=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Corps JSON attendu."}), 400

    try:
        result = run_prediction(data)
    except ValueError as e:
        log_audit("client_ingest_manual", status_code=400, detail=str(e))
        return jsonify({"error": str(e)}), 400

    db   = g.db
    prev = _save_prelevement(db, g.client, data, IngestionSource.MANUAL)
    _save_prediction(db, prev, result)

    log_audit("client_ingest_manual", resource_id=prev.id, status_code=201)
    return jsonify({
        "prelevement_id": prev.id,
        "prediction": {
            "potable":     result["potable"],
            "label":       result["label"],
            "probability": result["probability"],
        },
    }), 201


@bp.route("/ingest/ocr", methods=["POST"])
@require_client_key
@timed
def ingest_ocr():
    """
    Dépose une fiche PDF/image → extraction OCR → stockage.
    Pas de prédiction automatique : certains champs peuvent manquer.
    Appelez ensuite /ingest/ocr-and-predict pour le pipeline complet.

    Requête : multipart/form-data, champ 'file'
    """
    try:
        file_bytes, mime, filename = _read_upload()
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    try:
        extracted = extract_from_document(file_bytes, mime)
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 503
    except Exception as e:
        logger.exception("Erreur OCR")
        return jsonify({"error": f"Erreur extraction : {e}"}), 500

    db   = g.db
    prev = _save_prelevement(
        db, g.client, extracted.get("mesures", {}),
        IngestionSource.OCR, ocr_data=extracted,
        filename=filename, mime=mime,
    )
    log_audit("client_ingest_ocr", resource_id=prev.id, status_code=201)
    return jsonify({
        "prelevement_id": prev.id,
        "ocr":            extracted,
    }), 201


@bp.route("/ingest/ocr-and-predict", methods=["POST"])
@require_client_key
@timed
def ingest_ocr_and_predict():
    """
    Pipeline complet : OCR → stockage → prédiction.
    Si des mesures manquent, le prélèvement est quand même stocké
    et prediction_possible=false est retourné avec le détail des champs manquants.

    Requête : multipart/form-data, champ 'file'
    """
    try:
        file_bytes, mime, filename = _read_upload()
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    try:
        extracted = extract_from_document(file_bytes, mime)
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 503
    except Exception as e:
        logger.exception("Erreur OCR")
        return jsonify({"error": f"Erreur extraction : {e}"}), 500

    db   = g.db
    prev = _save_prelevement(
        db, g.client, extracted.get("mesures", {}),
        IngestionSource.OCR, ocr_data=extracted,
        filename=filename, mime=mime,
    )

    prediction          = None
    prediction_possible = False
    prediction_error    = None

    try:
        result              = run_prediction(extracted.get("mesures", {}))
        _save_prediction(db, prev, result)
        prediction          = {
            "potable":     result["potable"],
            "label":       result["label"],
            "probability": result["probability"],
        }
        prediction_possible = True
    except ValueError as e:
        prediction_error = str(e)
        db.rollback()

    log_audit("client_ingest_ocr_predict", resource_id=prev.id, status_code=201)
    return jsonify({
        "prelevement_id":      prev.id,
        "ocr":                 extracted,
        "prediction":          prediction,
        "prediction_possible": prediction_possible,
        "prediction_error":    prediction_error,
    }), 201


# ════════════════════════════════════════════════════════════════════════════
# ADMIN — gestion des comptes clients
# Accessible à TOUS les experts (analyste ET exploit)
# Authentification : Authorization: Bearer <token>
# ════════════════════════════════════════════════════════════════════════════

@bp.route("/admin/clients", methods=["GET"])
@require_expert()
def admin_list_clients():
    """
    Liste tous les comptes clients.
    Accessible à l'analyste qualité ET au responsable d'exploitation.
    """
    db      = g.db
    clients = db.query(Client).order_by(Client.created_at.desc()).all()
    detail  = (g.expert_role == "exploit")   # exploit voit les champs sensibles
    log_audit("admin_list_clients")
    return jsonify([_client_dict(c, detail=detail) for c in clients])


@bp.route("/admin/clients", methods=["POST"])
@require_expert()
def admin_create_client():
    """
    Crée un compte client.
    Accessible à l'analyste qualité ET au responsable d'exploitation.

    Corps JSON requis :
      {
        "id_client":    "COMM-042",
        "denomination": "Commune de Marseille",
        "adresse":      "1 place de la Mairie 13000 Marseille"
      }

    La clé API est générée séparément via POST /admin/clients/<id>/apikey.
    """
    data    = request.get_json(force=True) or {}
    missing = [f for f in ("id_client", "denomination", "adresse")
               if not str(data.get(f, "")).strip()]
    if missing:
        return jsonify({"error": f"Champs requis manquants : {missing}"}), 400

    db = g.db
    if db.query(Client).filter(Client.id_client == data["id_client"].strip()).first():
        return jsonify({"error": f"id_client déjà existant : {data['id_client']}"}), 409

    client = Client(
        id_client    = data["id_client"].strip(),
        denomination = data["denomination"].strip(),
        adresse      = data["adresse"].strip(),
        created_by   = g.expert_login,
        rgpd_consent    = bool(data.get("rgpd_consent", False)),
        rgpd_consent_at = utcnow() if data.get("rgpd_consent") else None,
    )
    db.add(client)
    db.commit()
    db.refresh(client)

    log_audit("admin_create_client", resource_id=client.id, status_code=201)
    return jsonify({
        **_client_dict(client, detail=True),
        "next_step": f"Générez la clé API via : POST /admin/clients/{client.id}/apikey",
    }), 201


@bp.route("/admin/clients/<string:client_id>", methods=["GET"])
@require_expert()
def admin_get_client(client_id: str):
    """
    Détail d'un compte client (par UUID interne ou id_client métier).
    """
    db     = g.db
    client = (db.query(Client)
                .filter((Client.id == client_id) | (Client.id_client == client_id))
                .first())
    if not client:
        return jsonify({"error": "Client introuvable."}), 404
    log_audit("admin_get_client", resource_id=client.id)
    return jsonify(_client_dict(client, detail=True))


@bp.route("/admin/clients/<string:client_id>", methods=["PUT"])
@require_expert()
def admin_update_client(client_id: str):
    """
    Modifie denomination, adresse ou statut actif.
    Accessible à l'analyste ET à l'exploit.
    L'id_client métier est immuable une fois créé.
    """
    db     = g.db
    client = (db.query(Client)
                .filter((Client.id == client_id) | (Client.id_client == client_id))
                .first())
    if not client:
        return jsonify({"error": "Client introuvable."}), 404

    data = request.get_json(force=True) or {}

    if "denomination" in data:
        val = str(data["denomination"]).strip()
        if not val:
            return jsonify({"error": "denomination ne peut pas être vide."}), 400
        client.denomination = val

    if "adresse" in data:
        val = str(data["adresse"]).strip()
        if not val:
            return jsonify({"error": "adresse ne peut pas être vide."}), 400
        client.adresse = val

    if "actif" in data:
        client.actif = bool(data["actif"])

    db.commit()
    log_audit("admin_update_client", resource_id=client.id)
    return jsonify(_client_dict(client, detail=True))


@bp.route("/admin/clients/<string:client_id>/apikey", methods=["POST"])
@require_expert()
def admin_generate_apikey(client_id: str):
    """
    Génère ou régénère la clé API d'un client.
    Accessible à l'analyste ET au responsable d'exploitation.

    ⚠ La clé brute n'est retournée QU'UNE SEULE FOIS et n'est
      jamais stockée en clair. L'ancienne clé est immédiatement révoquée.
    """
    db     = g.db
    client = (db.query(Client)
                .filter((Client.id == client_id) | (Client.id_client == client_id))
                .first())
    if not client:
        return jsonify({"error": "Client introuvable."}), 404
    if not client.actif:
        return jsonify({
            "error": "Client désactivé. Réactivez-le d'abord via PUT /admin/clients/<id>."
        }), 409

    raw_key = secrets.token_urlsafe(32)   # 256 bits d'entropie
    client.set_api_key(raw_key)
    db.commit()

    log_audit("admin_generate_apikey", resource_id=client.id, status_code=201)
    return jsonify({
        "id_client":    client.id_client,
        "denomination": client.denomination,
        "api_key":      raw_key,
        "key_hint":     client.api_key_hint,
        "generated_at": client.key_generated_at.isoformat(),
        "generated_by": g.expert_login,
        "warning": (
            "⚠ Transmettez immédiatement cette clé au client par canal sécurisé. "
            "Elle ne pourra plus être consultée après cette réponse."
        ),
    }), 201


# ════════════════════════════════════════════════════════════════════════════
# ANALYSTE QUALITÉ
# Accède à tous les prélèvements, dashboards, prédictions, données enrichies.
# Authentification : Authorization: Bearer <token> (rôle analyste ou exploit)
# ════════════════════════════════════════════════════════════════════════════

@bp.route("/analyste/prelevements", methods=["GET"])
@require_expert(role="analyste")
@timed
def analyste_prelevements():
    """
    Tous les prélèvements — paginés, filtrables.
    Filtres : client_id (id_client métier), source, date_from, date_to
    """
    db        = g.db
    page, ppp = _page_params()
    q = db.query(Prelevement).order_by(Prelevement.created_at.desc())

    if request.args.get("client_id"):
        c = db.query(Client).filter(
            Client.id_client == request.args["client_id"]
        ).first()
        if c:
            q = q.filter(Prelevement.client_id == c.id)

    if request.args.get("source"):
        q = q.filter(Prelevement.source == request.args["source"])

    for param, op in (("date_from", "__ge__"), ("date_to", "__le__")):
        if request.args.get(param):
            try:
                dt = datetime.fromisoformat(request.args[param])
                q  = q.filter(getattr(Prelevement.date_prelevement, op)(dt))
            except ValueError:
                pass

    paged = _paginate(q, page, ppp)
    log_audit("analyste_read_prelevements", status_code=200)
    return jsonify({**paged,
                    "items": [_prev_dict(p, include_ocr=True) for p in paged["items"]]})


@bp.route("/analyste/prelevements/<string:prev_id>", methods=["GET"])
@require_expert(role="analyste")
@timed
def analyste_prelevement_detail(prev_id: str):
    """Détail complet d'un prélèvement, incluant le texte OCR brut."""
    p = g.db.query(Prelevement).filter(Prelevement.id == prev_id).first()
    if not p:
        return jsonify({"error": "Prélèvement introuvable."}), 404
    log_audit("analyste_read_prelevement", resource_id=prev_id)
    return jsonify(_prev_dict(p, include_ocr=True))


@bp.route("/analyste/clients/<string:client_id>/prelevements", methods=["GET"])
@require_expert(role="analyste")
@timed
def analyste_client_prelevements(client_id: str):
    """Prélèvements d'un client spécifique (filtrés par id_client métier)."""
    db     = g.db
    client = db.query(Client).filter(Client.id_client == client_id).first()
    if not client:
        return jsonify({"error": f"Client '{client_id}' introuvable."}), 404

    page, ppp = _page_params()
    q     = (db.query(Prelevement)
               .filter(Prelevement.client_id == client.id)
               .order_by(Prelevement.created_at.desc()))
    paged = _paginate(q, page, ppp)
    return jsonify({**paged, "items": [_prev_dict(p) for p in paged["items"]]})


@bp.route("/analyste/dashboard", methods=["GET"])
@require_expert(role="analyste")
@timed
def analyste_dashboard():
    """
    KPIs qualité agrégés :
    - taux de potabilité global
    - moyennes des mesures physico-chimiques
    - distribution par source d'ingestion
    - 15 derniers prélèvements
    """
    db = g.db

    total_prevs   = db.query(Prelevement).count()
    total_preds   = db.query(Prediction).count()
    potable_count = db.query(Prediction).filter(Prediction.potable == 1).count()

    avgs = db.query(
        func.avg(Mesure.ph),
        func.avg(Mesure.turbidity),
        func.avg(Mesure.conductivity),
        func.avg(Mesure.chloramines),
        func.avg(Mesure.hardness),
    ).one()

    sources = dict(
        db.query(Prelevement.source, func.count(Prelevement.id))
          .group_by(Prelevement.source).all()
    )

    recents = (db.query(Prelevement)
                 .order_by(Prelevement.created_at.desc())
                 .limit(15).all())

    log_audit("analyste_read_dashboard")
    return jsonify({
        "total_prelevements":  total_prevs,
        "total_predictions":   total_preds,
        "potable_count":       potable_count,
        "non_potable_count":   total_preds - potable_count,
        "potable_rate":        round(potable_count / total_preds, 4)
                               if total_preds else None,
        "clients_actifs":      db.query(Client).filter(Client.actif == True).count(),
        "sources": {
            (k.value if hasattr(k, "value") else str(k)): v
            for k, v in sources.items()
        },
        "moyennes": {
            "ph":          round(avgs[0], 3) if avgs[0] else None,
            "turbidity":   round(avgs[1], 3) if avgs[1] else None,
            "conductivity":round(avgs[2], 3) if avgs[2] else None,
            "chloramines": round(avgs[3], 3) if avgs[3] else None,
            "hardness":    round(avgs[4], 3) if avgs[4] else None,
        },
        "recents": [_prev_dict(p) for p in recents],
    })


# ════════════════════════════════════════════════════════════════════════════
# RESPONSABLE D'EXPLOITATION
# Supervision santé plateforme, journaux d'accès.
# Authentification : Authorization: Bearer <token> (rôle exploit uniquement)
# ════════════════════════════════════════════════════════════════════════════

@bp.route("/exploitation/metrics", methods=["GET"])
@require_expert(role="exploit")
@timed
def exploitation_metrics():
    """
    Indicateurs de santé de la plateforme :
    - volume de requêtes par route
    - temps de réponse (p50, p95, moyenne)
    - taux d'erreur
    Paramètre optionnel : ?limit=N (défaut : 5000 dernières requêtes)
    """
    db    = g.db
    limit = min(50000, max(100, int(request.args.get("limit", 5000))))
    rows  = (db.query(RequestMetric)
               .order_by(RequestMetric.timestamp.desc())
               .limit(limit).all())

    from collections import defaultdict
    by_route: dict = defaultdict(lambda: {"count": 0, "errors": 0, "durations": []})
    for r in rows:
        key = f"{r.method} {r.route}"
        by_route[key]["count"] += 1
        if r.status_code >= 400:
            by_route[key]["errors"] += 1
        by_route[key]["durations"].append(r.duration_ms)

    summary = {}
    for route, d in by_route.items():
        durs = sorted(d["durations"])
        n    = len(durs)
        summary[route] = {
            "count":      d["count"],
            "errors":     d["errors"],
            "error_rate": round(d["errors"] / d["count"], 4) if d["count"] else 0,
            "p50_ms":     round(durs[n // 2], 1)       if durs else 0,
            "p95_ms":     round(durs[int(n * .95)], 1) if durs else 0,
            "avg_ms":     round(sum(durs) / n, 1)       if durs else 0,
        }

    total_preds   = db.query(Prediction).count()
    potable_count = db.query(Prediction).filter(Prediction.potable == 1).count()

    log_audit("exploitation_metrics")
    return jsonify({
        "routes":             summary,
        "sample_size":        len(rows),
        "clients_total":      db.query(Client).count(),
        "clients_actifs":     db.query(Client).filter(Client.actif == True).count(),
        "total_prelevements": db.query(Prelevement).count(),
        "total_predictions":  total_preds,
        "potable_rate":       round(potable_count / total_preds, 4)
                              if total_preds else None,
    })


@bp.route("/exploitation/audit", methods=["GET"])
@require_expert(role="exploit")
@timed
def exploitation_audit():
    """
    Journal d'accès RGPD — paginé, filtrable.
    Filtres : actor_type (client|expert), actor_id, action
    """
    db        = g.db
    page      = max(1, int(request.args.get("page", 1)))
    per_page  = min(200, max(1, int(request.args.get("per_page", 50))))

    q = db.query(AuditLog).order_by(AuditLog.timestamp.desc())
    if request.args.get("actor_type"):
        q = q.filter(AuditLog.actor_type == request.args["actor_type"])
    if request.args.get("actor_id"):
        q = q.filter(AuditLog.actor_id == request.args["actor_id"])
    if request.args.get("action"):
        q = q.filter(AuditLog.action.contains(request.args["action"]))

    paged = _paginate(q, page, per_page)
    log_audit("exploitation_audit")
    return jsonify({
        **paged,
        "items": [{
            "id":          l.id,
            "timestamp":   l.timestamp.isoformat(),
            "actor_type":  l.actor_type,
            "actor_id":    l.actor_id,
            "actor_role":  l.actor_role,
            "ip_address":  l.ip_address,
            "action":      l.action,
            "resource_id": l.resource_id,
            "status_code": l.status_code,
            "detail":      l.detail,
        } for l in paged["items"]],
    })
