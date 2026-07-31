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

¿Recién arrancás? De cero a la primera tanda de mails, sin consola:
[`docs/primera-busqueda.md`](docs/primera-busqueda.md).

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

Cinco destinos al frente —el camino de todos los días— y el resto en el menú «Más»,
que son pantallas de alta y configuración que se usan una vez.

| Pantalla | Qué muestra |
|---|---|
| **Panel** | Métricas, leads nuevos por encima del umbral y búsquedas que se les están estirando |
| **Leads** | Listado filtrable por estado, país, score y texto, con la señal principal de cada uno |
| **Tablero** | Kanban con drag & drop: Nuevo → Contactado → En conversación → Reunión → Propuesta → Ganado/Perdido |
| **Avisos** | Todas las vacantes detectadas, ordenadas por días abiertas |
| **Cargar empresas** | El arranque entero en un paso: pegás una lista y salen leads puntuados |
| *Más →* **Mi empresa** | Datos de la consultora, el ICP que alimenta el eje de *fit*, y las casillas de Gmail |
| *Más →* **Fuentes** | Empresas a vigilar y de dónde se leen sus avisos, con el resultado de cada corrida |
| *Más →* **Importar** | Pegás cualquier lista (Excel, Apollo, Hunter, contactos viejos) sin correr la cadena entera |
| *Más →* **Buscar** | Empresas y decisores desde Apollo, filtrando por cargo, país, industria y tamaño |
| *Más →* **Señales** | Cola de revisión de rondas de inversión y expansiones detectadas en posts |
| Dentro del lead | **Asistente**: «¿conviene contactarlo?» y borradores que contestan el hilo |

**Cargar empresas** es el camino corto y el único que hace falta el primer día.
Encadena lo que antes eran cuatro pantallas en el orden correcto —importar, dejar
vigilando, sondear dónde publica cada una, traer los avisos, sacar contactos y
puntuar— y cuenta en castellano qué pasó en cada tramo. Viene con una lista de 45
empresas de IT argentinas cargada, para que el histórico empiece a correr hoy y no
la semana que viene.

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

**Asistente** (opcional, requiere clave de Anthropic — ver [`docs/asistente.md`](docs/asistente.md)):
dentro de la ficha del lead, un botón que lee el texto de los avisos, lo que la
empresa contestó y las notas del comercial, y responde **si conviene contactarlo**
con sus motivos y sus reparos. Y en la ventana de redacción, un borrador que
contesta lo que la empresa efectivamente dijo, que ninguna plantilla puede hacer.

No toca el score: el score sale de los cuatro ejes y es lo que el comercial le
puede explicar al cliente. El asistente lee lo que los ejes no miran —el texto— y
queda al lado, fechado. Su respuesta más valiosa suele ser *«no conviene»*.

**Buscar decisores** (opcional, requiere plan pago de Apollo — ver
[`docs/apollo.md`](docs/apollo.md)): filtrás por cargo, país, industria y tamaño y
traés las empresas con la persona que firma. Buscar es gratis y los emails vienen
tapados; destaparlos consume créditos y es un botón aparte, para poder ajustar los
filtros sin gastar.

Sin plan pago no hace falta: la exportación CSV de Apollo entra por **Importar** y
termina idéntica en la base. Los encabezados que rompen un importador genérico
—`First Name`+`Last Name`, `# Employees`, `City` contra `Company City`— ya están
contemplados.

Apollo dice **quién** decide; los avisos dicen **cuándo** conviene escribirle. Lo que
rinde es usar los dos: traés las empresas de tu rubro, las dejás en Fuentes, y cuando
a una se le estira una búsqueda el score la sube sola con el decisor ya cargado.

**Ingesta** en tres carriles, del más barato al más caro:

1. **APIs de ATS** (`talanton/ingest/ats.py`) — Greenhouse, Lever. JSON público, estable,
   con fecha de publicación real y sin anti-bot.
2. **JSON-LD `schema.org/JobPosting`** (`talanton/ingest/jsonld.py`) — un solo parser
   sirve para cientos de páginas de carrera.
3. **Portales HTML** — vía Scrapling, con selectores adaptativos y sesiones stealth
   sólo donde hace falta.
4. **LinkedIn Jobs vía Apify** (`talanton/ingest/apify.py`) — la única fuente que además
   **descubre empresas nuevas**: el resto vigila las que ya cargaste, una búsqueda por
   rubro y zona trae las que todavía no conocías. Tiene contrapartidas de ToS que
   conviene leer antes: [`docs/linkedin.md`](docs/linkedin.md).

Las fuentes **se administran desde la pantalla Fuentes**, sin tocar archivos ni
consola: cargás el nombre de una empresa y Talanton sondea Greenhouse, Lever, Ashby,
Recruitee y Workable, y si no encuentra board busca JSON-LD en su página de trabajo.
Lo que queda pendiente lo resuelve la corrida diaria.

