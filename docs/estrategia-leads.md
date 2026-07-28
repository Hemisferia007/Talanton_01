# Talanton — Estrategia del motor de leads

> Motor de generación de leads para una consultora de RRHH especializada en selección.

## 1. La tesis: señales, no listas

El error habitual es armar una base de empresas y hacer outbound genérico. Eso compite
por atención sin ningún argumento y quema el dominio de mail.

Para una consultora de **selección**, el lead no es "una empresa": es **una empresa que
tiene una búsqueda abierta que no está pudiendo cerrar, ahora**. Ese estado es
observable públicamente y tiene fecha de vencimiento. Todo el sistema se diseña alrededor
de detectar ese momento y llegar antes que la competencia.

El activo defendible no es el scraper: es la **serie histórica**. Cualquiera puede
scrapear un aviso hoy; sólo quien viene mirando todos los días sabe que ese aviso lleva
52 días publicado, que ya se republicó dos veces y que el mismo puesto se buscó hace
7 meses. Eso no se compra: se acumula. Por eso el sistema corre desde el día 1 aunque el
scoring todavía sea tosco.

## 2. Señales de compra (ordenadas por poder predictivo)

| # | Señal | Por qué importa | Cómo se detecta |
|---|---|---|---|
| 1 | **Aviso abierto > 30/45 días** | La búsqueda propia falló. Es el pitch perfecto: "veo que buscás X hace 7 semanas". | Requiere histórico: `primera_vez_visto` vs. hoy |
| 2 | **Reposteo del mismo puesto** | Reintentaron y volvieron a fallar. Dolor confirmado. | Fingerprint del puesto (empresa + rol normalizado) reapareciendo |
| 3 | **Misma vacante hace 6-12 meses** | Problema de rotación → necesidad recurrente, no puntual. | Histórico + matching de rol |
| 4 | **Volumen simultáneo (3+ búsquedas)** | Expansión o equipo de TA desbordado. Ticket grande. | Agregación por empresa |
| 5 | **Perfil difícil / senior / nicho** | Es exactamente lo que no se cubre con un aviso. Mayor fee. | Clasificación de seniority + skills escasas |
| 6 | **Sin equipo de TA interno** | Si no tienen recruiter, tercerizan sí o sí. | Ausencia de roles de TA/People en la empresa; el aviso lo firma el CEO/dueño |
| 7 | **Publicado por la empresa, no por una consultora** | Si ya hay consultora, el lead está tomado (o es inteligencia competitiva). | Detección de aviso "confidencial"/marca de consultora |
| 8 | **Ronda de inversión / expansión / nueva sede** | Presupuesto fresco y presión de contratación. | Fuentes de prensa y de funding |

Señales 1-3 son las que **nadie más tiene**, porque exigen correr el crawler todos los días
desde antes de necesitarlas.

### Señal negativa (igual de importante)

Cuando un aviso **desaparece**, la búsqueda se cerró. Ese lead baja de prioridad de
inmediato. Un sistema que sólo suma señales termina llamando a empresas que ya
contrataron; hay que modelar el cierre tanto como la apertura.

## 3. Arquitectura

```
┌────────────┐   ┌───────────────┐   ┌──────────────┐   ┌─────────┐   ┌───────────┐
│  Ingesta   │──▶│ Normalización │──▶│Enriquecimiento│──▶│ Scoring │──▶│ Activación│
│ (Scrapling)│   │   + dedupe    │   │   decisores   │   │ + razones│   │ CRM/mail │
└────────────┘   └───────────────┘   └──────────────┘   └─────────┘   └───────────┘
       │                  │                                    ▲            │
       └──── cron diario ─┴────── Postgres (histórico) ────────┘            │
                                        ▲                                   │
                                        └────── feedback comercial ─────────┘
```

### 3.1 Ingesta — dónde entra Scrapling

Tres carriles, de más barato a más caro. Siempre se intenta el más barato primero:

**Carril A — APIs de ATS (el atajo).** Muchísimas empresas publican en Greenhouse, Lever,
Workable, Ashby, SmartRecruiters, Recruitee o Teamtailor, y esos boards exponen JSON
público y estable:

- `https://boards-api.greenhouse.io/v1/boards/<empresa>/jobs`
- `https://api.lever.co/v0/postings/<empresa>?mode=json`

Sin bloqueo, sin parseo frágil, con fecha de publicación real. Se cubre con
`Fetcher.get()` de Scrapling y listo. Esto se ataca primero: es el 20% del esfuerzo por
el 60% de la señal limpia.

**Carril B — JSON-LD en páginas de carrera.** El estándar `schema.org/JobPosting` está
embebido en la mayoría de los sitios corporativos porque es lo que consume Google Jobs.
Trae `datePosted`, `hiringOrganization`, `employmentType`, `validThrough` ya
estructurados:

```python
page.css('script[type="application/ld+json"]::text')
```

Un solo parser sirve para cientos de sitios distintos. Enorme ahorro de mantenimiento.

**Carril C — Portales de empleo (HTML).** Acá sí hace falta la artillería de Scrapling:

- `StealthySession` para los que tienen anti-bot, `Fetcher` para el resto.
- **Selectores adaptativos** (`adaptive=True`): los portales cambian el DOM seguido; que
  el framework relocalice el elemento evita que el pipeline se caiga cada dos semanas.
  Este es el motivo principal para elegir Scrapling sobre requests+bs4.
- **Spider** con throttling por dominio y checkpoints, para pausar/reanudar sin perder
  el crawl.
- Rotación de proxies y sesiones con cookies persistentes.

