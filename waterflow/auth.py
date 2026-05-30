"""
api/middleware/auth.py — Authentification Waterflow 2

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 MONDE 1 — CLIENTS (collectivités)
   Mécanisme  : clé API générée par la plateforme
   Transport  : header  X-API-Key: <clé>
              : ou param ?api_key=<clé>
   Périmètre  : leurs propres données uniquement
   Décorateur : @require_client_key

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 MONDE 2 — EXPERTS (analyste qualité / responsable exploitation)
   Mécanisme  : tokens statiques configurés côté serveur (variable
                d'environnement). Modèle intentionnellement simple
                — pas de système d'auth complet (hors périmètre).
   Variable   : EXPERT_TOKENS="login:token:role,login2:token2:role2"
   Rôles      : analyste → données, dashboards, gestion clients
                exploit  → supervision, métriques, audit + tout analyste
   Transport  : Authorization: Bearer <token>
   Décorateur : @require_expert()               → tout expert valide
              : @require_expert(role="analyste") → analyste ou exploit
              : @require_expert(role="exploit")  → exploit uniquement

 Exemple de configuration minimale (.env ou variable système) :
   EXPERT_TOKENS="alice:token-alice-32chars-minimum:analyste,bob:token-bob-32chars-minimum:exploit"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Contexte flask.g après authentification réussie :
  g.actor_type   : 'client' | 'expert'
  g.client       : objet Client         (monde client uniquement)
  g.expert_login : login configuré      (monde expert uniquement)
  g.expert_role  : 'analyste'|'exploit' (monde expert uniquement)
  g.db           : session SQLAlchemy
"""

import os
import hashlib
import logging
import time
from functools import wraps

from flask import request, jsonify, g
from sqlalchemy.orm import Session

from api.models.db import Client, AuditLog, RequestMetric, get_db, utcnow

logger = logging.getLogger(__name__)

# Longueur minimale recommandée pour les tokens experts (caractères)
_TOKEN_MIN_LEN = 20


# ════════════════════════════════════════════════════════════════════════════
# Chargement et validation des tokens experts au démarrage
# ════════════════════════════════════════════════════════════════════════════

def _load_expert_tokens() -> dict[str, tuple[str, str]]:
    """
    Parse EXPERT_TOKENS="login:token:role,login2:token2:role2"
    Retourne { sha256(token): (login, role) }

    Appelé une seule fois au démarrage du module.
    Émet des warnings si la configuration est absente ou mal formée.
    """
    raw    = os.getenv("EXPERT_TOKENS", "").strip()
    result: dict[str, tuple[str, str]] = {}

    if not raw:
        logger.warning(
            "EXPERT_TOKENS non défini — aucun expert ne peut se connecter. "
            "Définissez EXPERT_TOKENS='login:token:role,...' dans l'environnement."
        )
        return result

    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue

        parts = entry.split(":")
        if len(parts) != 3:
            logger.warning(
                "EXPERT_TOKENS : entrée ignorée (format attendu login:token:role) : %r",
                entry,
            )
            continue

        login, token, role = (p.strip() for p in parts)

        if not login:
            logger.warning("EXPERT_TOKENS : login vide, entrée ignorée.")
            continue

        if role not in ("analyste", "exploit"):
            logger.warning(
                "EXPERT_TOKENS : rôle '%s' inconnu pour '%s'. "
                "Valeurs acceptées : analyste | exploit. Entrée ignorée.",
                role, login,
            )
            continue

        if len(token) < _TOKEN_MIN_LEN:
            logger.warning(
                "EXPERT_TOKENS : token de '%s' trop court (%d chars, min %d). "
                "Utilisez un token d'au moins %d caractères.",
                login, len(token), _TOKEN_MIN_LEN, _TOKEN_MIN_LEN,
            )
            # On accepte quand même pour ne pas bloquer le démarrage,
            # mais le warning est émis.

        token_hash = hashlib.sha256(token.encode()).hexdigest()

        if token_hash in result:
            logger.warning(
                "EXPERT_TOKENS : collision de token détectée pour '%s'. Entrée ignorée.",
                login,
            )
            continue

        result[token_hash] = (login, role)
        logger.info("Expert configuré : login='%s' rôle='%s'", login, role)

    if not result:
        logger.warning(
            "EXPERT_TOKENS défini mais aucune entrée valide — "
            "vérifiez le format : 'login:token:role,...'"
        )

    return result


# Chargé une fois au démarrage du module
_EXPERT_TOKENS: dict[str, tuple[str, str]] = _load_expert_tokens()


def _resolve_expert(bearer: str | None) -> tuple[str, str] | None:
    """
    Résout un header Authorization: Bearer <token>.
    Retourne (login, role) si valide, None sinon.
    Comparaison en temps constant via hash.
    """
    if not bearer or not bearer.startswith("Bearer "):
        return None
    raw_token  = bearer[7:].strip()
    if not raw_token:
        return None
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    return _EXPERT_TOKENS.get(token_hash)


# ════════════════════════════════════════════════════════════════════════════
# Résolution client par clé API
# ════════════════════════════════════════════════════════════════════════════

def _resolve_client(raw_key: str | None, db: Session) -> Client | None:
    """
    Vérifie la clé API contre la base de données.
    Retourne le Client si la clé est valide et le compte actif.
    """
    if not raw_key:
        return None
    key_hash = Client.hash_key(raw_key)
    return (
        db.query(Client)
          .filter(Client.api_key_hash == key_hash, Client.actif == True)
          .first()
    )


# ════════════════════════════════════════════════════════════════════════════
# Audit RGPD et métriques
# ════════════════════════════════════════════════════════════════════════════

