# Apollo.io

La pantalla **Buscar** trae empresas que encajan con tu cliente ideal, con la
persona que decide contratar una consultora.

## Lo primero: qué resuelve y qué no

Apollo te dice **quién** es el decisor de una empresa que encaja con tu ICP. No
te dice **cuándo** esa empresa necesita una consultora.

Esa distinción es el producto entero. Un mail que abre con

> Vi que hace 92 días están buscando Jefe de Depósito en Mendoza y que ya
> republicaron el aviso.

se lee. Uno que abre con «somos una consultora de selección» no, por más
correcto que esté el destinatario.

Así que Apollo no reemplaza a los avisos: **los alimenta**. El flujo que rinde es

1. Traés 50 empresas de tu rubro y tamaño desde Buscar.
2. Las dejás en [Fuentes](../README.md) para que la corrida diaria vigile sus
   avisos.
3. Cuando una publica una búsqueda y se le estira, el score la sube sola y ya
   tenés el decisor cargado desde el día uno.

Contactar en frío a las 50 el primer día también se puede, y a veces hay que
hacerlo. Pero la tasa de respuesta de un mail sin señal es de otro orden.

## Los dos pasos, y dónde está la plata

Apollo cobra de dos maneras distintas y conviene tenerlo claro:

| Acción | En Talanton | Costo |
|---|---|---|
| Buscar personas | Botón **Buscar** | Gratis. Los emails vienen tapados |
| Destapar un email | Botón **Traer los seleccionados** | **Un crédito por email** |

Por eso están separados. Podés ajustar los filtros veinte veces sin gastar nada,
y recién pagás por los contactos que marcaste. Un buscador que gasta créditos al
apretar «buscar» se come el plan del mes en una tarde de pruebas.

En la lista, los emails que todavía no compraste se ven con un chip
**«Tapado»** — no es un mail real, es el literal
`email_not_unlocked@dominio.com` que devuelve Apollo.

Si destildás **«Destapar los emails que falten»**, se importan igual la empresa,
el nombre y el cargo del decisor sin gastar un crédito. Sirve más de lo que
parece: con eso ya sabés a quién buscar, y el mail puede salir del aviso de la
propia empresa (`python -m talanton.cli enriquecer`).

## Si tu plan no tiene API

**La API de Apollo es de plan pago.** Con una cuenta gratuita la key existe pero
los endpoints devuelven 403, y eso no se arregla desde acá.

No estás trabado: **exportá desde la web de Apollo y pegá en Importar.** El
resultado en la base es exactamente el mismo —empresa, contacto marcado como
decisor, lead en «Nuevo», score calculado—; lo único que cambia es que el paso
de traer los datos lo hacés vos en vez del servidor.

1. En Apollo hacés la búsqueda con los filtros que quieras.
2. Seleccionás las filas y **Export**.
3. Abrís el CSV, copiás todo y lo pegás en **Importar**.

Talanton reconoce los encabezados de Apollo tal cual vienen, incluidos los tres
que suelen romper un importador genérico:

| Columna de Apollo | Qué hace Talanton |
|---|---|
| `First Name` + `Last Name` | Las junta. Sin esto el saludo del mail sale cortado |
| `# Employees` | La lee igual pese al `#`, y alimenta el eje de capacidad de pago |
| `City` y `Company City` | Gana la de la empresa: el lead es la empresa, no la persona |
| `Person Linkedin Url` | Queda como procedencia del contacto, para poder auditarlo |

La pantalla **Buscar** queda ahí para el día que actives la API. No hay nada que
migrar: las dos vías escriben en la misma tabla por el mismo código.

## Alta de la API

1. En Apollo: **Settings → Integrations → API**, generá una key.
2. Cargala como variable del servicio:

```
TALANTON_APOLLO_API_KEY=...
```

3. Reiniciá y entrá a **Buscar**.

