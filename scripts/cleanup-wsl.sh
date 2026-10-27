#!/usr/bin/env bash
# Elimina PostgreSQL y Ollama de WSL. Ejecutar desde WSL:  bash cleanup-wsl.sh
set -e
echo "== Deteniendo servicios =="
sudo systemctl stop postgresql 2>/dev/null || true
sudo systemctl stop ollama 2>/dev/null || true

echo "== Desinstalando PostgreSQL =="
sudo apt-get remove --purge -y postgresql-16 postgresql-16-pgvector \
    postgresql-client-16 postgresql-client-common postgresql-common
sudo rm -rf /var/lib/postgresql /etc/postgresql /var/log/postgresql
sudo apt-get autoremove -y

echo "== Desinstalando Ollama =="
sudo rm -f /usr/local/bin/ollama
sudo rm -rf /usr/share/ollama /usr/local/lib/ollama
sudo userdel ollama 2>/dev/null || true

echo "== Limpiando caché de pip =="
rm -rf ~/.cache/pip ~/.cache/huggingface

echo "Hecho. Verificar con:  dpkg -l | grep postgresql ; which ollama"
