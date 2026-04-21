#!/usr/bin/env bash
set -euo pipefail

# ─── TaskManager — LOQ Hub Setup ────────────────────────────────
# Installs OpenClaw, PostgreSQL (Docker), Python deps, and links the skill.
#
# Prerequisites on LOQ (WSL2 or native Linux):
#   - Node.js 22+ (or 24)
#   - Docker (Docker Desktop on WSL2 or docker-ce)
#   - Python 3.11+
#   - Tailscale connected
#
# Usage:
#   1. Clone the repo:  git clone https://github.com/BrandonTrigueros/TaskManager.git ~/TaskManager
#   2. Run:             cd ~/TaskManager && bash scripts/setup_loq.sh
#   3. Edit .env with real values (Telegram token, Gemini key, DB password)
#   4. Restart:         openclaw gateway restart
# ─────────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OPENCLAW_HOME="${OPENCLAW_HOME:-$HOME/.openclaw}"
OPENCLAW_WORKSPACE="$OPENCLAW_HOME/workspace"

echo "══════════════════════════════════════════"
echo "  TaskManager — LOQ Hub Setup"
echo "══════════════════════════════════════════"
echo "  Project root: $PROJECT_ROOT"
echo ""

# ─── 1. Check prerequisites ──────────────────────────────────────
echo "[1/7] Checking prerequisites..."
MISSING=()
for cmd in node npm docker python3; do
  if ! command -v "$cmd" &>/dev/null; then
    MISSING+=("$cmd")
  fi
done

