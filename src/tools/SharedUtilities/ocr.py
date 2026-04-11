#!/usr/bin/env python3
"""OCR Tool — Receipt and whiteboard OCR using Gemini Vision (REST API).

Usage (from project root):
    python3 -m src.tools.SharedUtilities.ocr receipt /path/to/photo.jpg
    python3 -m src.tools.SharedUtilities.ocr whiteboard /path/to/photo.jpg
    python3 -m src.tools.SharedUtilities.ocr describe /path/to/screenshot.jpg

Or via CLI:
    python3 scripts/cli.py ocr-whiteboard /path/to/photo.jpg
"""

import argparse
import base64
import json
import os
import ssl
import sys
import urllib.request
import urllib.error

# Ensure project root is in sys.path for `from src.tools.common import ...`
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.tools.common import GEMINI_API_KEY, GEMINI_MODEL, _SSL_CTX

MIME_MAP = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp",
}


def _gemini_vision(prompt: str, image_path: str) -> dict | list | None:
    """Call Gemini REST API with an image for vision tasks."""
    if not GEMINI_API_KEY:
        return None
    ext = os.path.splitext(image_path)[1].lower()
    mime = MIME_MAP.get(ext, "image/jpeg")
    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/"
        f"models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    )
    payload = json.dumps({
        "contents": [{"parts": [
            {"text": prompt},
            {"inline_data": {"mime_type": mime, "data": img_b64}},
        ]}],
        "generationConfig": {"responseMimeType": "application/json"},
    }).encode()
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, context=_SSL_CTX, timeout=90) as resp:
            data = json.loads(resp.read())
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(text)
    except json.JSONDecodeError:
        # Try stripping markdown fences
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        return json.loads(text)
    except Exception as e:
        print(f"Gemini Vision error: {e}", file=sys.stderr)
        return None


def ocr_receipt(image_path: str):
    """Extract structured data from a receipt/invoice photo."""
    prompt = """Analiza esta imagen de factura/recibo y extrae SOLO un JSON válido:
{
    "amount": monto total como número,
    "currency": "CRC" o "USD",
    "merchant": nombre del comercio,
    "date": fecha en formato YYYY-MM-DD si es visible,
    "payment_method": "efectivo", "tarjeta" o "sinpe" si es visible,
    "items": ["item1", "item2"] lista de artículos si son visibles
}
Responde SOLO el JSON, sin explicaciones."""

    result = _gemini_vision(prompt, image_path)
    if result:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(json.dumps({"error": "Failed to parse receipt"}))
        sys.exit(1)


def ocr_whiteboard(image_path: str):
    """Extract tasks from a whiteboard or notebook photo."""
    prompt = """Analiza esta foto de pizarra/libreta y extrae las tareas o puntos escritos.
Devuelve SOLO un JSON array de strings, donde cada string es una tarea/item:
["tarea 1", "tarea 2", "tarea 3"]
Si no hay tareas claras, extrae los puntos principales que se lean.
Responde SOLO el JSON array."""

    result = _gemini_vision(prompt, image_path)
    if result:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(json.dumps({"error": "Failed to parse whiteboard"}))
        sys.exit(1)


def describe_image(image_path: str):
    """Generate a text description of a screenshot or image for the idea vault."""
    prompt = """Describe esta imagen en español en 2-3 oraciones. Enfócate en el contenido
informacional: qué se muestra, qué conceptos o datos contiene, qué herramientas o tecnologías
aparecen. Devuelve SOLO un JSON:
{"description": "...", "tags": ["tag1", "tag2", "tag3"]}"""

    result = _gemini_vision(prompt, image_path)
    if result:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(json.dumps({"error": "Failed to describe image"}))
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="OCR Tool")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("receipt")
    p.add_argument("image_path")

    p = sub.add_parser("whiteboard")
    p.add_argument("image_path")

    p = sub.add_parser("describe")
    p.add_argument("image_path")

    args = parser.parse_args()

    if not os.path.isfile(args.image_path):
        print(json.dumps({"error": f"File not found: {args.image_path}"}))
        sys.exit(1)

    commands = {
        "receipt": lambda: ocr_receipt(args.image_path),
        "whiteboard": lambda: ocr_whiteboard(args.image_path),
        "describe": lambda: describe_image(args.image_path),
    }
    commands[args.command]()


if __name__ == "__main__":
    main()