`fuentes.json` quedó sólo como semilla opcional del primer arranque, y se reparte
**vacío** a propósito: sembrar boards sin verificar deja la corrida diaria en rojo
desde el día uno, y una alarma que siempre suena deja de ser una alarma.

**Conseguir los contactos** —el paso sin el cual el score no sirve para nada, porque
no hay a quién escribirle— tiene tres vías, de la más barata a la más cara:
[`docs/contactos.md`](docs/contactos.md).

1. **Hunter.io** (`talanton/enriquecer/hunter.py`) — busca la persona de RRHH por el
   dominio de la empresa. **Su API anda en el plan gratuito**: 25 búsquedas al mes.
   Un botón en *Leads* resuelve las 10 empresas de mayor score que todavía no tienen
   mail; las que ya tienen se saltean. Descarta lo de baja confianza —un rebote cuesta
   reputación de dominio— y nunca marca un `rrhh@` como decisor.
2. **Apollo por la web** + *Importar*, cuando hace falta volumen.
3. **Del propio aviso**, que es la fuente de mejor calidad legal que existe.

**Enriquecimiento**: `python -m talanton.cli enriquecer` busca emails en los avisos ya
cargados, distingue buzones de área (`rrhh@`) de personas, verifica que el dominio
resuelva, y marca al decisor. En el lead, cuando todavía no hay decisor, la ficha dice
**qué cargo buscar** según el tamaño de la empresa — en una PyME decide el dueño, en
una de 500 el líder de selección.

**Procedencia siempre guardada.** Cada contacto lleva su `fuente_url` —el aviso del
que salió, el LinkedIn de la persona, o `apollo.io:<id>`— para poder auditarlo y
borrarlo a pedido. Sin eso, un dato de contacto de un tercero no se puede defender
bajo la Ley 25.326.

No se compran bases sueltas por CSV: no se sabe de dónde salieron y no hay a quién
reclamarle. Apollo es distinto —proveedor identificable, con términos de uso y bajas
procesadas—, y por eso está integrado; el razonamiento completo está en
[`docs/apollo.md`](docs/apollo.md). De LinkedIn se leen **avisos, nunca perfiles**:
la distinción y sus motivos están en [`docs/linkedin.md`](docs/linkedin.md).

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
- **Los buzones de CV no son búsquedas.** «General Applications», «Talent Pool»,
  «Candidatura espontánea»: nunca cierran, así que acumulan días para siempre y se
  trepan solos al tope del ranking justo por no ser lo que buscamos. Se muestran
  marcados pero no cuentan como búsqueda abierta ni pesan en el score.
- **Las consultoras de selección y las staffing no son clientes, son competencia.**
  Se detectan por el nombre o por publicar más búsquedas simultáneas de las que
  ninguna empresa sostiene —una de 200 personas no tiene 800 vacantes propias— y
  quedan al fondo del ranking en vez de arriba. Una consultora de *software* no
  entra en esa bolsa: contrata para sí y es cliente.
- **El reclutamiento interno se detecta solo**: si la empresa busca un reclutador
  para su propio equipo, si tiene gente de RRHH entre sus contactos, o si pasa de
  250 empleados. Pesa 40 de 100 en accesibilidad, así que darlo por «no» sin mirar
  regalaba el eje entero. El motivo se muestra: el comercial tiene que poder
  explicar por qué un lead quedó abajo.
- Los roles se normalizan (`Programador Full-Stack Ssr` ≡ `Full Stack Developer Senior`,
  `Ingeniero DevOps` ≡ `DevOps Engineer`), sin lo cual las señales de reposteo y
  recurrencia directamente no existen. El vocabulario de IT está cubierto en los dos
  idiomas, incluida la escalera técnica: `Tech Lead` pesa como jefatura, `Staff` y
  `Principal` como senior.

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
  enriquecer/     Contactos desde avisos y desde Hunter, verificación y regla de decisor
  correo/         Gmail: OAuth, cifrado de tokens, plantillas y envío
  apollo/         Búsqueda de empresas y decisores, y su importación
  arranque.py     El primer arranque encadenado, en un solo paso
  asistente/      Claude: expediente del lead, «¿conviene?» y redacción del hilo
  importar.py     Pegar una lista y que quede como leads
  auth.py         Hash scrypt, login, sesiones
  web/            FastAPI + templates + kanban + ventana de redacción
  seed.py         Datos de demo
  cli.py          init | usuario | descubrir | seed | ingestar | enriquecer | recalcular | servir
migraciones/      Alembic
tests/            453 tests: dominio, web, accesibilidad, correo, asistente, Apollo, auth, ingesta y enriquecimiento
docs/             Primera búsqueda, estrategia, Gmail, LinkedIn/Apify, Apollo, asistente y despliegue
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
