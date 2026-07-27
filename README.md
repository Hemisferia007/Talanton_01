# Talanton

Motor de generación de leads y mini-CRM para una consultora de RRHH especializada en
selección. Mercado: **Argentina y LatAm**.

Detecta empresas con **búsquedas abiertas que no logran cerrar** —el momento exacto en
que necesitan una consultora— y las prioriza con un score explicable.

## La idea en una línea

El activo no es el scraper, es la **serie histórica**: saber que un aviso lleva 92 días
publicado y ya se republicó dos veces sólo es posible si venís mirando desde antes.
Por eso el sistema empieza a correr antes de estar terminado.

Estrategia completa, señales y roadmap: [`docs/estrategia-leads.md`](docs/estrategia-leads.md).

## Arranque rápido

```bash
pip install -r requirements.txt
python -m talanton.cli usuario   # crea el usuario para entrar
python -m talanton.cli seed      # datos de demo (empresas ficticias AR/LatAm)
python -m talanton.cli servir    # http://127.0.0.1:8000
```

No hay registro abierto: los usuarios se crean por consola. La app maneja datos de
contacto de terceros y credenciales de Gmail, así que **todas las rutas exigen sesión**
salvo el login, lo estático y el health check.

Para la ingesta real hace falta además el navegador de Scrapling:

```bash
scrapling install
python -m talanton.cli ingestar  # lee fuentes.json
```

## Qué hay hoy

**Mini-CRM web** (FastAPI + Jinja2, sin build step):

| Pantalla | Qué muestra |
|---|---|
| **Panel** | Métricas, leads nuevos por encima del umbral y búsquedas que se les están estirando |
| **Tablero** | Kanban con drag & drop: Nuevo → Contactado → En conversación → Reunión → Propuesta → Ganado/Perdido |
| **Leads** | Listado filtrable por estado, país, score y texto, con la señal principal de cada uno |
| **Avisos** | Todas las vacantes detectadas, ordenadas por días abiertas |
| **Mi empresa** | Datos de la consultora, el ICP que alimenta el eje de *fit*, y las casillas de Gmail conectadas |

Dentro de cada lead, el intercambio con la empresa se ve como un **hilo de chat**:
lo que mandamos de un lado, lo que contestaron del otro, en orden. Los mails se
escriben desde una ventana de redacción que abre ya con el borrador armado a partir
de la señal concreta del lead.

La interfaz está construida sobre tokens: una escala de espacio base 4, cinco tamaños
tipográficos y una rampa de neutros sin `#000` ni `#fff`. Los bordes estructuran y las
sombras sólo aparecen cuando algo realmente flota (una tarjeta arrastrándose). Todo
control tiene `:focus-visible`, y hay un `prefers-reduced-motion` que apaga las
transiciones sin romper los estados.

**Accesibilidad** (WCAG 2.1 AA como piso, verificado por tests):

- Todo control de formulario tiene `<label>` asociado — un placeholder no es etiqueta.
- El kanban se opera **con teclado**: además del drag & drop, cada tarjeta tiene un
  selector de estado que pega contra el mismo endpoint, con región `role="status"` que
  anuncia el resultado.
- Texto y bordes de controles verificados contra 4.5:1 y 3:1 respectivamente.
- Enlace para saltar al contenido, `aria-current` en la navegación, tablas con `scope`
  en los encabezados, y el estado nunca se comunica sólo por color.

**Motor de scoring** con cuatro ejes ponderados —urgencia 40%, fit ICP 25%,
accesibilidad 20%, capacidad de pago 15%— donde cada punto sumado deja una frase que lo
justifica, más un **gancho** listo para abrir la conversación:

> Vi que hace 92 días están buscando Jefe de Depósito en Mendoza. Ya la republicaron, así
> que imagino que no está siendo fácil.

**Envío por Gmail** (OAuth2, permiso `gmail.send` únicamente — Talanton puede mandar
en tu nombre, no leer tu casilla). Alta paso a paso en [`docs/gmail.md`](docs/gmail.md).

- Los refresh tokens se guardan **cifrados** en la base; la clave nunca va a la base.
- Cinco plantillas que se eligen solas según la señal del lead: búsqueda estirada,
  volumen, rotación, seguimiento y presentación. El mail abre por algo que la empresa
  reconoce como cierto sobre sí misma, no por quiénes somos.
- Enviar registra la actividad, marca la fecha de contacto y mueve el lead a
  *Contactado*. Registrar una respuesta lo mueve a *En conversación*.
- Tope diario conservador (40 por cuenta) para no quemar la reputación del dominio.

**Ingesta** en tres carriles, del más barato al más caro:

