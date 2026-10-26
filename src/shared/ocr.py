#!/usr/bin/env python3
"""OCR Tool — Vision engine using Gemini 2.5 Flash Lite (REST/urllib, Zscaler-safe).

Part of the asymmetric AI stack:
  - Gemini 2.5 Flash Lite → Vision/OCR nativo (whiteboard, receipt, describe)
  - DeepSeek V4-Flash / R1 → Classification, Vision Diff

All API calls delegate to bt_common.py (SSOT). No duplicated REST logic.

Usage (from project root):
    python3 -m src.shared.ocr receipt /path/to/photo.jpg
    python3 -m src.shared.ocr whiteboard /path/to/photo.jpg
    python3 -m src.shared.ocr describe /path/to/screenshot.jpg

Or via CLI:
    python3 scripts/cli.py ocr-whiteboard /path/to/photo.jpg
"""

import argparse
import base64
import json
import os
import sys

# Ensure project root is in sys.path for `from src.common import ...`
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.common import gemini_generate

MIME_MAP = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp",
}

# Gemini 2.5 Flash Lite max image size ~7 MB base64-encoded.
# For Tailscale bandwidth efficiency, warn if > 5 MB raw file.
_MAX_RAW_BYTES = 5 * 1024 * 1024


def _load_image_b64(image_path: str) -> tuple[str, str]:
    """Load image from disk, return (base64_string, mime_type).

    Emits a warning to stderr if the image is large enough to cause
    Tailscale bandwidth issues.
    """
    ext = os.path.splitext(image_path)[1].lower()
    mime = MIME_MAP.get(ext, "image/jpeg")
    file_size = os.path.getsize(image_path)
    if file_size > _MAX_RAW_BYTES:
        print(f"ocr: image is {file_size / 1024 / 1024:.1f} MB — consider "
              f"resizing for Tailscale bandwidth",
              file=sys.stderr)
    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()
    return img_b64, mime


def _vision(prompt: str, image_path: str) -> dict | list | None:
    """Run Gemini Vision via SSOT gemini_generate.

    All REST/auth/json-parsing logic is delegated to common.py — no duplication.
    """
    img_b64, _mime = _load_image_b64(image_path)
    return gemini_generate(prompt, image_base64=img_b64)


def ocr_receipt(image_path: str):
    """Extract structured data from a receipt/invoice photo."""
    prompt = (
        "Analiza esta imagen de factura/recibo y extrae SOLO un JSON válido:\n"
        "{\n"
        '  "amount": monto total como número,\n'
        '  "currency": "CRC" o "USD",\n'
        '  "merchant": nombre del comercio,\n'
        '  "date": fecha YYYY-MM-DD si es visible,\n'
        '  "payment_method": "efectivo", "tarjeta" o "sinpe",\n'
        '  "items": ["item1", "item2"]\n'
        "}\n"
        "Responde SOLO el JSON, sin explicaciones ni markdown."
    )
    result = _vision(prompt, image_path)
    if result:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(json.dumps({"error": "Gemini Vision returned no result"}))
        sys.exit(1)


def ocr_whiteboard(image_path: str):
    """Extract tasks from a whiteboard or notebook photo.

    Returns a JSON array of strings — one per visible task/item.
    Designed as input for the Vision Diff pipeline (vision_diff.py).
    """
    prompt = (
        "Analiza esta foto de pizarra/libreta y extrae EXCLUSIVAMENTE las tareas "
        "o ítems escritos a mano.\n"
        "Reglas:\n"
        "- Si una tarea está TACHADA o tiene una línea encima, NO la incluyas.\n"
        "- Si una tarea tiene un CHECKMARK (✓) al lado, NO la incluyas.\n"
        "- Solo incluí tareas activas, pendientes, sin marca de completado.\n"
        "- Cada tarea debe ser un string con el texto exacto visible.\n\n"
        "Devuelve SOLO un JSON array de strings:\n"
        '["tarea 1", "tarea 2", "tarea 3"]\n\n'
        "Si no hay tareas claras, devuelve un array vacío: []\n"
        "Responde SOLO el JSON array, sin explicaciones ni markdown."
    )
    result = _vision(prompt, image_path)
    if result is not None:
        if isinstance(result, list):
            print(json.dumps(result, ensure_ascii=False))
        else:
            # Gemini sometimes wraps in {"tasks": [...]}
            tasks = result.get("tasks", result.get("items", []))
            print(json.dumps(tasks if isinstance(tasks, list) else [], ensure_ascii=False))
    else:
        print(json.dumps({"error": "Gemini Vision returned no result"}))
        sys.exit(1)


def describe_image(image_path: str):
    """Generate a text description for the IdeaVault."""
    prompt = (
        "Describe esta imagen en español en 2-3 oraciones. Enfócate en el contenido "
        "informacional: qué se muestra, qué conceptos o datos contiene, qué herramientas "
        "o tecnologías aparecen.\n"
        "Devuelve SOLO un JSON:\n"
        '{"description": "...", "tags": ["tag1", "tag2", "tag3"]}\n'
        "Responde SOLO el JSON, sin explicaciones ni markdown."
    )
    result = _vision(prompt, image_path)
    if result:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(json.dumps({"error": "Gemini Vision returned no result"}))
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="OCR Tool — Gemini 2.5 Flash Lite Vision")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("receipt", help="Extract structured data from receipt photo")
    p.add_argument("image_path")

    p = sub.add_parser("whiteboard", help="Extract task list from whiteboard/notebook photo")
    p.add_argument("image_path")

    p = sub.add_parser("describe", help="Generate description + tags for IdeaVault")
    p.add_argument("image_path")

    args = parser.parse_args()

    if not os.path.isfile(args.image_path):
        print(json.dumps({"error": f"File not found: {args.image_path}"}))
        sys.exit(1)

    {
        "receipt": lambda: ocr_receipt(args.image_path),
        "whiteboard": lambda: ocr_whiteboard(args.image_path),
        "describe": lambda: describe_image(args.image_path),
    }[args.command]()


if __name__ == "__main__":
    main()
