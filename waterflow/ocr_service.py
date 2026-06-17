"""
api/services/ocr_service.py — Service OCR via OCR.space

Veille comparative des solutions OCR cloud (juin 2024) :
┌─────────────────┬──────────────┬─────────────┬──────────────────────────┐
│ Solution        │ Gratuit/mois │ PDF natif   │ Remarques                │
├─────────────────┼──────────────┼─────────────┼──────────────────────────┤
│ OCR.space       │ 25 000 req   │ Oui         │ Simple, REST, FR OK      │
│ Google Vision   │ 1 000 units  │ Via convert │ Très précis, coûteux     │
│ Azure Form Rec. │ 500 pages    │ Oui natif   │ Meilleur sur formulaires │
│ Tesseract OSS   │ Illimité     │ Non direct  │ Hébergé, latence +       │
│ Claude Vision   │ Selon usage  │ Via images  │ Sémantique supérieure    │
└─────────────────┴──────────────┴─────────────┴──────────────────────────┘

Choix retenu : OCR.space (plan gratuit suffisant pour MVP, API REST simple,
support PDF natif, résultats exploitables en FR).
Fallback : Claude Vision (anthropic) si OCR.space échoue ou clé absente.
"""

import os
import re
import json
import base64
import logging
from io import BytesIO
from typing import Any

import requests

logger = logging.getLogger(__name__)

OCR_SPACE_URL    = "https://api.ocr.space/parse/image"
OCR_SPACE_KEY    = os.getenv("OCR_SPACE_API_KEY", "")
ANTHROPIC_KEY    = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL  = "claude-opus-4-6"

FEATURES = [
    "ph", "Hardness", "Solids", "Chloramines", "Sulfate",
    "Conductivity", "Organic_carbon", "Trihalomethanes", "Turbidity",
]

ACCEPTED_MIME = {
    "image/jpeg", "image/jpg", "image/png",
    "image/webp", "image/gif", "application/pdf",
}

_EXTRACTION_PROMPT = """\
Tu es un assistant spécialisé en analyse de rapports de laboratoire d'eau potable.
Extrais les données du document et réponds UNIQUEMENT avec un JSON valide (sans backticks).

Structure attendue :
{
  "date_prelevement": "YYYY-MM-DD ou null",
  "id_client": "identifiant ou null",
  "lieu": "lieu de prélèvement ou null",
  "mesures": {
    "ph": <nombre|null>, "Hardness": <nombre|null>, "Solids": <nombre|null>,
    "Chloramines": <nombre|null>, "Sulfate": <nombre|null>, "Conductivity": <nombre|null>,
    "Organic_carbon": <nombre|null>, "Trihalomethanes": <nombre|null>, "Turbidity": <nombre|null>
  },
  "observations": "texte libre ou null",
  "raw_text": "transcription intégrale",
  "warnings": ["liste de champs manquants ou douteux"]
}

Règles : virgule décimale → point. Si valeur floue → null + warning. Ne devine pas."""


# ── OCR.space ───────────────────────────────────────────────────────────────

