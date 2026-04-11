#!/usr/bin/env python3
"""Classify Task — AI task categorization using Gemini Flash.

Usage (from project root):
    python3 -m src.tools.TaskManager.classify_task "Terminar Lab 2 de Empotrados"

Or via CLI:
    python3 scripts/cli.py classify "Terminar Lab 2 de Empotrados"
"""

import argparse
import json
import os
import sys

# Ensure project root is in sys.path for `from src.tools.common import ...`
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.tools.common import gemini_generate


def classify_task(text: str):
    prompt = (
        'Analiza esta tarea y clasifica.\n\n'
        f'Tarea: {text}\n\n'
        'Clasifica en:\n'
        '- project_tag: uno de [Empotrados, Computer Vision, HPE, Personal, Universidad, Finanzas, Salud, Hogar]\n'
        '- priority: entero de 1 (baja) a 5 (urgente)\n'
        '- estimated_hours: estimación realista en horas decimales\n\n'
        'Devuelve JSON con keys "project_tag", "priority", "estimated_hours".'
    )

    try:
        result = gemini_generate(prompt)
        if result:
            print(json.dumps(result, ensure_ascii=False))
        else:
            raise ValueError("Failed to parse")
    except Exception as e:
        print(json.dumps({
            "project_tag": "Personal", "priority": 3, "estimated_hours": 1.0,
            "ai_error": str(e)
        }))


def main():
    parser = argparse.ArgumentParser(description="Task Classification")
    parser.add_argument("text", nargs="+")
    args = parser.parse_args()
    classify_task(" ".join(args.text))


if __name__ == "__main__":
    main()
