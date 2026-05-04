#!/bin/bash

# set -e: Detiene el script si algún comando falla.
set -e

echo "--- 1. Esperando a que la base de datos esté lista ---"
# Intentamos conectarnos al host 'db' (nombre del servicio en docker-compose) 
# en el puerto 5432. Repetimos hasta que responda.
until (echo > /dev/tcp/db/5432) >/dev/null 2>&1; do
  echo "Postgres no responde todavía... esperando 1 segundo."
  sleep 1
done

echo "--- 2. Base de datos conectada. Instalando dependencias ---"
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

echo "--- 3. Aplicando migraciones de base de datos ---"
python manage.py migrate

echo "--- 4. Iniciando el servidor de desarrollo ---"
# 0.0.0.0 es obligatorio para que Docker pueda mapear el puerto hacia afuera
python manage.py runserver 0.0.0.0:8000