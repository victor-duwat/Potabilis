"""
logging_config.py — Journalisation structurée en JSON (compétence C20).

Pourquoi du JSON plutôt que du texte libre ?
Un log en texte n'est ni filtrable ni agrégeable : en plein incident, impossible
de répondre à « combien d'échecs OCR sur les 5 dernières minutes, et pour quel
client ? ». Chaque log devient ici un **événement** : une ligne JSON avec un nom
d'événement stable (`event`) et son contexte métier, directement exploitable par
un agrégateur (Loki, ELK) ou un simple `jq`.

    logger.warning("ocr_fallback", extra={"error": "ReadTimeout", "duration_ms": 30000})
    -> {"timestamp":"...","level":"WARNING","logger":"ocr_service",
        "event":"ocr_fallback","error":"ReadTimeout","duration_ms":30000}

Aucune dépendance externe : `json` + `logging` de la bibliothèque standard.

RGPD : on journalise des identifiants et des métadonnées (durées, statuts), jamais
le contenu des fiches ni la réponse OCR complète — cela ferait fuiter des données
personnelles dans les logs et les ferait exploser en volume.
"""

import json
import logging
import os
from datetime import datetime, timezone

# Attributs techniques posés par `logging` sur chaque enregistrement : tout le
# reste vient de `extra={...}` et constitue le contexte métier à sérialiser.
_RESERVED = set(
    logging.LogRecord(name="", level=0, pathname="", lineno=0, msg="", args=(), exc_info=None).__dict__
) | {"message", "asctime", "taskName"}


class JsonLogFormatter(logging.Formatter):
    """Sérialise chaque enregistrement en une ligne JSON."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        # Contexte métier transmis via extra={...}
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def setup_logging() -> None:
    """Configure la journalisation du processus.

    LOG_FORMAT=json (défaut) : une ligne JSON par événement — format de production,
                               attendu par les agrégateurs de logs.
    LOG_FORMAT=text          : format lisible, pratique en développement local.
    LOG_LEVEL                : DEBUG / INFO / WARNING / ERROR (défaut INFO).
    """
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    handler = logging.StreamHandler()

    if os.getenv("LOG_FORMAT", "json").lower() == "text":
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s — %(message)s"))
    else:
        handler.setFormatter(JsonLogFormatter())

    # force=True : remplace les handlers déjà posés (Gunicorn, Flask) pour garantir
    # un format homogène sur tout le processus.
    logging.basicConfig(level=level, handlers=[handler], force=True)
