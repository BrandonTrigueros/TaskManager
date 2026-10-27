#!/usr/bin/env bash
set -euo pipefail

# ═══════════════════════════════════════════════════════════════
# BT-Core TaskManager — Setup local (sin contenedores)
#
# Qué hace:
#   1. Verifica prerequisites (Python, PostgreSQL, Ollama)
#   2. Crea el .env desde .env.example si no existe
#   3. Crea el rol y la base si faltan, y aplica db/schema.sql
#   4. Baja el modelo de embeddings (nomic-embed-text)
#   5. Deja listo para: api/server.py + heartbeat + app Android
#
# Uso:
#   cd TaskManager && bash scripts/setup_loq.sh
#
# Prerrequisitos (Ubuntu/Debian, requieren sudo):
#   sudo apt install postgresql-16 postgresql-16-pgvector
# ═══════════════════════════════════════════════════════════════

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo ""
echo -e "${GREEN}══════════════════════════════════════════${NC}"
echo -e "${GREEN}  BT-Core TaskManager — Setup local${NC}"
echo -e "${GREEN}══════════════════════════════════════════${NC}"
echo "  Project: $PROJECT_ROOT"
echo ""

# ─── 1. Prerequisitos ───────────────────────────────────────────
echo "[1/4] Verificando prerequisitos..."

for cmd in python3 psql ollama; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo -e "${RED}  Falta: $cmd${NC}"
    case "$cmd" in
      psql)   echo "    sudo apt install postgresql-16 postgresql-16-pgvector" ;;
      ollama) echo "    https://ollama.com/download" ;;
      *)      echo "    sudo apt install $cmd" ;;
    esac
    exit 1
  fi
done

if ! pg_isready -q 2>/dev/null; then
  echo -e "${YELLOW}  PostgreSQL no responde. Intentando iniciarlo…${NC}"
  if command -v systemctl >/dev/null 2>&1; then
    sudo systemctl start postgresql
  elif command -v pg_ctlcluster >/dev/null 2>&1; then
    sudo pg_ctlcluster 16 main start
  else
    echo -e "${RED}  No sé cómo iniciar PostgreSQL en este sistema.${NC}"
    exit 1
  fi
fi

echo -e "${GREEN}  python3, psql, ollama OK${NC}"

# ─── 2. .env ────────────────────────────────────────────────────
echo "[2/4] Configuración..."
cd "$PROJECT_ROOT"
if [[ ! -f .env ]]; then
  cp .env.example .env
  echo -e "${YELLOW}  .env creado desde .env.example — editá las API keys${NC}"
else
  echo "  .env ya existe"
fi

set -a
# shellcheck disable=SC1091
source <(grep -E '^[A-Z_]+=' .env | sed 's/#.*//')
set +a

DB_USER="${POSTGRES_USER:-hb_admin}"
DB_NAME="${POSTGRES_DB:-heartbeat}"
DB_PASS="${POSTGRES_PASSWORD:-changeme}"

# ─── 3. Base de datos ───────────────────────────────────────────
echo "[3/4] Preparando PostgreSQL..."

sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='${DB_USER}'" \
  | grep -q 1 || \
  sudo -u postgres psql -c "CREATE ROLE ${DB_USER} LOGIN PASSWORD '${DB_PASS}'"

sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" \
  | grep -q 1 || \
  sudo -u postgres createdb -O "${DB_USER}" "${DB_NAME}"

sudo -u postgres psql -d "${DB_NAME}" -c "CREATE EXTENSION IF NOT EXISTS vector" >/dev/null
sudo -u postgres psql -d "${DB_NAME}" -c "CREATE EXTENSION IF NOT EXISTS pg_trgm" >/dev/null

PGPASSWORD="${DB_PASS}" psql -h localhost -U "${DB_USER}" -d "${DB_NAME}" \
  -v ON_ERROR_STOP=1 -q -f db/schema.sql
echo -e "${GREEN}  schema aplicado en ${DB_NAME}${NC}"

# ─── 4. Python + embeddings ─────────────────────────────────────
echo "[4/4] Entorno Python y embeddings..."
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
  echo "  .venv creado"
fi
.venv/bin/python -m pip install -q --upgrade pip
.venv/bin/python -m pip install -q -r requirements.txt

if ollama list 2>/dev/null | grep -q "nomic-embed-text"; then
  echo "  nomic-embed-text ya está"
else
  ollama pull nomic-embed-text
fi

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo ""
echo -e "${GREEN}══════════════════════════════════════════${NC}"
echo -e "${GREEN}  Listo${NC}"
echo -e "${GREEN}══════════════════════════════════════════${NC}"
echo ""
echo "  API para la app Android:"
echo "    source .venv/bin/activate"
echo "    python3 -m src.api.server"
echo ""
echo "  URL desde el emulador de Windows:  http://${IP:-<ip-wsl>}:${API_PORT:-8787}"
echo "  Ciclo del grafo:                   python3 -m src.ingest.heartbeat --action graph"
echo ""
