# LinkedIn Jobs vía Apify

## Por qué vale la pena

LinkedIn es la fuente más grande de avisos en Argentina para empresas medianas y
grandes. Y a diferencia del resto de los conectores, una búsqueda **descubre empresas
nuevas**: el resto sólo vigila las que ya cargaste, esto trae las que todavía no
conocías.

## El riesgo, sin vueltas

Los términos y condiciones de LinkedIn **prohíben el scraping automatizado**. No es
zona gris: está escrito.

Ahora, qué implica eso en la práctica:

- **No es un delito.** En *hiQ Labs v. LinkedIn* los tribunales estadounidenses
  sostuvieron que scrapear datos públicos no viola la ley de fraude informático
  (CFAA). LinkedIn igual ganó después por incumplimiento de contrato.
- **Es un incumplimiento contractual.** La reacción habitual de LinkedIn es bloquear
  IPs y mandar cartas de cese; los juicios los reservan para operaciones grandes.
- **El riesgo operativo lo absorbe Apify**, que pone sus propios proxies — siempre y
  cuando se respete la regla de abajo.

Es una decisión de negocio, no técnica. Queda registrada acá para que se tome con la
información a la vista.

## Las dos reglas

### 1. Nunca le des tu cookie de sesión al actor

Hay actores que piden tu cookie `li_at` para acceder a más datos. **No los uses.**

Con tu cookie, el ban deja de ser un riesgo de infraestructura de Apify y pasa a ser
*tu cuenta de LinkedIn* — la que usás para trabajar, contactar candidatos y sostener tu
reputación profesional. Es exactamente el activo que no conviene arriesgar.

Elegí actores que trabajen sobre avisos públicos, sin autenticar.

### 2. Sólo avisos, nunca perfiles de personas

Un aviso de trabajo es información de empresa: qué puesto, dónde, desde cuándo.

Un perfil es un dato personal de alguien que no te lo dio. Eso cae bajo la Ley 25.326
y exige una base legal que no tenemos. Además es lo que efectivamente irrita a
LinkedIn.

Talanton sólo mapea campos de aviso. Si un actor devuelve datos del reclutador, se
descartan.

## Configuración

1. Creá una cuenta en [apify.com](https://apify.com) y sacá tu token en
   **Settings → Integrations → Personal API token**.
2. Cargalo como variable de entorno del servicio:
   ```
   TALANTON_APIFY_TOKEN=apify_api_...
   ```
3. Elegí un actor de LinkedIn Jobs en la [tienda de Apify](https://apify.com/store).
   Mirá que sea de avisos públicos y **que no pida cookie de sesión**.

## Cargar una búsqueda

En la pantalla **Fuentes**, panel «Búsqueda en LinkedIn». La configuración es el JSON
de entrada del actor, más dos campos propios:

```json
{
  "_actor": "usuario/nombre-del-actor",
  "_pais": "AR",
  "title": "jefe de mantenimiento",
  "location": "Argentina",
  "rows": 100
}
```

- `_actor`: qué actor correr. Lo tomás de su página en la tienda.
- `_pais`: país por defecto cuando el aviso no permite deducirlo de la ubicación.
- El resto son los parámetros del actor, **tal cual los documenta su página**. Cambian
  de actor en actor: por eso se guardan como JSON libre en vez de un formulario fijo.

### La URL de búsqueda es lo que más importa

El actor recibe URLs de búsqueda de LinkedIn. Una URL sin filtros
(`/jobs/search/?position=1&pageNum=0`) devuelve avisos de todo el mundo, sin relación
con lo que buscás: se paga igual y no sirve para nada.

Armala en LinkedIn: hacé la búsqueda a mano, con los filtros puestos, y copiá la URL de
la barra del navegador. Los parámetros que importan:

| Parámetro | Para qué |
|---|---|
| `keywords=` | El puesto. `jefe%20de%20mantenimiento` |
| `location=Argentina` | Dónde |
| `f_TPR=r604800` | Publicados en los últimos 7 días |
| `sortBy=DD` | Más recientes primero |

Con `f_TPR` acotado a la última semana, cada corrida trae poco y barato: lo que ya
viste está en la base, y `primera_vez_vista` sigue contando los días igual.

**Poné siempre un tope de resultados** (`rows`, `maxItems` o como lo llame el actor).
Apify cobra por uso y un actor sin límite puede correr durante horas.

### `scrapeCompany: true` conviene dejarlo prendido

Suma los datos de la empresa al resultado: cantidad de empleados, industria y sitio
web. Los tres se usan:

- La **dotación** decide a qué cargo apuntar (en una PyME el dueño, en una de 500 el
  líder de selección) y pesa en el eje de capacidad de pago del score.
- El **sitio web** es la clave de deduplicación preferida: evita que la misma empresa
  entre dos veces con nombres distintos.

Sale un poco más caro por resultado, pero es información que de otro modo hay que
buscar a mano empresa por empresa.

## Sobre la precisión de las fechas

LinkedIn muchas veces informa la antigüedad como texto relativo: «hace 3 semanas» en
vez de una fecha. Talanton lo interpreta, pero marca esas vacantes como
**fecha aproximada**, y en pantalla se ven con un `~` (`~92 días`).

Importa porque ese número termina en un mail al cliente. Decirle «hace 92 días» cuando
en realidad son entre 85 y 99 es una forma barata de quedar mal en la primera frase.

La buena noticia: `primera_vez_vista` sigue siendo exacta. Una vez que Talanton lleva
unas semanas mirando un aviso, el histórico propio es más confiable que lo que informa
la fuente.

## Qué hacer si LinkedIn bloquea

Si el actor empieza a devolver vacío o a fallar:

1. **No subas la frecuencia ni la cantidad.** Empeora todo.
2. Fijate si el actor tiene actualizaciones — sus autores suelen adaptarse.
3. Si el problema persiste, bajá el volumen o pausá la búsqueda.

Las fuentes de ATS y JSON-LD siguen andando igual: por eso el sistema no depende de
una sola fuente. LinkedIn suma alcance, no lo sostiene.
