#!/usr/bin/env bash
# reconcile-cron.sh — Red de seguridad de pagos en PRODUCCIÓN (VPS).
#
# Corre cada 15 min (lo instala deploy.sh). Reconcilia órdenes PENDING contra
# MercadoPago para cubrir pagos offline (efectivo/Rapipago/transferencia) que
# se acreditan tarde y sin que el cliente vuelva a la página de éxito, o casos
# en que el webhook no llegó.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE="docker compose -f ${SCRIPT_DIR}/docker-compose.prod.yml"
LOG="${SCRIPT_DIR}/reconcile.log"

# Rotación simple: si el log pasa de ~5 MB, conservamos solo el final.
if [ -f "${LOG}" ] && [ "$(stat -c%s "${LOG}")" -gt 5242880 ]; then
  tail -n 500 "${LOG}" > "${LOG}.tmp" && mv "${LOG}.tmp" "${LOG}"
fi

echo "===== $(date '+%Y-%m-%d %H:%M:%S') =====" >> "${LOG}"
${COMPOSE} exec -T web python manage.py reconcile_pending_payments >> "${LOG}" 2>&1
echo "" >> "${LOG}"
