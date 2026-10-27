# HANDOFF — TaskManager nativo en Windows

> **Fecha:** 2026-10-26
> **Estado:** todo corre nativo en Windows. **No hay WSL, no hay Docker.**

---

## 0. Léeme primero, en 30 segundos

El backend es Python que escribe JSON a stdout. Cada módulo se ejecuta con
`python -m src.<paquete>.<modulo>`. No hay servidor de aplicaciones, ni agente
LLM, ni contenedores: solo procesos, Postgres y la API HTTP.

**Tres cosas que NO hay que rehacer:**

1. El Grafo Vivo de 6 capas — cableado y verificado.
2. `next_action` v1 con los dos slots — 28 tests pasando.
3. La API HTTP local — responde `health: db up`.

---

## 1. Layout

```
C:\Users\trigueros\Dev\TaskManager\
├── src/                      # backend Python
│   ├── _bootstrap.py         # UTF-8 + CA bundle (importar siempre primero)
│   ├── processing/           # next_action, tasks, classify, vision_diff
│   ├── knowledge/            # graph, co_occurrence, embeddings
│   ├── shared/               # ocr, export_md, transcribe
│   ├── ingest/               # heartbeat, cli
│   └── api/                  # server.py (http.server, stdlib)
├── db/schema.sql
├── android/                  # cliente Kotlin/Compose
├── scripts/                  # setup-windows-admin.ps1
├── tests/
└── .venv/                    # Python 3.14, todas las deps
```

---

## 2. Toolchain instalado

| Pieza | Versión | Ruta / cómo |
|---|---|---|
| Python | 3.14.4 | `C:\Users\trigueros\AppData\Local\Python\pythoncore-3.14-64\python.exe` |
| venv | — | `.\.venv\Scripts\python.exe` |
| PostgreSQL | 16.15 | `C:\Program Files\PostgreSQL\16` |
| pgvector | 0.8.7 | `scripts/pgvector-win/` → requiere admin para copiar |
| Ollama | 0.40.11 | modelo `nomic-embed-text` (274 MB) ya descargado |
| JDK | 21 Temurin | para Gradle |
| Android SDK | compileSdk 35, minSdk 26 | Android Studio |

---

## 3. Puesta en marcha desde cero

```powershell
# 1. Python
python -m venv .venv
.\.venv\Scripts\pip.exe install -r requirements.txt

# 2. PostgreSQL + pgvector  (EJECUTAR COMO ADMINISTRADOR)
cd scripts
.\setup-windows-admin.ps1

# 3. Verificar
cd ..
.\.venv\Scripts\python.exe tests\test_next_action.py
```

`setup-windows-admin.ps1` hace todo lo privilegiado de una sola vez: copia
pgvector, arranca el servicio, crea el rol `hb_admin`, la base `heartbeat`,
las extensiones y aplica `db/schema.sql`.

---

## 4. Uso diario

```powershell
# red de seguridad de privacidad: solo localhost
.\.venv\Scripts\python.exe -m src.ingest.heartbeat --action all
.\.venv\Scripts\python.exe -m src.processing.next_action
.\.venv\Scripts\python.exe -m src.api.server          # 0.0.0.0:8787
```

La app Android apunta a `http://10.0.2.2:8787` desde el emulador
(`10.0.2.2` = el host visto desde el emulador).

---

## 5. Estado verificado (probado en Windows nativo)

| Componente | Estado | Evidencia |
|---|---|---|
| Import de los 12 módulos | ✅ | 12 ok, 0 fail |
| `next_action` | ✅ | 28/28 tests |
| UTF-8 en consola cp1252 | ✅ | vía `src/_bootstrap.py` |
| PostgreSQL + pgvector | ⏳ | pendiente el script elevado |
| Grafo Vivo | ⏳ | pendiente DB |
| App Android compila | ✅ | `app-debug.apk` 9.1 MB |

---

## 6. Problemas conocidos

**`ctranslate2` bloqueado por App Control (WinError 4551).**
La política WDAC corporativa bloquea `ctranslate2.dll`, motor de
`faster-whisper`. `av` sí funciona. Consecuencia: **la transcripción de audio
no corre en esta máquina**. Los otros 11 módulos no se ven afectados.

Opciones, en orden de menor esfuerzo:
1. Usar la API de Gemini para audio (ya hay key configurada).
2. Pedir a IT la allowlist de `ctranslate2.dll`.
3. Migrar a `whisper.cpp` (binario nativo, sin DLL bloqueada).

**Consola cp1252.** Cualquier `print` con emojis revienta si no se importa
`src._bootstrap` primero. Todos los módulos ejecutables ya lo importan.

**PowerShell `curl`.** Es alias de `Invoke-WebRequest`. Usar `curl.exe`.

---

## 7. Qué sigue

| Prioridad | Tarea |
|---|---|
| 1 | Correr `setup-windows-admin.ps1` como admin y validar `/health` |
| 2 | Probar la app en el emulador contra la API real |
| 3 | Captura por foto/voz en la app |
| 4 | Reemplazar `ctranslate2` por la API de audio de Gemini |
