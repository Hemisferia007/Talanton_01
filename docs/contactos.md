# Conseguir los contactos

El problema concreto: tenés 45 empresas cargadas y a ninguna le podés escribir,
porque no sabés el mail de nadie.

Hay tres vías y conviene usarlas en este orden, de la más barata a la más cara.

## 0. El sitio de la empresa — gratis, ilimitada y la de mejor procedencia

El botón **Buscar en su web**, en el panel de Contactos de cada lead.

Talanton recorre unas pocas páginas del sitio —home, contacto, nosotros, equipo,
trabajá con nosotros— y junta los mails publicados. Es la fuente de mejor calidad
legal que existe: la dirección la publicó la propia empresa, en su propia web, y
la procedencia es la URL misma.

El parseo lo hace **Scrapling**, que es para lo que está: HTML institucional que
cambia seguido y hay que leer igual. Si no está instalado se usa `httpx` y funciona
igual para la enorme mayoría de los sitios.

Dos límites deliberados:

- **Cinco páginas por empresa**, no un crawl. Si el mail no está ahí, no está
  publicado, y seguir es golpear un sitio ajeno de más.
- **Sólo mails del dominio de la empresa.** El `hola@agenciaweb.com` del pie es de
  quien hizo el sitio, no de quien queremos contactar.

No cuesta nada y no tiene tope: probala siempre antes que Hunter.


## 1. Hunter.io — la que anda gratis y automatizada

Hunter busca sobre el **dominio** de una empresa —`baufest.com`— y devuelve las
direcciones que encontró publicadas en internet, con nombre, cargo y **de qué
página las sacó**.

A diferencia de Apollo, **su API funciona en el plan gratuito**: 25 búsquedas
por mes. Eso son 25 empresas mensuales sin pagar nada.

### Alta

1. Cuenta en [hunter.io](https://hunter.io), **API → API Keys**.
2. Cargala como variable del servicio:

```
TALANTON_HUNTER_API_KEY=...
```

3. Reiniciá. Aparece el botón **Buscar contactos de RRHH** arriba en *Leads*, y
   uno por lead en su ficha.

### Cómo se usa

El botón de *Leads* busca en **las 10 empresas de mayor score que todavía no
tienen ningún mail**. Las que ya tienen contacto se saltean: re-consultar una
empresa resuelta es la forma más rápida de quemar las 25 del mes.

Le pide a Hunter sólo los departamentos `hr` y `executive` — RRHH porque es
quien compra el servicio, dirección porque en una empresa chica no hay área de
RRHH y decide el dueño.

### Qué guarda y qué descarta

- **Persona con nombre y cargo** → se carga como contacto, y si el cargo
  corresponde al decisor de una empresa de ese tamaño, queda marcado como tal.
- **Buzón de área** (`rrhh@`, `empleos@`) → se carga igual, sirve para escribir,
  pero **nunca como decisor**: llamarlo así le mentiría al eje de accesibilidad
  del score.
- **Confianza por debajo de 50** → se descarta. Un rebote cuesta reputación de
  dominio, que es cara de recuperar y barata de arruinar.
- **Nada** → si la empresa no tiene mails publicados, Hunter no devuelve nada, y
  eso está bien. Es preferible a un `nombre.apellido@` armado por patrón.

Cada contacto queda con la URL de donde salió. Sin procedencia, un dato de
contacto de un tercero no se puede defender bajo la Ley 25.326.

## 2. Del propio aviso — gratis y la más limpia

`python -m talanton.cli enriquecer` lee las descripciones de los avisos que ya
están en la base y saca los mails que la empresa **publicó para que la contacten
por trabajo**.

Es la fuente de mejor calidad legal que existe: no hay intermediario, no hay
base comprada, y el consentimiento es evidente. La contra es que sólo funciona
donde ya hay avisos cargados, y muchos avisos no traen mail.

## Cuál usar

| Situación | Vía |
|---|---|
| Tenés el dominio | **Su propia web** — gratis, sin tope |
| La web no tenía nada y querés al de RRHH | **Hunter** |
| Ya tenés avisos cargados con texto | **`cli enriquecer`** |
| La empresa no tiene nada publicado | LinkedIn a mano, o descartala |

Lo razonable al empezar: prendé Hunter, apretá el botón una vez, y mirá cuántas
de las 10 resolvió. Si resuelve 6 o 7, con 25 búsquedas mensuales cubrís el
ritmo de trabajo de una persona sin pagar nada.

## Y después del contacto

Tener el mail no es tener algo para decir. El mail que abre con

> Vi que hace un mes están buscando Cloud Engineer y que además tienen abierta
> una de DevOps.

se lee; el que abre con «somos una consultora de selección» no.

Por eso, cuando veas una búsqueda publicada de una empresa que tenés cargada
—en LinkedIn, en su web, donde sea— **cargala en la ficha del lead**. Son treinta
segundos y cambian el mail entero: el score se recalcula, el gancho se arma solo
y el borrador ya sale escrito con ese dato.