**Sobre las fuentes:** priorizar ATS, JSON-LD y portales que lo permitan. LinkedIn queda
fuera del scraping automatizado — su ToS lo prohíbe explícitamente y el riesgo (legal y
de bloqueo de cuentas del equipo) no compensa; se usa como canal de contacto manual, no
como fuente. Cada conector declara su fuente y su base legal en la config, y se guarda
`fuente_url` en cada registro para poder auditar y borrar a pedido (Ley 25.326 / GDPR
según mercado).

### 3.2 Normalización y deduplicación

El punto más subestimado del proyecto. Sin esto, el comercial recibe la misma empresa
seis veces con seis nombres distintos y deja de confiar en la herramienta.

- **Entidades canónicas:** `Empresa`, `Vacante`, `Señal`, `Contacto`.
- **Clave de empresa:** dominio web > CUIT/tax ID > nombre normalizado (fuzzy match sobre
  razón social sin sufijos societarios).
- **Clave de vacante:** `empresa_id + rol_normalizado + ubicación`. El rol se normaliza
  contra un diccionario propio (ej: "Dev Full Stack Ssr", "Programador Full-Stack
  Semi Senior" → mismo puesto). Sin esto, las señales 2 y 3 no existen.
- **Append-only:** nunca se pisa un registro. Cada corrida escribe observaciones con
  timestamp; el estado actual es una vista derivada. Así el histórico queda intacto.

### 3.3 Enriquecimiento

- Resolución de dominio y datos firmográficos (tamaño, industria, ubicación).
- **Decisor:** en PyME es dueño/CEO; en empresa mediana, Head of People / HRBP. La
  regla de a quién apuntar sale del tamaño estimado.
- Canal de contacto verificado (mail corporativo con validación MX/SMTP antes de enviar,
  para no quemar reputación de dominio).

### 3.4 Scoring — que sea explicable

Score 0-100 compuesto por cuatro ejes, **cada uno con sus razones en texto**:

| Eje | Peso inicial | Qué mide |
|---|---|---|
| **Urgencia** | 40% | Días abierta, reposteos, volumen simultáneo |
| **Fit ICP** | 25% | Industria, tamaño, geo, tipo de perfil vs. lo que la consultora cubre bien |
| **Accesibilidad** | 20% | Sin TA interno, sin consultora ya asignada, decisor identificable |
| **Capacidad de pago** | 15% | Funding, crecimiento de headcount, seniority de las búsquedas |

Reglas determinísticas para lo numérico; LLM sólo para lo que es texto libre
(clasificar seniority, detectar si el aviso lo publica una consultora, resumir el
contexto). **El LLM no decide el score.** Un score que el comercial no puede
explicarle al cliente no se usa.

Lo que sí hace el asistente —ya implementado, ver [`asistente.md`](asistente.md)— es
una lectura **paralela**: entra a la ficha, lee el texto de los avisos y lo que la
empresa contestó, y dice si conviene contactarla, con sus motivos y sus reparos. Queda
al lado del score, fechada y con su propia etiqueta, nunca sumada adentro. Son dos
lecturas distintas de la misma empresa y tienen que verse como tales: si alguna vez se
contradicen, el que manda es el score.

**Salida por lead:** score + las 3 razones principales + el gancho textual listo
("hace 52 días que buscan un Contador Senior en Córdoba, ya lo republicaron una vez").

### 3.5 Activación y feedback

- Export a CRM / CSV / webhook (n8n si ya lo usan para las secuencias).
- Alerta diaria: sólo leads nuevos por encima del umbral, no un dump.
- **Loop cerrado:** el resultado comercial (respondió / reunión / ganado / perdido)
  vuelve al sistema y recalibra los pesos. A los 3-6 meses el scoring deja de ser
  intuición y pasa a estar entrenado con datos propios. Este loop es lo que separa una
  herramienta de un scraper con Excel.

## 4. Stack

- Python 3.11+ · **Scrapling** (`[fetchers]`) para ingesta/parseo
- Pydantic para los modelos, Postgres para el histórico (SQLite en el MVP)
- Scheduler diario (cron/APScheduler) · FastAPI + UI mínima para revisar la cola
- Un conector = un módulo con interfaz común (`fetch() -> list[VacanteCruda]`), así
  agregar fuentes es incremental y aislado

## 5. Roadmap

**Fase 0 — Esqueleto que ya acumula histórico (semana 1).**
Modelos, storage append-only, 2-3 conectores ATS + parser JSON-LD, dedupe de empresas,
corrida diaria. Todavía no scorea, pero **empieza a juntar el activo**. Prioridad
absoluta: cada día que no corre es un día de histórico perdido.

**Fase 1 — Señales y scoring (semana 2-3).**
Cálculo de días-abierta, detección de reposteos, scoring con razones, export CSV.
Acá ya es usable comercialmente.

**Fase 2 — Enriquecimiento y personalización (semana 4-5).**
Decisores, verificación de mails, generación del mensaje a partir de la señal concreta.

**Fase 3 — Producto (semana 6+).**
UI de revisión, alertas, integración CRM, loop de feedback y recalibración.

## 6. Riesgos y cómo se mitigan

| Riesgo | Mitigación |
|---|---|
| Bloqueo de fuentes | Priorizar ATS/JSON-LD; throttling conservador; stealth sólo donde hace falta |
| Portales cambian el DOM | Selectores adaptativos de Scrapling + tests de contrato por conector que avisan cuando un parser deja de traer datos |
| Dedupe pobre → desconfianza del comercial | Invertir en normalización desde la Fase 0, no después |
| Datos personales | Guardar sólo contacto profesional, con `fuente_url`, retención definida y borrado a pedido |
| Falsos positivos de urgencia | Modelar el cierre de vacante (aviso que desaparece) con el mismo cuidado que la apertura |
