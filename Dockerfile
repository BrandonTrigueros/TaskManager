# ─── BT-Core TaskManager Dockerfile ──────────────────────────
# Imagen única para bot, heartbeat y CLI.
#   docker build -t taskmanager .
#   docker compose up -d

FROM python:3.12-slim

# ── System deps ─────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# ── Python deps ─────────────────────────────────────────────
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir \
        python-telegram-bot[job-queue]>=21.0 \
        numpy \
        scipy \
        pgvector

# ── Download faster-whisper model (small) at build time ──────
RUN python3 -c "from faster_whisper import WhisperModel; \
    WhisperModel('small', device='cpu', compute_type='int8')" 2>/dev/null || true

# ── App code ─────────────────────────────────────────────────
COPY src/ ./src/
COPY db/schema.sql ./db/schema.sql
COPY scripts/ ./scripts/
COPY tests/ ./tests/

# ── Default entrypoint (override via compose command:) ───────
ENV PYTHONUNBUFFERED=1
CMD ["python3", "-m", "src.ingest.bot"]
