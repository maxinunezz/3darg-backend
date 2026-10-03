#!/usr/bin/env bash
# backup-media.sh — Backup diario de las imágenes de producto (media/) en producción.
#
# Comprime ../media en un .tar.gz dentro de deploy/backups/ (mismo directorio
# que usa backup-db.sh) y conserva los últimos 14 días. Lo instala deploy.sh
# como cron a las 03:10 (10 min después del backup de la DB, para no pisarse).
#
# IMPORTANTE: esto guarda el backup en el MISMO servidor, igual que backup-db.sh.
# Para estar realmente cubierto ante una falla de disco, copiá periódicamente
# deploy/backups/ a otro lado (tu PC con scp, o un bucket S3/Backblaze). Un
# backup solo en el mismo disco no te salva si el disco muere.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MEDIA_DIR="${SCRIPT_DIR}/../media"
BACKUP_DIR="${SCRIPT_DIR}/backups"
RETENTION_DAYS=14

mkdir -p "${BACKUP_DIR}"

if [ ! -d "${MEDIA_DIR}" ] || [ -z "$(ls -A "${MEDIA_DIR}" 2>/dev/null)" ]; then
  echo "$(date '+%Y-%m-%d %H:%M:%S') backup media: nada que respaldar (${MEDIA_DIR} vacío o no existe)."
  exit 0
fi

STAMP="$(date +%Y-%m-%d_%H%M)"
OUT="${BACKUP_DIR}/media_${STAMP}.tar.gz"

# tar corre directo sobre el bind mount del host — media/ no vive dentro de
# ningún contenedor (a diferencia de la DB), así que no hace falta docker exec.
tar -czf "${OUT}" -C "${SCRIPT_DIR}/.." media

echo "$(date '+%Y-%m-%d %H:%M:%S') backup media OK: ${OUT} ($(du -h "${OUT}" | cut -f1))"

# Rotación: borra backups más viejos que RETENTION_DAYS.
find "${BACKUP_DIR}" -name "media_*.tar.gz" -type f -mtime +${RETENTION_DAYS} -delete

# Restaurar (referencia):
#   tar -xzf media_FECHA.tar.gz -C 3darg-backend/deploy/..
#   (extrae de nuevo la carpeta media/ en la raíz del repo backend)