def _pseudo_ip(ip: str | None) -> str:
    """Pseudonymise l'IP : masque le dernier octet IPv4."""
    if not ip:
        return "unknown"
    parts = ip.split(".")
    if len(parts) == 4:
        return f"{parts[0]}.{parts[1]}.{parts[2]}.xxx"
    # IPv6 : masque après le dernier ':'
    return ip[:ip.rfind(":") + 1] + "xxx" if ":" in ip else ip


def _write_audit(
    db: Session, *,
    actor_type: str,
    actor_id: str | None,
    actor_role: str | None,
    action: str,
    resource_id: str | None = None,
    status_code: int = 200,
    detail: str | None = None,
) -> None:
    try:
        db.add(AuditLog(
            actor_type  = actor_type,
            actor_id    = actor_id,
            actor_role  = actor_role,
            ip_address  = _pseudo_ip(request.remote_addr),
            action      = action,
            resource_id = resource_id,
            status_code = status_code,
            detail      = detail,
        ))
        db.commit()
    except Exception as exc:
        logger.error("Audit log échoué : %s", exc)
        db.rollback()


def log_audit(
    action: str,
    resource_id: str | None = None,
    status_code: int = 200,
    detail: str | None = None,
) -> None:
    """
    Enregistre un événement d'audit depuis une route.
    Lit actor_type / actor_id depuis flask.g (disponible après @require_*).
    """
    db = getattr(g, "db", next(get_db()))
    _write_audit(
        db,
        actor_type  = getattr(g, "actor_type", "unknown"),
        actor_id    = getattr(g, "expert_login", None)
                      or (g.client.id_client if hasattr(g, "client") else None),
        actor_role  = getattr(g, "expert_role", None) or "client",
        action      = action,
        resource_id = resource_id,
        status_code = status_code,
        detail      = detail,
    )


def record_metric(
    route: str,
    method: str,
    status_code: int,
    duration_ms: float,
) -> None:
    """Enregistre une métrique de performance. Non bloquant."""
    db = next(get_db())
    try:
        db.add(RequestMetric(
            route       = route,
            method      = method,
            status_code = status_code,
            duration_ms = duration_ms,
            actor_type  = getattr(g, "actor_type", None),
            actor_hint  = (
                g.client.api_key_hint
                if hasattr(g, "client")
                else getattr(g, "expert_login", None)
            ),
        ))
        db.commit()
    except Exception as exc:
        logger.error("Metric échouée : %s", exc)
        db.rollback()
    finally:
        db.close()


# ════════════════════════════════════════════════════════════════════════════
# Décorateurs d'authentification
# ════════════════════════════════════════════════════════════════════════════

def require_client_key(f):
    """
    Authentifie un CLIENT par clé API.

    La clé est cherchée dans l'ordre :
      1. Header  X-API-Key: <clé>
      2. Paramètre URL  ?api_key=<clé>

    En cas de succès, injecte dans flask.g :
      g.actor_type = 'client'
      g.client     = objet Client
      g.db         = session SQLAlchemy
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        raw_key = (
            request.headers.get("X-API-Key")
            or request.args.get("api_key")
        )
        db     = next(get_db())
        client = _resolve_client(raw_key, db)

        if not client:
            _write_audit(
                db,
                actor_type  = "client",
                actor_id    = None,
                actor_role  = "client",
                action      = "auth_failed",
                status_code = 401,
                detail      = f"path={request.path} ip={_pseudo_ip(request.remote_addr)}",
            )
            logger.warning(
                "Auth client échouée | ip=%s path=%s",
                request.remote_addr, request.path,
            )
            return jsonify({"error": "Clé API invalide ou absente."}), 401

        g.actor_type = "client"
        g.client     = client
        g.db         = db
        return f(*args, **kwargs)

    return decorated


def require_expert(role: str | None = None):
    """
    Authentifie un EXPERT par token Bearer (variable EXPERT_TOKENS).

    role  : rôle minimum requis pour accéder à la route.
            None       → tout expert valide est accepté
            'analyste' → analyste ou exploit
            'exploit'  → exploit uniquement

    Note : 'exploit' est un super-rôle — il accède à tout ce qu'un
    analyste peut faire, plus les routes de supervision.

    En cas de succès, injecte dans flask.g :
      g.actor_type   = 'expert'
      g.expert_login = login configuré dans EXPERT_TOKENS
      g.expert_role  = 'analyste' | 'exploit'
      g.db           = session SQLAlchemy
    """
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            bearer = request.headers.get("Authorization")
            result = _resolve_expert(bearer)

            if not result:
                logger.warning(
                    "Auth expert échouée | ip=%s path=%s",
                    request.remote_addr, request.path,
                )
                return jsonify({"error": "Token expert invalide ou absent."}), 401

            login, expert_role = result

            # exploit est super-rôle : accès à toutes les routes expert
            if role and expert_role != "exploit" and expert_role != role:
                return jsonify({
                    "error": (
                        f"Accès refusé. Rôle requis : '{role}'. "
                        f"Votre rôle : '{expert_role}'."
                    )
                }), 403

            db = next(get_db())
            g.actor_type   = "expert"
            g.expert_login = login
            g.expert_role  = expert_role
            g.db           = db
            return f(*args, **kwargs)

        return decorated
    return decorator


def timed(f):
    """
    Décorateur de mesure de performance.
    Enregistre la durée de la requête dans request_metrics.
    À placer après les décorateurs d'auth.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        t0     = time.perf_counter()
        result = f(*args, **kwargs)
        code   = result[1] if isinstance(result, tuple) else 200
        record_metric(
            route       = request.path,
            method      = request.method,
            status_code = code,
            duration_ms = (time.perf_counter() - t0) * 1000,
        )
        return result
    return decorated
