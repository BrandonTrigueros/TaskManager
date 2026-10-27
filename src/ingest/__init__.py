"""Ingesta — puntos de entrada del sistema.

- cli.py       Router CLI
- heartbeat.py Ciclo periódico de coherencia (embedding backfill, recordatorios, grafo)

El cliente principal es la app Android (ver ANDROID.md), que habla con
src/api/server.py. El bot de Telegram se eliminó en 2026-10-26.
"""