if [[ ${#MISSING[@]} -gt 0 ]]; then
  echo "ERROR: Missing required commands: ${MISSING[*]}"
  echo ""
  echo "Install them first:"
  echo "  Node.js:  curl -fsSL https://deb.nodesource.com/setup_24.x | sudo -E bash - && sudo apt install -y nodejs"
  echo "  Docker:   https://docs.docker.com/engine/install/"
  echo "  Python:   sudo apt install python3 python3-pip python3-venv"
  exit 1
fi

NODE_VER=$(node --version | sed 's/v//' | cut -d. -f1)
if [[ "$NODE_VER" -lt 22 ]]; then
  echo "WARNING: Node.js $NODE_VER detected. Node 22+ recommended."
fi
echo "  node $(node --version), python3 $(python3 --version | cut -d' ' -f2), docker OK"

# ─── 2. Install OpenClaw Gateway ─────────────────────────────────
echo ""
if ! command -v openclaw &>/dev/null; then
  echo "[2/7] Installing OpenClaw..."
  npm install -g openclaw@latest
else
  echo "[2/7] OpenClaw already installed ($(openclaw --version 2>/dev/null || echo 'unknown'))"
fi

# ─── 3. Onboard OpenClaw ─────────────────────────────────────────
echo ""
if [[ ! -d "$OPENCLAW_HOME" ]]; then
  echo "[3/7] Running OpenClaw onboard..."
  echo "  This will ask for your AI provider and API key."
  echo "  Choose: Google / Gemini when prompted."
  echo ""
  openclaw onboard --install-daemon
else
  echo "[3/7] OpenClaw already onboarded ($OPENCLAW_HOME exists)"
fi

# ─── 4. Configure OpenClaw for TaskManager ────────────────────────
echo ""
echo "[4/7] Configuring OpenClaw..."

# Copy openclaw.json config
OPENCLAW_CONFIG="$OPENCLAW_HOME/openclaw.json"
if [[ -f "$OPENCLAW_CONFIG" ]]; then
  BACKUP="$OPENCLAW_CONFIG.backup.$(date +%Y%m%d_%H%M%S)"
  cp "$OPENCLAW_CONFIG" "$BACKUP"
  echo "  Backed up existing config to: $BACKUP"
fi
cp "$PROJECT_ROOT/openclaw/openclaw.json" "$OPENCLAW_CONFIG"
echo "  → openclaw.json installed"

# Symlink the taskmanager skill
mkdir -p "$OPENCLAW_WORKSPACE/skills"
SKILL_LINK="$OPENCLAW_WORKSPACE/skills/taskmanager"
if [[ -L "$SKILL_LINK" ]]; then
  rm "$SKILL_LINK"
fi
ln -s "$PROJECT_ROOT/openclaw/skills/taskmanager" "$SKILL_LINK"
echo "  → taskmanager skill linked"

# Copy agent identity files
for md_file in AGENTS.md SOUL.md; do
  SRC="$PROJECT_ROOT/openclaw/workspace/$md_file"
  DST="$OPENCLAW_WORKSPACE/$md_file"
  if [[ -f "$SRC" ]]; then
    cp "$SRC" "$DST"
    echo "  → $md_file copied"
  fi
done

# ─── 5. Create .env from example if needed ───────────────────────
echo ""
echo "[5/7] Setting up environment..."
if [[ ! -f "$PROJECT_ROOT/.env" ]]; then
  cp "$PROJECT_ROOT/.env.example" "$PROJECT_ROOT/.env"
  echo "  ⚠ Created .env from .env.example"
  echo "  ⚠ YOU MUST EDIT .env WITH REAL VALUES before starting!"
  echo ""
  echo "  Required values:"
  echo "    POSTGRES_PASSWORD  — Choose a secure password"
  echo "    GEMINI_API_KEY     — From https://aistudio.google.com/apikey"
  echo "    TASKS_BOT_TOKEN    — From @BotFather in Telegram"
  echo "    ALLOWED_USER_ID    — Your Telegram numeric user ID"
else
  echo "  .env already exists"
fi

# Source .env for subsequent steps
set -a
source "$PROJECT_ROOT/.env"
set +a

# ─── 6. Start PostgreSQL + apply schema ─────────────────────────
echo ""
echo "[6/7] Starting PostgreSQL..."
cd "$PROJECT_ROOT"
docker compose up -d postgres

echo "  Waiting for PostgreSQL to be healthy..."
RETRIES=30
until docker compose exec -T postgres pg_isready -U "${POSTGRES_USER:-hb_admin}" -d "${POSTGRES_DB:-heartbeat}" &>/dev/null; do
  RETRIES=$((RETRIES - 1))
  if [[ $RETRIES -le 0 ]]; then
    echo "  ERROR: PostgreSQL did not become healthy in time"
    exit 1
  fi
  sleep 1
done
echo "  PostgreSQL ready"

echo "  Applying schema..."
docker compose exec -T postgres psql -U "${POSTGRES_USER:-hb_admin}" -d "${POSTGRES_DB:-heartbeat}" \
  < "$PROJECT_ROOT/db/schema.sql" 2>/dev/null || true
echo "  Schema applied"

# ─── 7. Python virtual environment + dependencies ───────────────
echo ""
echo "[7/7] Setting up Python environment..."
if [[ ! -d "$PROJECT_ROOT/.venv" ]]; then
  python3 -m venv "$PROJECT_ROOT/.venv"
  echo "  Created .venv"
fi
source "$PROJECT_ROOT/.venv/bin/activate"
pip install --quiet -r "$PROJECT_ROOT/requirements.txt"
echo "  Dependencies installed"

# ─── Done ────────────────────────────────────────────────────────
echo ""
echo "══════════════════════════════════════════"
echo "  ✅ TaskManager setup complete!"
echo "══════════════════════════════════════════"
echo ""
echo "Next steps:"
echo ""
echo "  1. Edit .env with real values:"
echo "     nano $PROJECT_ROOT/.env"
echo ""
echo "  2. Edit OpenClaw config with your Telegram token and user ID:"
echo "     nano $OPENCLAW_CONFIG"
echo "     Replace CONFIGURE_ME values"
echo ""
echo "  3. Restart OpenClaw gateway:"
echo "     openclaw gateway restart"
echo ""
echo "  4. Send a DM to your Tasks bot in Telegram"
echo "     If using pairing: run 'openclaw pairing list telegram'"
echo "     then 'openclaw pairing approve telegram <CODE>'"
echo ""
echo "  5. Test from CLI:"
echo "     cd $PROJECT_ROOT && source .venv/bin/activate"
echo "     python3 scripts/cli.py add --title \"Test task\" --priority 3"
echo "     python3 scripts/cli.py list"
echo ""
