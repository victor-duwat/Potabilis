"""
extensions.py — Extensions Flask partagées (limiter, etc.)

Séparé de app.py pour éviter les imports circulaires :
  app.py    → importe limiter pour l'initialiser avec l'app
  routes.py → importe limiter pour appliquer les décorateurs
"""

import hashlib
from flask import request
from flask_limiter import Limiter


def _rate_limit_key() -> str:
    """
    Clé de rate limiting :
    - Requête avec clé API → hash SHA-256 tronqué (identifie le client, pas la clé)
    - Sinon → IP source (routes publiques / tentatives non authentifiées)
    """
    raw_key = request.headers.get("X-API-Key")
    if raw_key:
        return hashlib.sha256(raw_key.encode()).hexdigest()[:16]
    return request.remote_addr or "unknown"


limiter = Limiter(
    key_func=_rate_limit_key,
    storage_uri="memory://",
    default_limits=["300 per hour", "60 per minute"],
)
