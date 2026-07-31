FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    # Fuera del HOME de root: el navegador se instala como root pero lo usa el
    # usuario `talanton`, y en `~/.cache` no podría leerlo.
    PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers

WORKDIR /app

# Las dependencias van primero: cambian mucho menos que el código, así la capa
# se reusa entre builds.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# El navegador de Scrapling. Bumeran y ZonaJobs arman el listado con JavaScript:
# sin navegador el HTML llega vacío y esos dos portales no devuelven nada.
# Suma peso a la imagen y minutos al build; Computrabajo anda sin esto, así que
# si el build se vuelve un problema, esta línea se puede sacar y la búsqueda
# sigue funcionando con un portal menos.
RUN (scrapling install && chmod -R a+rX /opt/pw-browsers) \
    || echo "Sin navegador: Bumeran y ZonaJobs quedan fuera"

COPY . .

# Usuario sin privilegios: si alguien logra ejecutar algo, que no sea root.
RUN useradd --create-home --uid 1000 talanton \
    && mkdir -p /app/data \
    && chown -R talanton:talanton /app
USER talanton

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os,urllib.request,sys; p=os.getenv('PORT','8000'); sys.exit(0 if urllib.request.urlopen(f'http://127.0.0.1:{p}/salud', timeout=3).status==200 else 1)"

# Migraciones y después el servidor. El puerto sale de $PORT cuando el hosting
# lo fija (Railway y casi todo PaaS), con 8000 como default.
CMD ["/bin/sh", "/app/scripts/arranque.sh"]
