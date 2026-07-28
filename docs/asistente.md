# El asistente

Dos cosas, dentro de la ficha del lead:

1. **¿Conviene contactarlo?** — lee el texto de los avisos, lo que la empresa
   contestó y las notas del comercial, y dice si vale la pena dedicarle tiempo.
2. **Redactar respuestas** — escribe el próximo mail del hilo, contestando lo
   que la empresa efectivamente dijo.

Es opcional. Sin clave de API la app funciona exactamente igual y los botones no
aparecen.

## Qué agrega sobre el score

El score de Talanton mira números: días abiertos, cantidad de búsquedas,
dotación, industria. Por eso es determinístico, estable y —lo más importante—
explicable: el comercial puede decirle al cliente por qué lo llamó.

Lo que el score no puede mirar es el texto:

- Un aviso que pide diez años de experiencia por un sueldo de junior. Esa
  búsqueda no se cierra nunca, y ahí la consultora tampoco puede.
- Una respuesta que dice «nos interesa pero lo vemos el año que viene». El score
  sigue viendo una empresa con tres búsquedas abiertas; el hilo dice que no es
  el momento.
- Una descripción de la que se deduce que el mandato ya está dado a otra
  consultora.

El asistente lee eso. **No modifica el score**: queda al lado, con su fecha,
para que se vean como dos lecturas distintas y no como una sola con más
decimales. Si alguna vez hay que elegir, el que manda es el score.

El veredicto más valioso suele ser **«no conviene»**. El costo real de una
herramienta de leads no son los mails que manda: son las semanas que el
comercial gasta en empresas que nunca iban a comprar.

## Qué sale de Talanton (y qué no)

Todo lo que viaja a la API pasa por `talanton/asistente/expediente.py` y por
ningún otro lado. Se arma a mano campo por campo, en vez de serializar los
modelos, justamente para que agregar una columna a la base no mande nada nuevo
sin que alguien lo decida.

**Sale:**

- Datos de la empresa y de sus avisos —nombre, industria, dotación, país,
  puesto, días abiertos, texto del aviso—. Son públicos por definición: la
  empresa los publicó para que la contacten por trabajo.
- **Nombre y cargo** de los contactos, para poder saludar y para razonar sobre a
  quién apuntar.
- El hilo de mails con esa empresa, que es lo que hay que leer para contestar.
- Los datos de la consultora y su ICP, que salen de la pantalla *Mi empresa*.

**No sale nunca:** emails, teléfonos, credenciales, ni nada de otras empresas de
la base. Hay un test que lo verifica (`test_expediente_no_saca_datos_de_contacto`)
para que no se pierda al refactorizar.

Anthropic no entrena con los datos de la API. Aun así, la regla de acá es la
misma que en el resto del proyecto: sale lo mínimo que hace falta para responder
la pregunta.

## Alta

1. Creá una cuenta en [console.anthropic.com](https://console.anthropic.com) y
   cargá saldo.
2. Sacá una clave en **API Keys**.
3. Cargala como variable del servicio:

```
TALANTON_ANTHROPIC_API_KEY=sk-ant-...
```

No hace falta nada más: el panel aparece solo en la ficha del lead.

## Cuánto cuesta

Se paga por uso, no por mes. Cada lectura de un lead son unos pocos centavos de
dólar —depende de cuántos avisos y cuántos mensajes tenga la ficha—.

Dos cosas que lo mantienen bajo:

- La opinión **se guarda**. Entrar diez veces a la ficha no la vuelve a pedir:
  hay que apretar el botón.
- El expediente está acotado: se mandan hasta 12 avisos, 12 mensajes y los
  primeros 1.200 caracteres de cada descripción. Un aviso de LinkedIn entero es
  mayormente relleno.

Si el volumen crece, se puede cambiar el modelo:

```
TALANTON_ASISTENTE_MODELO=claude-sonnet-5
```

Sale bastante menos. Para leads simples alcanza; para decidir si vale la pena
una búsqueda difícil, el default (`claude-opus-5`) lee mejor.

## Por qué la opinión se marca como vieja

Junto a la opinión se guarda una huella de los hechos con los que se calculó:
cuántas búsquedas abiertas hay, en qué tramo de días están, cuántos mensajes
tiene el hilo, en qué etapa está el lead. Si eso cambia, la pantalla avisa que la
lectura quedó vieja en vez de mostrarla como si fuera de hoy.

La huella **ignora el día suelto**: que un aviso pase de 61 a 62 días no cambia
ninguna conclusión, y avisar por eso todos los días entrena a ignorar el aviso.
Los saltos de tramo, los mensajes nuevos y los cambios de etapa sí cuentan.

## La redacción asistida

Vive dentro de la ventana de redacción, al lado del selector de plantillas.

Las plantillas siguen siendo el camino principal para el primer mail: son
instantáneas, gratis y salen siempre igual. El asistente es para lo que una
plantilla no puede hacer —contestar lo que la empresa escribió— y para el primer
mail cuando el aviso dice algo puntual que vale la pena usar.

Hay un campo opcional para decirle qué querés decir («proponerle una reunión el
jueves»). Lo que escribas ahí tiene prioridad sobre su criterio: vos sabés cosas
del cliente que no están en la base.

**El borrador nunca se manda solo.** Cae en el formulario, editable, igual que el
de plantilla. Un mail que sale sin que nadie lo lea es la forma más rápida de
quemar un dominio.

## Reglas que tiene puestas

Están en `SISTEMA`, en `conviene.py` y en `escribir.py`, y son la parte del
código que más conviene leer antes de tocar:

- **Sólo lo que dice la ficha.** No inventa rondas de inversión, sueldos ni
  nombres.
- **Si hay poca información, lo dice** y baja la confianza. Un veredicto seguro
  apoyado en nada es peor que un «no sé».
- **Los días marcados con `~` son aproximados** y no se pueden decir como número
  exacto. Ese número termina en un mail al cliente: decirle «hace 92 días»
  cuando son entre 85 y 99 es una forma barata de quedar mal en la primera frase.
- **El mail abre por algo que la empresa reconoce como cierto sobre sí misma**,
  no por quiénes somos. Nada de «espero que estés muy bien» ni «somos una
  consultora líder».

## Si falla

Los errores se muestran en la pantalla del lead, con el motivo:

| Qué dice | Qué hacer |
|---|---|
| La clave no es válida o venció | Regenerala en la consola de Anthropic |
| La clave no tiene permiso para usar este modelo | Revisá el plan de la cuenta, o bajá el modelo |
| Está limitando el uso por volumen | Esperá un minuto |
| No se pudo llegar a la API | Red del servidor; si persiste, revisá si el hosting bloquea salidas |
| La respuesta quedó cortada por longitud | El lead tiene demasiados avisos o mensajes; es raro |

Nada de esto rompe el resto de la app: el score, el kanban y el envío de mails
siguen andando igual.
