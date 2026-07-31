# Portales de empleo argentinos

Es lo que alimenta **Buscar empresas**: elegís zona y rubro y salen las empresas que
están publicando ahora. Tres conectores en `talanton/ingest/portales/`.

## Por qué estos tres

Porque acá postea la PyME argentina, que es exactamente el cliente que compra
búsquedas de mando medio.

- **Greenhouse y Lever** sirven para *vigilar* empresas que ya conocés, no para
  descubrir: ninguna PyME argentina usa un ATS internacional.
- **LinkedIn vía Apify** descubre, pero sesga a medianas y grandes y trae muchas
  consultoras — justo lo que no sirve.

| Portal | Cómo sirve el listado | Necesita navegador |
|---|---|---|
| **Computrabajo** | HTML del servidor | No |
| **Bumeran** | Armado con JavaScript | Sí |
| **ZonaJobs** | Armado con JavaScript | Sí |

Bumeran y ZonaJobs son la misma plataforma con dos marcas y dos públicos: Bumeran
tira más a puestos profesionales, ZonaJobs a operativos y comerciales. Comparten
todo el código salvo el dominio.

Computrabajo va primero en la lista por una razón práctica: es el más barato de
consultar y el que anda sin `scrapling install`. Si el navegador no está instalado,
los otros dos fallan y la búsqueda sigue con el que queda — **un portal caído no
frena a los demás**.

## El riesgo, sin vueltas

Los términos y condiciones de estos portales, como los de LinkedIn, **restringen el
scraping automatizado**. Vale el mismo análisis que está en [`linkedin.md`](linkedin.md):
es un incumplimiento contractual, no un delito, y la reacción habitual es el bloqueo
por IP, no el juicio.

Hay dos diferencias a favor:

- **Sólo se leen avisos**, que son publicaciones de empresa dirigidas al público. No
  se tocan perfiles de personas, que es lo que cae bajo la Ley 25.326 y lo que
  realmente irrita a los portales.
- **El volumen es bajo**: una búsqueda por segmento cuando el usuario aprieta un
  botón, no un barrido continuo. No hay corrida programada contra los portales.

Se descarta además lo que no sirve como lead: avisos confidenciales (sin nombre de
empresa no hay a quién escribirle), consultoras de selección y avisos perennes.

## Los selectores

Cada conector concentra sus selectores en constantes al principio del archivo, para
que arreglar un cambio de HTML sea cambiar una línea:

```python
SEL_AVISO = "article.box_offer, article[data-id]"
SEL_TITULO = "h2 a, a.js-o-link"
SEL_EMPRESA = "a.it-blank, p.dFlex a, span.dIB"
```

**Advertencia honesta**: se escribieron contra la estructura documentada de cada
sitio, **no contra una respuesta capturada** — hay que verificarlos contra el HTML
real la primera vez. Es la misma advertencia que aplicó al conector de Apify.

Cómo verificarlos cuando un portal deja de traer nada:

```bash
python - <<'PY'
from talanton.ingest.base import traer_pagina
from talanton.ingest.portales.computrabajo import Computrabajo, SEL_AVISO
portal = Computrabajo()
from talanton.ingest.portales import Segmento
pagina = traer_pagina(portal.url(Segmento(zona="caba")), stealth=False)
print(len(pagina.css(SEL_AVISO)), "avisos encontrados")
PY
```

Si devuelve 0, el selector cambió. Abrí la URL en el navegador, mirá el HTML y
ajustá la constante.

Scrapling trae emparejamiento adaptativo, que amortigua los cambios chicos —una clase
renombrada, un `div` de más— pero no los rediseños.

## La fecha

Es el dato que hace útil a todo lo demás: sin fecha no se puede decir «hace 92 días
que buscan», que es lo que abre la conversación.

Los portales casi nunca publican la fecha exacta; publican «hace 3 días», «hace 1
mes». Se interpreta con el mismo criterio que LinkedIn (`interpretar_antiguedad`):

- «hace 3 días» → fecha exacta.
- «hace 2 semanas», «hace 1 mes» → fecha **marcada como aproximada**, y en pantalla
  se muestra con `~`. Ese número termina en un mail al cliente, así que decir «hace
  unos dos meses» es correcto y decir «hace exactamente 60 días» no lo sería.
- Texto que no se entiende → **sin fecha**. No se inventa.

Y cuando pedís «publicados hace más de N días», los avisos sin fecha quedan afuera.
Es a propósito: no se puede afirmar que sea viejo, y mejor perderlo que suponerlo.

## Instalación del navegador

```bash
pip install "scrapling[fetchers]"
scrapling install
```

En Docker está en el `Dockerfile`, con `PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers`
para que el navegador quede fuera del `HOME` de root y lo pueda leer el usuario sin
privilegios que corre la app. Suma unos cientos de MB a la imagen y minutos al build;
si eso llega a molestar, esa línea se puede sacar y la búsqueda sigue funcionando con
Computrabajo solo.
