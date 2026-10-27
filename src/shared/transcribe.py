#!/usr/bin/env python3
"""Audio Transcription — Faster-Whisper local (REQ-T3).

Runs entirely on-device (LOQ Hub). Zero cost, 100% privacy.
No audio ever leaves the machine.

Model: small (~500MB RAM, fast on CPU, good enough for Spanish)
Fallback: tiny (~200MB RAM) if small fails to load.

Usage:
    python3 -m src.shared.transcribe /path/to/audio.ogg
    python3 -m src.shared.transcribe /path/to/voice_note.mp3

Dependencies:
    pip install faster-whisper
"""

import argparse
import json
import os
import sys

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import src._bootstrap  # noqa: F401  (UTF-8 + CA en Windows)

WHISPER_MODEL_SIZE = os.environ.get("WHISPER_MODEL", "small")


def transcribe(audio_path: str, model_size: str | None = None) -> str | None:
    """Transcribe an audio file using Faster-Whisper.

    Args:
        audio_path: Path to audio file (.ogg, .mp3, .wav, .m4a).
        model_size: Whisper model size (tiny, base, small, medium, large).
                    Defaults to WHISPER_MODEL env var or "small".

    Returns:
        Transcribed text string, or None on failure.
    """
    if not os.path.isfile(audio_path):
        print(f"Audio file not found: {audio_path}", file=sys.stderr)
        return None

    if model_size is None:
        model_size = WHISPER_MODEL_SIZE

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print(
            "faster-whisper not installed. Run: pip install faster-whisper",
            file=sys.stderr,
        )
        return None

    # Try requested model size, fall back to tiny
    for size in (model_size, "tiny"):
        try:
            print(f"Loading Faster-Whisper model: {size}...", file=sys.stderr)
            model = WhisperModel(size, device="cpu", compute_type="int8")
            segments, info = model.transcribe(audio_path, beam_size=5)
            text = " ".join(s.segment.text.strip() for s in segments)
            print(
                f"Transcription complete ({info.language}, "
                f"{info.duration:.1f}s audio)",
                file=sys.stderr,
            )
            return text.strip()
        except Exception as e:
            print(f"Model {size} failed: {e}", file=sys.stderr)
            if size == "tiny":
                return None
            print("Falling back to tiny model...", file=sys.stderr)

    return None


def main():
    parser = argparse.ArgumentParser(description="Audio Transcription — Faster-Whisper")
    parser.add_argument("audio_path", help="Path to audio file")
    parser.add_argument(
        "--model",
        default=WHISPER_MODEL_SIZE,
        help=f"Model size (default: {WHISPER_MODEL_SIZE})",
    )
    args = parser.parse_args()

    text = transcribe(args.audio_path, args.model)
    if text:
        print(json.dumps({"text": text, "model": args.model}, ensure_ascii=False))
    else:
        print(json.dumps({"error": "Transcription failed"}))
        sys.exit(1)


if __name__ == "__main__":
    main()
