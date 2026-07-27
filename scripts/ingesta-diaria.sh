#!/bin/sh
# Corre la ingesta una vez por día a la hora indicada en HORA_INGESTA (UTC).
#
# Se usa un bucle en vez de cron para que los logs salgan por stdout del
# contenedor, como el resto de los servicios, y no haya que entrar a buscarlos.
set -eu

HORA="${HORA_INGESTA:-06}"
echo "[ingesta] esperando a las ${HORA}:00 UTC de cada día"

while true; do
  AHORA="$(date -u +%H)"
  if [ "$AHORA" = "$HORA" ]; then
    echo "[ingesta] arrancando corrida — $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    # Una fuente caída no debe tumbar el servicio: el runner ya aísla los
    # errores por conector, y acá se absorbe cualquier resto.
    python -m talanton.cli ingestar || echo "[ingesta] la corrida terminó con errores"
    # Dormir más de una hora evita repetir la corrida dentro de la misma hora.
    sleep 3660
  else
    sleep 300
  fi
done
