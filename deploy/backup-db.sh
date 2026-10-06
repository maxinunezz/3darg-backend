#!/usr/bin/env bash
# backup-db.sh — Backup diario de la base Postgres de producción.
#
# Hace un pg_dump comprimido dentro de deploy/backups/ y conserva los últimos
# 14 días. Lo instala deploy.sh como cron a las 03:00.
#
# IMPORTANTE: esto guarda el backup en el MISMO servidor. Para estar realmente
# cubierto ante una falla de disco, copiá periódicamente deploy/backups/ a otro
# lado (tu PC con scp, o un bucket S3/Backblaze). Un backup solo en el mismo
# disco no te salva si el disco muere.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE="docker compose -f ${SCRIPT_DIR}/docker-compose.prod.yml"
BACKUP_DIR="${SCRIPT_DIR}/backups"
RETENTION_DAYS=14

mkdir -p "${BACKUP_DIR}"
STAMP="$(date +%Y-%m-%d_%H%M)"
OUT="${BACKUP_DIR}/db_${STAMP}.sql.gz"

# pg_dump corre DENTRO del contenedor db, usando sus propias env (POSTGRES_*).
${COMPOSE} exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB"' | gzip > "${OUT}"

echo "$(date '+%Y-%m-%d %H:%M:%S') backup OK: ${OUT} ($(du -h "${OUT}" | cut -f1))"

# Rotación: borra backups más viejos que RETENTION_DAYS.
find "${BACKUP_DIR}" -name "db_*.sql.gz" -type f -mtime +${RETENTION_DAYS} -delete

# Restaurar (referencia):
#   gunzip -c db_FECHA.sql.gz | docker compose -f docker-compose.prod.yml exec -T db \
#     sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