def _ocr_space(file_bytes: bytes, mime: str, filename: str = "document") -> str:
    """Envoie le fichier à OCR.space, retourne le texte extrait brut."""
    b64 = base64.b64encode(file_bytes).decode()
    ext = mime.split("/")[-1].replace("jpeg", "jpg")

    payload = {
        "base64Image":   f"data:{mime};base64,{b64}",
        "language":      "fre",
        "isOverlayRequired": False,
        "isTable":       True,
        "OCREngine":     2,      # moteur 2 : meilleur sur tableaux structurés
        "filetype":      ext.upper(),
    }
    headers = {"apikey": OCR_SPACE_KEY}

    resp = requests.post(OCR_SPACE_URL, data=payload, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    if data.get("IsErroredOnProcessing"):
        msg = data.get("ErrorMessage", ["Erreur OCR.space inconnue"])
        raise RuntimeError(f"OCR.space : {msg}")

    pages = data.get("ParsedResults", [])
    return "\n\n".join(p.get("ParsedText", "") for p in pages).strip()


# ── Claude Vision ────────────────────────────────────────────────────────────

def _claude_vision_extract(file_bytes: bytes, mime: str) -> dict[str, Any]:
    """Extraction directe via Claude Vision (contournement OCR.space)."""
    import anthropic

    client  = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    b64     = base64.standard_b64encode(file_bytes).decode()

    # Pour les PDF, on tente le type document natif d'Anthropic
    if mime == "application/pdf":
        content_block = {
            "type": "document",
            "source": {"type": "base64", "media_type": "application/pdf", "data": b64},
        }
    else:
        canonical = {"image/jpg": "image/jpeg"}.get(mime, mime)
        content_block = {
            "type": "image",
            "source": {"type": "base64", "media_type": canonical, "data": b64},
        }

    response = client.messages.create(
        model      = ANTHROPIC_MODEL,
        max_tokens = 2048,
        messages   = [{
            "role": "user",
            "content": [
                content_block,
                {"type": "text", "text": _EXTRACTION_PROMPT},
            ],
        }],
    )
    raw = response.content[0].text
    clean = re.sub(r"```(?:json)?\s*", "", raw).strip()
    match = re.search(r"\{.*\}", clean, re.DOTALL)
    if not match:
        raise ValueError(f"Réponse Claude non JSON : {raw[:300]}")
    return json.loads(match.group())


# ── Claude text → structure ──────────────────────────────────────────────────

def _claude_structure(raw_text: str) -> dict[str, Any]:
    """Utilise Claude pour structurer le texte brut extrait par OCR.space."""
    import anthropic

    client   = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    prompt   = (
        f"Voici le texte brut extrait d'une fiche de prélèvement d'eau :\n\n"
        f"---\n{raw_text}\n---\n\n"
        f"{_EXTRACTION_PROMPT}"
    )
    response = client.messages.create(
        model      = ANTHROPIC_MODEL,
        max_tokens = 1024,
        messages   = [{"role": "user", "content": prompt}],
    )
    raw   = response.content[0].text
    clean = re.sub(r"```(?:json)?\s*", "", raw).strip()
    match = re.search(r"\{.*\}", clean, re.DOTALL)
    if not match:
        raise ValueError(f"Réponse Claude non JSON : {raw[:300]}")
    return json.loads(match.group())


# ── Normalisation ────────────────────────────────────────────────────────────

def _normalise(data: dict) -> dict[str, Any]:
    """Normalise et valide le dict extrait."""
    mesures  = data.get("mesures", {})
    warnings = list(data.get("warnings", []))

    for field in FEATURES:
        val = mesures.get(field)
        if val is None:
            warnings.append(f"Champ absent ou illisible : {field}")
        else:
            try:
                mesures[field] = float(str(val).replace(",", "."))
            except (ValueError, TypeError):
                warnings.append(f"Valeur non numérique pour {field} : {val!r}")
                mesures[field] = None

    data["mesures"]  = mesures
    data["warnings"] = warnings
    data.setdefault("date_prelevement", None)
    data.setdefault("id_client",        None)
    data.setdefault("lieu",             None)
    data.setdefault("observations",     None)
    data.setdefault("raw_text",         "")
    return data


# ── Point d'entrée public ────────────────────────────────────────────────────

def extract_from_document(file_bytes: bytes, mime: str) -> dict[str, Any]:
    """
    Stratégie d'extraction :
    1. Si OCR.space configuré → OCR.space puis Claude structure le texte
    2. Sinon (ou si OCR.space échoue) → Claude Vision directement

    Retourne un dict normalisé avec mesures, warnings, raw_text, etc.
    """
    mime = mime.lower().split(";")[0].strip()
    if mime not in ACCEPTED_MIME:
        raise ValueError(f"Type non supporté : {mime}")

    # Stratégie 1 : OCR.space + Claude structuration
    if OCR_SPACE_KEY:
        try:
            logger.info("Tentative OCR.space | type=%s taille=%.1fko", mime, len(file_bytes)/1024)
            raw_text = _ocr_space(file_bytes, mime)
            if len(raw_text) < 20:
                raise ValueError("Texte OCR.space trop court, basculement sur Claude Vision")
            logger.info("OCR.space OK | %d chars", len(raw_text))
            result = _claude_structure(raw_text)
            if not result.get("raw_text"):
                result["raw_text"] = raw_text
            return _normalise(result)
        except Exception as exc:
            logger.warning("OCR.space échoué (%s) — fallback Claude Vision", exc)

    # Stratégie 2 : Claude Vision (fallback ou mode sans OCR.space)
    if not ANTHROPIC_KEY:
        raise RuntimeError(
            "Aucun service OCR disponible. "
            "Définissez OCR_SPACE_API_KEY et/ou ANTHROPIC_API_KEY."
        )

    logger.info("Claude Vision | type=%s taille=%.1fko", mime, len(file_bytes)/1024)
    result = _claude_vision_extract(file_bytes, mime)
    return _normalise(result)
