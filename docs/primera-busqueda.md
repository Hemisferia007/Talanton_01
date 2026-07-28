# La primera búsqueda real

De cero a la primera tanda de mails. Una tarde de trabajo, sin consola.

## Antes de empezar: 15 minutos de configuración

### 1. Que el cron deje de estar en rojo

Entrá a **Fuentes**. Van a estar dos fuentes de ejemplo que se sembraron solas
(`mercadolibre` en Greenhouse, `ualaar` en Lever) y que fallan siempre porque
esos boards no existen. Desactivalas con el botón de cada una.

Sin eso, la corrida diaria falla todos los días y la alarma pierde sentido justo
cuando vas a empezar a depender de ella.

### 2. Cargá Mi empresa

**Mi empresa** no es cosmética: el ICP que cargues ahí alimenta el 25% del score
—el eje de *fit*— y precarga los filtros de búsqueda. Con esto vacío, el score
puntúa igual a una PyME de 8 personas que a tu cliente ideal.

Lo mínimo:

- **Industrias objetivo**: los rubros donde ya cubriste búsquedas. Si recién
  arrancás, poné dos o tres, no diez.
- **Dotación**: el rango de empresa que te puede pagar un fee. En Argentina,
  para búsquedas de mando medio, algo entre 50 y 800 suele ser realista.
- **Seniority**: qué perfiles cubrís bien. Ahí está tu margen — un analista
  junior lo cubre RRHH publicando un aviso, un jefe de planta no.

### 3. Conectá Gmail

En la misma pantalla. Sin esto podés cargar leads pero no escribirles desde acá.
Paso a paso en [`gmail.md`](gmail.md).

---

## La búsqueda, paso a paso

### Paso 1 — Sacá la lista de Apollo

En apollo.io, **People** (no Companies: querés la persona, no la empresa suelta).

Filtros:

| Filtro | Qué poner |
|---|---|
| **Job titles** | Gerente de Recursos Humanos, Jefe de Recursos Humanos, Human Resources Manager, Head of People, Gerente General, Owner |
| **Company location** | Argentina — es la ubicación de la *empresa*, no de la persona |
| **# Employees** | El rango que cargaste en Mi empresa |
| **Industry** | Uno solo, el rubro donde más fuerte estás |

**Un rubro por vez.** Es lo más importante de todo esto y explico por qué abajo.

Seleccioná entre **30 y 50 filas**, desbloqueá los emails con tus créditos y
exportá. Si tu plan no deja exportar, copiá la tabla de la pantalla: el
importador traga eso igual.

### Paso 2 — Pegala en Importar

**Importar** → pegás el CSV entero → **Previsualizar**.

Mirá que las columnas hayan caído en su lugar. Los encabezados de Apollo ya están
reconocidos: `First Name` y `Last Name` se juntan, `# Employees` se lee pese al
`#`, y entre `City` y `Company City` gana la de la empresa.

Dejá tildado **«Vigilar los avisos de estas empresas»** e importá.

### Paso 3 — Dejá que busque los avisos

Con ese tilde, las 50 empresas quedaron como objetivos en **Fuentes**. La corrida
diaria les va a buscar el board de avisos —Greenhouse, Lever, Ashby, Recruitee,
Workable, o JSON-LD en su página de trabajo— y a partir de ahí empieza a contar
los días de cada búsqueda abierta.

No esperes a mañana: en **Fuentes**, cada objetivo pendiente tiene un botón para
sondearlo ahora. Con 50 son unos minutos, y las que tengan board público empiezan
a traer avisos hoy mismo.

### Paso 4 — Escribí, pero no a los 50

Andá a **Leads**, ordenado por score.

**Arriba van a estar los que ya tienen señal**: una búsqueda abierta hace más de
30 días, varias en simultáneo, un puesto que se repite. A esos escribiles primero
y la plantilla se elige sola —el borrador ya abre con el dato concreto—.

Al resto, que todavía no tiene señal, dos opciones:

- **Esperar.** En dos o tres semanas algunos van a tener historia propia y el mail
  va a ser mucho mejor.
- **Escribir igual**, con la plantilla de presentación. Es legítimo, pero sabé que
  la tasa de respuesta es de otro orden.

El tope de envío es de **40 por casilla y por día**, y no conviene subirlo.

---

## Por qué un rubro por vez

Es la parte que más rinde y la que más se saltea.

Con 50 empresas de un mismo rubro, tu mail puede decir algo que sólo alguien de
ese rubro diría. «Sabemos lo que cuesta conseguir un jefe de mantenimiento
industrial en el interior» le habla a una persona. «Ofrecemos servicios de
selección» no le habla a nadie.

Además, cuando mandes las 50 vas a poder leer el resultado: si respondieron
cuatro, aprendiste algo del rubro. Si mandaste 50 mails a doce rubros distintos y
respondieron cuatro, no aprendiste nada.

Y cuando encuentres el rubro que responde, ahí sí escalás.

---

## Qué esperar, con números honestos

- De 50 mails fríos **sin señal**, con un mensaje decente: entre 2 y 5 respuestas.
- De 50 mails **con señal concreta** —«hace 92 días que buscan esto y ya lo
  republicaron»—: bastante más, y sobre todo mejores. La conversación arranca en
  otro lado.
- Una parte de los mails va a rebotar. Es normal en cualquier base, incluida la
  de Apollo.

La primera tanda es tanto para aprender como para vender. Anotá en el lead qué
contestaron, aunque sea que no: eso es lo que después recalibra el score con datos
tuyos y no con mi intuición.

---

## La semana que viene

Cuando la corrida diaria lleve unos días, **Avisos** va a mostrar búsquedas con
días acumulados de verdad. Ahí el producto empieza a hacer lo suyo: el panel te
muestra solo las que se están estirando, y el mail se escribe casi solo.

Ese es el activo. Una lista de contactos la compra cualquiera; saber que una
búsqueda lleva 92 días abiertos requiere haber estado mirando desde antes.

Por eso el orden de estos pasos importa: **cargar y dejar vigilando hoy** vale más
que mandar los 50 mails hoy.