Si algo falla, el botón **Probar la conexión** golpea la API con el pedido más
chico posible y te muestra el código HTTP y el texto que devolvió Apollo, sin
traducir. Con **401** la clave no sirve; con **403** la clave está bien y el que
no alcanza es el plan.

## Los filtros

**Cargos** es el campo que más mueve el resultado. La regla: no es quien *sufre*
la vacante, es quien *firma*. El gerente de operaciones tiene el depósito sin
jefe hace tres meses, pero el que contrata una consultora es RRHH — o el dueño,
en una empresa donde RRHH no existe como área.

Vienen precargados en español y en inglés porque Apollo hace coincidencia
aproximada sobre el título tal como la persona lo escribió en LinkedIn, y en
Argentina conviven las dos formas.

**Empleados** se precarga con el ICP de *Mi empresa*. Apollo no acepta un rango
libre: trabaja por tramos fijos (1-10, 11-20, 21-50, 51-100…). Talanton traduce
tu rango a los tramos que se **solapan**, no a los que caen enteros adentro: con
20-300, el tramo 11-20 también tiene empresas que sirven.

**Industrias** es una lista cerrada con nombres en castellano. Tiene que serlo:
Apollo filtra por palabras clave **de su propio vocabulario y en inglés**, así que
un campo de texto libre es una trampa —escribís «Logística», no matchea nada, y
la conclusión equivocada es que Apollo no tiene empresas de logística en
Argentina—. La lista no trae las ~150 industrias de Apollo sino las que le
compran a una consultora de selección en Argentina y LatAm.

Para lo que no esté hay un campo de **palabras clave libres**, y ahí sí manda el
inglés: «fintech» funciona, «tecnología financiera» no.

Vacío busca en todas, que al principio suele rendir más: es más fácil descartar
mirando la lista que adivinar cómo llama Apollo a tu rubro. Se precarga con el
ICP de *Mi empresa*, traduciendo del castellano.

**País** filtra por la ubicación de la *empresa*, no de la persona. Interesa dónde
está la operación que contrata, no dónde vive el gerente.

## Qué queda cargado

Cada persona importada deja:

- La **empresa** como lead en «Nuevo», con industria, dotación y ciudad.
- El **contacto** marcado como decisor —si lo elegiste vos, es con quien querés
  hablar—.
- La **procedencia** en `Contacto.fuente_url`: el LinkedIn de la persona o
  `apollo.io:<id>`. Sin eso, un dato de contacto de un tercero no se puede
  auditar ni borrar a pedido, que es lo que exige la Ley 25.326.

Si la empresa ya estaba en la base no se duplica: se completan los datos que
falten y el lead sigue con su historia.

## Sobre comprar datos de contacto

Antes dije que no conviene comprar bases, y lo sostengo para las bases sueltas
que se venden por CSV: no se sabe de dónde salieron, están desactualizadas y no
hay a quién reclamarle.

Apollo es otra cosa: es un proveedor identificable, con términos de uso, que
mantiene los datos y procesa bajas. Eso hace que la procedencia sea auditable, que
es lo que faltaba. No lo vuelve gratis ni lo vuelve infalible — una parte de los
mails va a rebotar igual—, pero es una base defendible.

Las reglas de siempre siguen valiendo: tope de 40 envíos diarios por casilla,
nada de secuencias automáticas, y baja a la primera que la piden.

## Si falla

| Qué dice | Qué pasa |
|---|---|
| Apollo rechazó la clave | Key vencida, mal copiada, o plan sin API |
| Rechazó los filtros | Algún valor no es de los que acepta; suele ser el rango de empleados |
| Está limitando por volumen | Tope por minuto, hora o día. Esperá |
| No se pudo llegar a Apollo | Red del servidor |

Un revelado que falla a mitad de una importación **no frena al resto**: los
contactos que ya se pagaron entran igual, y los que fallaron aparecen listados
abajo del resultado.
