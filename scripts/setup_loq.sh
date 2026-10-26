#!/usr/bin/env bash
set -euo pipefail

# ═══════════════════════════════════════════════════════════════
# BT-Core TaskManager — Setup (LOQ Hub / cualquier PC)
#
# Qué hace:
#   1. Verifica prerequisites (Docker, Python, Ollama)
#   2. Crea .env desde .env.example si no existe
#   3. Baja el modelo de embeddings (nomic-embed-text)
#   4. Levanta todo con docker compose up -d
#
# Uso:
#   git clone <repo> ~/Dev/TaskManager
#   cd ~/Dev/TaskManager && bash scripts/setup_loq.sh
#   # Editar .env con API keys reales si no lo hiciste
#   # Listo — docker compose ps
# ═══════════════════════════════════════════════════════════════

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo ""
echo -e "${GREEN}══════════════════════════════════════════${NC}"
echo -e "${GREEN}  BT-Core TaskManager — Setup${NC}"
echo -e "${GREEN}══════════════════════════════════════════${NC}"
echo "  Project: $PROJECT_ROOT"
echo ""

# ─── 1. Prerequisites ──────────────────────────────────────────
echo "[1/5] Checking prerequisites..."

MISSING=()
for cmd in docker python3 ollama; do
  if ! command -v "$cmd" &>/dev/null; then
    MISSING+=("$cmd")
  fi
done

if [[ ${#MISSING[@]} -gt 0 ]]; then
  echo -e "${RED}  ERROR: Missing: ${MISSING[*]}${NC}"
  echo ""
  echo "  Install:"
  echo "    Docker:  https://docs.docker.com/desktop/"
  echo "    Python:  sudo apt install python3 python3-pip"
  echo "    Ollama:  curl -fsSL https://ollama.com/install.sh | sh"
  exit 1
fi
echo -e "${GREEN}  docker, python3, ollama OK${NC}"

# ─── 2. .env setup ─────────────────────────────────────────────
echo ""
echo "[2/5] Setting up .env..."
if [[ ! -f "$PROJECT_ROOT/.env" ]]; then
  cp "$PROJECT_ROOT/.env.example" "$PROJECT_ROOT/.env"
  echo -e "${YELLOW}  Created .env from .env.example${NC}"
  echo -e "${YELLOW}  YOU MUST EDIT IT with real API keys:${NC}"
  echo ""
  echo -e "    ${YELLOW}nano $PROJECT_ROOT/.env${NC}"
  echo ""
  echo "    Required:"
  echo "      GEMINI_API_KEY       — https://aistudio.google.com/apikey"
  echo "      DEEPSEEK_API_KEY     — https://platform.deepseek.com/api_keys"
  echo "      BT_TASKS_BOT_TOKEN   — @BotFather in Telegram"
  echo "      BT_ALLOWED_USER_ID   — Your Telegram numeric user ID"
  echo ""
  echo "  Run this script again after editing .env"
  exit 0
else
  UNset=()
  for var in GEMINI_API_KEY DEEPSEEK_API_KEY BT_TASKS_BOT_TOKEN; do
    val=$(grep "^${var}=" "$PROJECT_ROOT/.env" 2>/dev/null | cut -d= -f2- | xargs)
    if [[ -z "$val" || "$val" == "your_"* ]]; then
      UNset+=("$var")
    fi
  done
  if [[ ${#UNset[@]} -gt 0 ]]; then
    echo -e "${YELLOW}  These vars still have placeholders: ${UNset[*]}${NC}"
    echo -e "${YELLOW}  Edit .env before continuing: nano $PROJECT_ROOT/.env${NC}"
    exit 1
  fi
  echo -e "${GREEN}  .env configured${NC}"
fi

# ─── 3. Ollama model ───────────────────────────────────────────
echo ""
echo "[3/5] Pulling Ollama embedding model..."
if ollama list 2>/dev/null | grep -q "nomic-embed-text"; then
  echo -e "${GREEN}  nomic-embed-text already cached${NC}"
else
  echo "  Downloading nomic-embed-text (137M)..."
  ollama pull nomic-embed-text
  echo -e "${GREEN}  Model ready${NC}"
fi

# ─── 4. Docker Compose ─────────────────────────────────────────
echo ""
echo "[4/5] Starting Docker services..."
cd "$PROJECT_ROOT"
docker compose up -d --build 2>&1

sleep 5
if docker compose ps 2>&1 | grep -q "healthy"; then
  echo -e "${GREEN}  PostgreSQL healthy${NC}"
fi

echo "  Applying DB schema..."
docker compose exec -T postgres psql -U hb_admin -d heartbeat \
  -f /docker-entrypoint-initdb.d/01_schema.sql 2>/dev/null || true
echo -e "${GREEN}  Schema applied${NC}"

# ─── 5. Verify ─────────────────────────────────────────────────
echo ""
echo "[5/5] Verifying..."
if docker compose ps 2>&1 | grep -q "taskmanager_bot.*Up"; then
  echo -e "${GREEN}  Bot running${NC}"
else
  echo -e "${RED}  Bot not running — check: docker compose logs bot${NC}"
fi

if docker compose ps 2>&1 | grep -q "taskmanager_heartbeat.*Up"; then
  echo -e "${GREEN}  Heartbeat running${NC}"
fi

# ─── Done ──────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}══════════════════════════════════════════${NC}"
echo -e "${GREEN}  Setup complete!${NC}"
echo -e "${GREEN}══════════════════════════════════════════${NC}"
echo ""
echo "  docker compose ps"
echo "  docker compose logs -f bot"
echo ""
echo "  Test in Telegram @bt_tasks_bot:"
echo "    /start"
echo "    /add Terminar informe de métricas Q2"
echo ""
echo "  Run tests:"
echo "    cd $PROJECT_ROOT && python3 tests/test_suite.py --quick"
echo ""
