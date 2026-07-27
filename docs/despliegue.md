# Poner Talanton en línea

## Por qué GitHub Pages no sirve

Pages publica **archivos estáticos**: HTML, CSS y JavaScript que el navegador
descarga tal cual. Talanton es un servidor Python que consulta una base de datos,
maneja sesiones, recibe el callback de OAuth de Google y guarda tokens cifrados. Nada
de eso puede pasar en un hosting estático.

Y aunque se pudiera: un repositorio de Pages es público. Ahí adentro habría datos de
contacto de terceros y la credencial que manda mail en nombre de la consultora.

Lo que sí se puede publicar en Pages es una **landing** que cuente qué hace Talanton,
con un link al CRM. Son dos cosas distintas y conviene que lo sigan siendo.

## La opción recomendada: un VPS con Docker

Para dos o tres personas, un servidor chico alcanza y sobra: **Hetzner CX22** (~€4/mes)
o **DigitalOcean** (~US$6/mes). Con Docker Compose queda todo —web, Postgres y la
corrida diaria de ingesta— en un solo `docker compose up`.

```bash
git clone <el-repo> talanton && cd talanton
cp .env.ejemplo .env
```

Generá los tres secretos y ponelos en `.env`:

```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # TALANTON_SECRET_KEY
python3 -c "import secrets; print(secrets.token_urlsafe(48))"                               # TALANTON_SESSION_SECRET
python3 -c "import secrets; print(secrets.token_urlsafe(24))"                               # POSTGRES_PASSWORD
```

```bash
docker compose up -d
docker compose exec web python -m talanton.cli usuario
```

Ese último comando crea el primer usuario. **Sin usuarios no entra nadie**, y no hay
registro abierto a propósito: los usuarios los crea quien administra el servidor.

### HTTPS

Poné [Caddy](https://caddyserver.com) adelante y resuelve el certificado solo:

```caddy
crm.talanton.com.ar {
    reverse_proxy localhost:8000
}
```

Con HTTPS andando, dejá `TALANTON_COOKIES_SEGURAS=1` para que la cookie de sesión no
viaje nunca en claro, y cargá `https://crm.talanton.com.ar/oauth/google/callback` como
URI de redireccionamiento en Google Cloud.

## Alternativas gestionadas

| Opción | Costo | La trampa |
|---|---|---|
| **Railway** | ~US$5/mes | Lo más rápido de arrancar. Postgres incluido y `TALANTON_DATABASE_URL` se inyecta sola. |
| **Render** | Gratis o US$7/mes | El plan gratis **apaga el servicio por inactividad**: la ingesta diaria no corre y se pierde histórico. Sirve para mostrarlo, no para operarlo. |
| **Fly.io** | ~US$5/mes | Bien si el equipo se reparte entre países. Postgres aparte. |
| **Google Cloud Run** | Por uso | Tiene sentido si ya están en Google Cloud por el OAuth. **El disco es efímero**: obliga a Cloud SQL, que arranca en ~US$10/mes. |

En todas, tres cosas no son negociables:

1. **Postgres, no SQLite.** Con disco efímero, un reinicio se lleva la base. Y la base
   *es* el producto: el histórico de días abiertos y reposteos no se puede reconstruir
   mirando los avisos de hoy.
2. **`TALANTON_SECRET_KEY` y `TALANTON_SESSION_SECRET` fijos.** Si el secreto de sesión
   cambia en cada deploy, se cierran todas las sesiones. Si cambia el de cifrado, los
   tokens de Gmail guardados dejan de poder descifrarse y hay que reconectar las casillas.
3. **Que la ingesta corra igual.** En un PaaS sin proceso de fondo, hay que usar el cron
   del proveedor apuntando a `python -m talanton.cli ingestar`.

## Base de datos

`TALANTON_DATABASE_URL` define el motor. Se aceptan las tres formas que entregan los
hostings —`postgres://`, `postgresql://` y `postgresql+psycopg://`— y se normalizan
solas.

- **Desarrollo:** SQLite en `data/talanton.db`. Es el default, no hay que configurar nada.
- **Producción:** Postgres. SQLite no soporta escrituras concurrentes de varios procesos
  y no tiene backups en línea.

### Migraciones

El esquema se versiona con Alembic. El contenedor corre `alembic upgrade head` antes de
levantar el servidor, así que desplegar deja la base al día sin pasos manuales.

```bash
# Después de cambiar models.py:
alembic revision --autogenerate -m "descripción del cambio"
alembic upgrade head
```

Hay un test (`test_no_quedan_cambios_de_modelo_sin_migrar`) que falla si alguien toca
los modelos y se olvida de generar la migración. Es a propósito: ese olvido se descubre
en el deploy, cuando ya es tarde.

### Backups

```bash
docker compose exec base pg_dump -U talanton talanton | gzip > backup-$(date +%F).sql.gz
```

Ponelo en el cron del servidor y mandá la copia afuera de la máquina. El día que se
pierda el volumen, lo que se pierde no es una app —se reinstala en diez minutos— sino
meses de histórico que no se pueden volver a juntar.

## Qué mirar después de desplegar

- `GET /salud` responde `{"ok": true}` — es lo que usa el healthcheck del contenedor.
- `docker compose logs -f ingesta` muestra la corrida diaria.
- Que el primer login funcione **antes** de compartir el link.
