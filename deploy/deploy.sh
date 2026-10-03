#!/usr/bin/env bash
# =============================================================================
# deploy.sh — Provisiona y levanta el backend 3DARG en un VPS Ubuntu 24.04.
#
# Qué hace, en orden:
#   1. Instala Docker + plugin compose (si faltan).
#   2. Configura el firewall (UFW): SSH + 80 + 443.
#   3. Verifica que exista el .env de producción.
#   4. Prepara la carpeta media/ con permisos correctos.
#   5. Buildea y levanta el stack (db + web + caddy).
#   6. Instala los cron: backup diario de DB + media + reconciliación cada 15 min.
#
# Cómo usarlo (en el VPS, como root o con sudo):
#   git clone <URL-del-repo-3darg-backend> 3darg-backend
#   cd 3darg-backend
#   # crear/editar .env con valores de PRODUCCIÓN (ver checklist al final)
#   nano .env
#   cd deploy
#   sudo bash deploy.sh
#
# Idempotente: se puede correr varias veces sin romper nada.
# =============================================================================
set -euo pipefail

# --- Rutas ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
COMPOSE="docker compose -f ${SCRIPT_DIR}/docker-compose.prod.yml"
ENV_FILE="${REPO_DIR}/.env"

info()  { echo -e "\n\033[1;34m▶ $*\033[0m"; }
ok()    { echo -e "\033[1;32m✔ $*\033[0m"; }
fail()  { echo -e "\033[1;31mERROR: $*\033[0m" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || fail "Corré el script como root o con sudo."

# --- 1. Docker ---
if ! command -v docker >/dev/null 2>&1; then
  info "Instalando Docker..."
  curl -fsSL https://get.docker.com | sh
  ok "Docker instalado."
else
  ok "Docker ya está instalado."
fi

if ! docker compose version >/dev/null 2>&1; then
  fail "Falta el plugin 'docker compose'. Reinstalá Docker desde get.docker.com."
fi

# --- 2. Firewall ---
if command -v ufw >/dev/null 2>&1; then
  info "Configurando firewall (UFW): SSH, 80, 443..."
  ufw allow OpenSSH   >/dev/null 2>&1 || ufw allow 22/tcp >/dev/null 2>&1 || true
  ufw allow 80/tcp    >/dev/null 2>&1 || true
  ufw allow 443/tcp   >/dev/null 2>&1 || true
  ufw --force enable  >/dev/null 2>&1 || true
  ok "Firewall configurado."
else
  echo "  (ufw no está instalado; salteando firewall. Asegurate de abrir 80 y 443.)"
fi

# --- 3. .env ---
info "Verificando .env de producción..."
[ -f "${ENV_FILE}" ] || fail "No existe ${ENV_FILE}. Crealo con los valores de PRODUCCIÓN antes de desplegar."

# Chequeos mínimos de que no quedó config de desarrollo.
grep -q "^DJANGO_DEBUG=0" "${ENV_FILE}" || echo "  ⚠ DJANGO_DEBUG debería ser 0 en producción."
grep -q "^MP_NOTIFICATION_URL=https://" "${ENV_FILE}" || echo "  ⚠ MP_NOTIFICATION_URL debería apuntar a tu dominio https real."
grep -q "localhost" "${ENV_FILE}" && echo "  ⚠ El .env menciona 'localhost'; revisá que no quede config de dev."
ok ".env presente."

# --- 4. media/ con permisos ---
info "Preparando carpeta media/..."
mkdir -p "${REPO_DIR}/media"
# El contenedor web corre como 'appuser' (uid 1000). Sin esto no puede subir archivos.
chown -R 1000:1000 "${REPO_DIR}/media" || true
ok "media/ lista."

# --- 5. Build + up ---
info "Buildeando y levantando el stack (db + web + caddy)..."
cd "${SCRIPT_DIR}"
${COMPOSE} up -d --build
ok "Stack levantado."

echo ""
info "Estado de los contenedores:"
${COMPOSE} ps

# --- 6. Cron: backup diario (DB + media) + reconciliación cada 15 min ---
info "Instalando tareas cron (backup DB + backup media + reconciliación de pagos)..."
CRON_BACKUP="0 3 * * * ${SCRIPT_DIR}/backup-db.sh >> ${SCRIPT_DIR}/backup.log 2>&1"
CRON_BACKUP_MEDIA="10 3 * * * ${SCRIPT_DIR}/backup-media.sh >> ${SCRIPT_DIR}/backup.log 2>&1"
CRON_RECON="*/15 * * * * ${SCRIPT_DIR}/reconcile-cron.sh"

chmod +x "${SCRIPT_DIR}/backup-db.sh" "${SCRIPT_DIR}/backup-media.sh" "${SCRIPT_DIR}/reconcile-cron.sh" 2>/dev/null || true

# Reinstala las líneas sin duplicar (filtra las viejas por path del script).
( crontab -l 2>/dev/null | grep -v "${SCRIPT_DIR}/backup-db.sh" | grep -v "${SCRIPT_DIR}/backup-media.sh" | grep -v "${SCRIPT_DIR}/reconcile-cron.sh" ; \
  echo "${CRON_BACKUP}" ; echo "${CRON_BACKUP_MEDIA}" ; echo "${CRON_RECON}" ) | crontab -
ok "Cron instalado (backup DB 03:00, backup media 03:10, reconciliación cada 15 min)."

# --- Cierre ---
cat <<EOF

============================================================
  ✔ DEPLOY COMPLETO
============================================================

Pasos que faltan (manuales, una sola vez):

  1. DNS: apuntá api.tudominio.com (registro A) a la IP de este VPS.
     Caddy emite el certificado HTTPS solo cuando el dominio resuelve.

  2. Editá el dominio en ${SCRIPT_DIR}/Caddyfile
     (reemplazá api.3darg.com por el tuyo) y recargá:
       ${COMPOSE} restart caddy

  3. Crear el superusuario del admin:
       ${COMPOSE} exec web python manage.py createsuperuser

  4. En el panel de MercadoPago, registrá el webhook:
       https://api.tudominio.com/api/payments/mp/webhook/
     y poné el mismo MP_WEBHOOK_SECRET que está en el .env.

  5. En Vercel, seteá NEXT_PUBLIC_BACKEND_URL=https://api.tudominio.com/api

Comandos útiles:
  Ver logs:              ${COMPOSE} logs -f
  Reiniciar web:         ${COMPOSE} restart web
  Backup DB manual:      ${SCRIPT_DIR}/backup-db.sh
  Backup media manual:   ${SCRIPT_DIR}/backup-media.sh
============================================================
EOF
