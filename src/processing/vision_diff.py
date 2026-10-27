#!/usr/bin/env python3
"""Vision Diff — Logical diff between whiteboard OCR and DB state (REQ-T4).

Part of the asymmetric AI stack:
  - Gemini 2.5 Flash Lite → OCR text extraction from whiteboard photo
  - DeepSeek R1 (reasoner)   → Compare OCR output vs DB pending tasks

Flow:
  1. Receive JSON of current pending tasks (from tasks.py list).
  2. Receive array of strings extracted by OCR (from ocr.py whiteboard).
  3. Send both to DeepSeek R1 for multi-step reasoning.
  4. Return structured diff: new tasks, completed task IDs, unchanged.

Usage:
    from src.processing.vision_diff import diff_whiteboard
    result = diff_whiteboard(pending_tasks_json, ocr_texts)
    # → {"new": [...], "completed_ids": [...], "unchanged_ids": [...]}
"""

import json
import os
import sys

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import src._bootstrap  # noqa: F401  (UTF-8 + CA en Windows)

from src.common import deepseek_generate

# ═══════════════════════════════════════════════════════════════
#  Prompt template for DeepSeek R1
# ═══════════════════════════════════════════════════════════════

SYSTEM_PROMPT = (
    "You are a logical diff engine. Your job is to compare two lists of tasks "
    "and determine what changed. You MUST reason step by step internally, then "
    "output ONLY a JSON object. Never include explanations outside the JSON."
)


def _build_diff_prompt(pending_json: str, ocr_texts_json: str) -> str:
    """Build the diff prompt with pending DB tasks and OCR-extracted texts."""
    return (
        "## Task State: Database (pending tasks)\n"
        f"{pending_json}\n\n"
        "## Task State: Whiteboard OCR (tasks visible in the photo)\n"
        f"{ocr_texts_json}\n\n"
        "## Instructions\n"
        "Compare the two lists and determine:\n\n"
        "1. **NEW tasks** — Strings found in the OCR list that do NOT match any "
        "existing task in the DB list (by semantic similarity, not exact string match). "
        "These should be created.\n\n"
        "2. **COMPLETED tasks** — Tasks present in the DB list that are ABSENT from "
        "the OCR list. These were likely erased or checked off on the whiteboard. "
        "Return their DB IDs.\n\n"
        "3. **UNCHANGED tasks** — Tasks present in BOTH lists. Return their DB IDs.\n\n"
        "Matching rules:\n"
        "- 'Lab 2 Empotrados' matches 'Terminar Lab 2 de Empotrados' (semantic match).\n"
        "- 'Comprar leche' does NOT match 'Comprar pan' (different items).\n"
        "- If a DB task has no semantic match in OCR, it was completed (erased from board).\n"
        "- If an OCR string has no semantic match in DB, it's a new task.\n\n"
        "Return EXACTLY this JSON structure:\n"
        '{\n'
        '  "new": ["task text 1", "task text 2"],\n'
        '  "completed_ids": [42, 17],\n'
        '  "unchanged_ids": [5, 8]\n'
        '}\n\n'
        "All arrays can be empty. completed_ids and unchanged_ids must contain "
        "only integers (DB IDs from the pending list). new must contain only strings."
    )


def diff_whiteboard(pending_tasks: list[dict], ocr_texts: list[str]) -> dict:
    """Execute Vision Diff: OCR texts vs DB pending tasks → structured diff.

    Args:
        pending_tasks: List of dicts from tasks.list (must include id, title).
        ocr_texts: List of strings extracted by ocr.py whiteboard.

    Returns:
        {
            "new": ["task text 1", ...],
            "completed_ids": [42, ...],
            "unchanged_ids": [5, ...],
            "ai_model": "deepseek-reasoner"
        }
        Returns a safe fallback (all new, none completed) if DeepSeek fails.
    """
    if not ocr_texts:
        return {"new": [], "completed_ids": [], "unchanged_ids": [],
                "ai_model": "none (empty OCR)", "note": "No text extracted from image"}

    # Build a compact representation of pending tasks for the prompt
    pending_compact = [
        {"id": t["id"], "title": t["title"], "project": t.get("project_tag", "")}
        for t in pending_tasks
    ]
    pending_json = json.dumps(pending_compact, ensure_ascii=False, indent=2)
    ocr_json = json.dumps(ocr_texts, ensure_ascii=False, indent=2)

    prompt = _build_diff_prompt(pending_json, ocr_json)

    try:
        result = deepseek_generate(
            prompt,
            model="deepseek-reasoner",  # R1 for multi-step reasoning
            system_prompt=SYSTEM_PROMPT,
            temperature=0.1,  # Deterministic diff
        )
    except Exception as e:
        print(f"Vision Diff: DeepSeek R1 error: {e}", file=sys.stderr)
        result = None

    if result and isinstance(result, dict):
        return {
            "new": result.get("new", []),
            "completed_ids": result.get("completed_ids", []),
            "unchanged_ids": result.get("unchanged_ids", []),
            "ai_model": "deepseek-reasoner",
        }

    # Fallback: treat all OCR texts as new, complete nothing
    print("Vision Diff: DeepSeek returned no valid result, treating all as new",
          file=sys.stderr)
    return {
        "new": ocr_texts,
        "completed_ids": [],
        "unchanged_ids": [],
        "ai_model": "fallback (DeepSeek unavailable)",
        "warning": "DeepSeek R1 failed — all OCR texts treated as new tasks",
    }


# ═══════════════════════════════════════════════════════════════
#  CLI entry point (for testing / manual diff)
# ═══════════════════════════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Vision Diff — REQ-T4")
    parser.add_argument("--pending", required=True,
                        help="JSON file with pending tasks (from tasks list)")
    parser.add_argument("--ocr", required=True,
                        help="JSON file with OCR texts (from ocr whiteboard)")
    args = parser.parse_args()

    with open(args.pending) as f:
        pending = json.load(f)
    with open(args.ocr) as f:
        ocr = json.load(f)

    # Normalize: if ocr is a dict with "tasks" key, extract it
    if isinstance(ocr, dict):
        ocr = ocr.get("tasks", ocr.get("items", []))

    result = diff_whiteboard(pending, ocr)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