1. **APIs de ATS** (`talanton/ingest/ats.py`) — Greenhouse, Lever. JSON público, estable,
   con fecha de publicación real y sin anti-bot.
2. **JSON-LD `schema.org/JobPosting`** (`talanton/ingest/jsonld.py`) — un solo parser
   sirve para cientos de páginas de carrera.
3. **Portales HTML** — vía Scrapling, con selectores adaptativos y sesiones stealth
   sólo donde hace falta.

Las fuentes se declaran en [`fuentes.json`](fuentes.json), y hay un **descubridor**
que lo arma solo: le pasás nombres de empresas y sondea las cinco plataformas de ATS
más usadas más la página de carrera, quedándose con las que responden de verdad.

```bash
cp empresas.ejemplo.txt empresas.txt   # y poné tus objetivos reales
python -m talanton.cli descubrir       # escribe fuentes.json
python -m talanton.cli ingestar
```

**Enriquecimiento**: `python -m talanton.cli enriquecer` busca emails en los avisos ya
cargados, distingue buzones de área (`rrhh@`) de personas, verifica que el dominio
resuelva, y marca al decisor. En el lead, cuando todavía no hay decisor, la ficha dice
**qué cargo buscar** según el tamaño de la empresa — en una PyME decide el dueño, en
una de 500 el líder de selección.

No se compran bases ni se scrapea LinkedIn: los emails salen de lo que la empresa
publicó para que la contacten por trabajo, con `fuente_url` guardada para poder
auditarlos y borrarlos a pedido.

**Visibilidad de la ingesta**: cada corrida queda registrada, y el panel avisa si la
última no trajo nada o si fallaron fuentes. Sin eso, una configuración rota se ve
exactamente igual que un día tranquilo — y el histórico que no se juntó no se recupera.

## Cómo se sostiene el histórico

- Las vacantes **nunca se borran**: cuando desaparecen de la fuente se marcan cerradas
  con fecha. Modelar el cierre importa tanto como la apertura, si no el sistema termina
  llamando a empresas que ya contrataron.
- `primera_vez_vista` no se pisa nunca. Es lo que permite calcular días abiertos.
- Si una vacante cerrada reaparece, cuenta como **reposteo**: reintentaron y volvieron a
  fallar.
- Los roles se normalizan (`Programador Full-Stack Ssr` ≡ `Full Stack Developer Senior`),
  sin lo cual las señales de reposteo y recurrencia directamente no existen.

## Poner esto en línea

**Railway** (recomendado): tres servicios —Postgres, web y la ingesta diaria por cron—
desde este mismo repo. El paso a paso está en [`docs/despliegue.md`](docs/despliegue.md).

**Con Docker**, en un VPS o local:

```bash
cp .env.ejemplo .env    # y completar los tres secretos
docker compose up -d
docker compose exec web python -m talanton.cli usuario
```

**GitHub Pages no sirve para esto**: publica archivos estáticos, y Talanton es un
servidor con base de datos, sesiones y callback de OAuth. Además el repo de Pages es
público, y acá hay datos de contacto y credenciales de Gmail.

**Postgres, no SQLite, en cualquier despliegue.** Con disco efímero un reinicio se lleva
la base, y la base *es* el producto: el histórico de días abiertos y reposteos no se
reconstruye mirando los avisos de hoy.

## Estructura

```
talanton/
  models.py       Empresa, Vacante, Lead, Contacto, Actividad, PerfilConsultora
  normalize.py    Dedupe de empresas, normalización de roles, detección de seniority
  scoring.py      Los cuatro ejes y sus razones
  services.py     Upserts, cierre de vacantes, kanban, consultas
  ingest/         Conectores, corrida diaria y descubridor de fuentes
  enriquecer/     Contactos desde avisos, verificación de dominio y regla de decisor
  correo/         Gmail: OAuth, cifrado de tokens, plantillas y envío
  auth.py         Hash scrypt, login, sesiones
  web/            FastAPI + templates + kanban + ventana de redacción
  seed.py         Datos de demo
  cli.py          init | usuario | descubrir | seed | ingestar | enriquecer | recalcular | servir
migraciones/      Alembic
tests/            185 tests: dominio, web, accesibilidad, correo, auth, ingesta y enriquecimiento
docs/             Estrategia, alta de Gmail y despliegue
.claude/skills/   Skills de craft visual y accesibilidad usadas para revisar el front
```

## Tests

```bash
python -m pytest -q
```

## Pendiente (ver roadmap)

Alertas diarias por mail, y el loop de feedback comercial que recalibra los pesos del
scoring con resultados reales — ese último recién tiene sentido con unos meses de
histórico y leads cerrados.
