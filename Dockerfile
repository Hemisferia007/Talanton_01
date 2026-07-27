FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Las dependencias van primero: cambian mucho menos que el código, así la capa
# se reusa entre builds.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Usuario sin privilegios: si alguien logra ejecutar algo, que no sea root.
RUN useradd --create-home --uid 1000 talanton \
    && mkdir -p /app/data \
    && chown -R talanton:talanton /app
USER talanton

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/salud', timeout=3).status==200 else 1)"

# Las migraciones corren antes de levantar: el contenedor puede arrancar contra
# una base vieja y tiene que dejarla al día solo.
CMD ["sh", "-c", "alembic upgrade head && uvicorn talanton.web.app:app --host 0.0.0.0 --port 8000"]
