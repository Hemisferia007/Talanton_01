# Conectar Gmail

Los mails salen desde la casilla real de cada persona del equipo, vía la API de Gmail
con OAuth2. Talanton pide **un solo permiso**: `gmail.send`. Puede mandar en tu nombre;
no puede leer tu casilla, ni tus contactos, ni tu Drive.

## 1. Crear el proyecto en Google Cloud

1. Entrá a [console.cloud.google.com](https://console.cloud.google.com) y creá un
   proyecto (o usá uno existente).
2. **APIs y servicios → Biblioteca** → buscá *Gmail API* → **Habilitar**.

## 2. Configurar la pantalla de consentimiento

**APIs y servicios → Pantalla de consentimiento de OAuth**.

| Si las casillas son… | Tipo de usuario | Verificación de Google |
|---|---|---|
| De un Workspace propio (`@talanton.com.ar`) | **Interno** | No hace falta |
| Cuentas `@gmail.com` sueltas | **Externo** | En modo *Prueba* alcanza con agregar cada casilla como usuario de prueba |

Elegí **Interno** si tenés Workspace: es el camino corto. Con **Externo** en modo
prueba también funciona, pero cada usuario tiene que estar cargado a mano en la lista
de usuarios de prueba, y el token se vence cada 7 días hasta que la app se publique.

En **Permisos** agregá `https://www.googleapis.com/auth/gmail.send`.

## 3. Crear las credenciales

**APIs y servicios → Credenciales → Crear credenciales → ID de cliente de OAuth**.

- Tipo: **Aplicación web**
- URI de redireccionamiento autorizado: exactamente la misma que vas a usar en
  `TALANTON_OAUTH_REDIRECT_URI`. En desarrollo:
  `http://127.0.0.1:8000/oauth/google/callback`

Google te da un **Client ID** y un **Client Secret**.

## 4. Configurar Talanton

```bash
export TALANTON_GOOGLE_CLIENT_ID="...apps.googleusercontent.com"
export TALANTON_GOOGLE_CLIENT_SECRET="..."
export TALANTON_OAUTH_REDIRECT_URI="http://127.0.0.1:8000/oauth/google/callback"

# Clave para cifrar los refresh tokens. Si no la definís se genera una en
# data/secret.key con permisos 600 — sirve para una sola máquina.
export TALANTON_SECRET_KEY="$(python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
```

Levantá la web, entrá a **Mi empresa → Casillas para enviar → Conectar una cuenta de
Gmail** y autorizá. Cada persona del equipo conecta la suya.

## Cómo se guardan las credenciales

- El **refresh token** (la credencial de larga vida) se guarda **cifrado con Fernet**
  en la base. La clave nunca va a la base.
- El **access token** dura una hora y se renueva solo antes de cada envío.
- **Desconectar** revoca el token contra Google y lo borra de nuestro lado. Los mails
  ya enviados se conservan: son el historial del lead.

Si perdés `TALANTON_SECRET_KEY` (o `data/secret.key`), los tokens guardados dejan de
poder descifrarse y hay que reconectar las cuentas. No se pierde nada más.

## Límites de envío

Gmail corta en **500 mails/día** en cuentas gratuitas y **2000/día** en Workspace.
Talanton aplica su propio tope, más conservador, en `TALANTON_LIMITE_ENVIOS_DIARIOS`
(40 por defecto).

Ese número bajo es a propósito. Mandar cientos de mails fríos desde el dominio con el
que la consultora también factura y habla con clientes es la forma más rápida de que
todo el dominio termine en spam — incluidos los mails que sí importan. Si en algún
momento el volumen crece, la salida es un **dominio de envío aparte**
(`talanton-contacto.com.ar`) con su propio SPF, DKIM y DMARC, calentado de a poco. No
subir este número.

## Qué queda afuera y por qué

**Leer las respuestas automáticamente** necesita `gmail.readonly`, que Google clasifica
como *scope restringido*: con la app en modo Externo exige una verificación anual con
auditoría de seguridad. Con Workspace en modo **Interno** no hace falta, y ahí sí vale
la pena sumarlo.

Mientras tanto, las respuestas se cargan a mano desde el hilo del lead
(*Registrar una respuesta que llegó*). Se guardan con la misma forma que tendrían si
las trajera la API, así que cuando se sume el permiso cambia de dónde salen los datos,
no cómo se ven.
