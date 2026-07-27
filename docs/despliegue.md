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

## Railway, paso a paso

Railway detecta el `Dockerfile` y usa `railway.json` para el health check. Son tres
servicios en el mismo proyecto.

### 1. Postgres primero

**New → Database → Add PostgreSQL**. Railway lo provisiona con volumen persistente y
expone `DATABASE_URL`. Creá la base **antes** que la app: así ya podés referenciarla
cuando cargues las variables.

### 2. El servicio web

**New → GitHub Repo** → elegí este repositorio y la rama.

En **Variables** del servicio:

```
TALANTON_DATABASE_URL=${{Postgres.DATABASE_URL}}
TALANTON_SESSION_SECRET=<generado>
TALANTON_SECRET_KEY=<generado>
TALANTON_COOKIES_SEGURAS=1
TALANTON_ADMIN_EMAIL=vos@talanton.com.ar
TALANTON_ADMIN_PASSWORD=<una contraseña larga>
```

La sintaxis `${{Postgres.DATABASE_URL}}` es de Railway: referencia la variable del
servicio de Postgres, así no hay que copiar credenciales a mano. Railway la entrega
como `postgresql://…` y la app la normaliza sola.

Generá los dos secretos:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"                                # SESSION_SECRET
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"   # SECRET_KEY
```

**Los dos tienen que quedar fijos.** Si el de sesión cambia, se cierran todas las
sesiones; si cambia el de cifrado, los tokens de Gmail guardados dejan de poder
descifrarse y hay que reconectar las casillas. Por eso la app **se niega a arrancar**
si `TALANTON_COOKIES_SEGURAS=1` y alguno falta: es un error visible en el deploy en
vez de un problema silencioso semanas después.

En **Settings → Networking → Generate Domain** obtenés la URL pública, con HTTPS
incluido.

### 3. El primer usuario

`TALANTON_ADMIN_EMAIL` y `TALANTON_ADMIN_PASSWORD` crean el primer usuario al arrancar,
**sólo si la tabla de usuarios está vacía**. Es el camino práctico en un PaaS donde no
hay consola a mano.

Apenas puedas entrar, **borrá esas dos variables** de Railway. Ya no hacen nada —con
usuarios existentes se ignoran— pero no tiene sentido dejar una contraseña dando vueltas
en el panel. De ahí en más los usuarios se crean desde la consola:

```bash
railway run --service web python -m talanton.cli usuario
```

### 4. La ingesta diaria

**New → GitHub Repo**, el mismo repositorio, y en ese segundo servicio:

- **Settings → Deploy → Custom Start Command**: `python -m talanton.cli ingestar`
- **Settings → Cron Schedule**: `0 9 * * *` (09:00 UTC ≈ 06:00 en Argentina)
- **Variables**: `TALANTON_DATABASE_URL=${{Postgres.DATABASE_URL}}` y
  `TALANTON_SECRET_KEY=<el mismo>`

Un servicio con cron en Railway corre, termina y se apaga: por eso acá va el comando de
ingesta directo y no el `scripts/ingesta-diaria.sh`, que es el bucle para VPS.

**Este servicio no es opcional.** Cada día que no corre es histórico que no se recupera,
y el histórico es lo único que ningún competidor puede improvisar.

### 5. Gmail

Con el dominio de Railway andando, cargá en Google Cloud la URI de redireccionamiento:

```
https://<tu-app>.up.railway.app/oauth/google/callback
```

y en Railway:

```
TALANTON_GOOGLE_CLIENT_ID=…
TALANTON_GOOGLE_CLIENT_SECRET=…
TALANTON_OAUTH_REDIRECT_URI=https://<tu-app>.up.railway.app/oauth/google/callback
```

Tiene que coincidir **exactamente** con lo cargado en Google, incluido el `https://` y
sin barra final. Es el error más común del alta.

### Costo y backups

Con el plan Hobby (US$5/mes de crédito) entra cómodo: la web y el Postgres consumen poco
y el servicio de cron sólo corre unos minutos por día.

Railway hace backups del volumen, pero conviene tener una copia propia afuera:

```bash
railway run --service Postgres pg_dump "$DATABASE_URL" | gzip > backup-$(date +%F).sql.gz
```

## Alternativa: un VPS con Docker

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

## Otras alternativas gestionadas

| Opción | Costo | La trampa |
|---|---|---|
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
