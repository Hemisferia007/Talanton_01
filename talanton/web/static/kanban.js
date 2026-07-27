/* Tablero: drag & drop con mouse y selector de estado por teclado.
   Sin dependencias. El drag es el atajo; el <select> es el camino accesible,
   y los dos pegan contra el mismo endpoint. */
(function () {
  const aviso = document.getElementById("aviso-guardado");
  let arrastrando = null;

  function anunciar(texto, esError) {
    if (!aviso) return;
    aviso.className = "aviso chip " + (esError ? "urgente" : "ok");
    aviso.textContent = texto;
    clearTimeout(aviso._t);
    aviso._t = setTimeout(() => (aviso.textContent = ""), 4000);
  }

  function columnaDe(estado) {
    return document.querySelector(`.columna[data-estado="${estado}"]`);
  }

  function actualizarCuentas() {
    document.querySelectorAll(".columna").forEach((col) => {
      const n = col.querySelectorAll(".tarjeta").length;
      col.querySelector(".cuenta").innerHTML = n + '<span class="sr-solo"> leads</span>';
      const vacio = col.querySelector(".vacio");
      if (n > 0 && vacio) vacio.remove();
      if (n === 0 && !vacio) {
        const p = document.createElement("p");
        p.className = "vacio";
        p.textContent = "Sin leads";
        col.appendChild(p);
      }
    });
  }

  async function guardar(leadId, estado, posicion) {
    const r = await fetch(`/api/leads/${leadId}/mover`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ estado, posicion }),
    });
    if (!r.ok) throw new Error(r.statusText);
    return r.json();
  }

  function sincronizarSelector(tarjeta, estado) {
    const select = tarjeta.querySelector(".selector-estado");
    if (select) select.value = estado;
  }

  /* --- Drag & drop --- */

  document.querySelectorAll(".tarjeta").forEach((tarjeta) => {
    tarjeta.addEventListener("dragstart", (e) => {
      arrastrando = tarjeta;
      tarjeta.classList.add("arrastrando");
      e.dataTransfer.effectAllowed = "move";
      // Firefox exige que se setee algo para iniciar el arrastre.
      e.dataTransfer.setData("text/plain", tarjeta.dataset.lead);
    });
    tarjeta.addEventListener("dragend", () => {
      tarjeta.classList.remove("arrastrando");
      arrastrando = null;
    });
    // Los controles internos no deben disparar el arrastre.
    tarjeta.querySelectorAll("a").forEach((a) => (a.draggable = false));
  });

  document.querySelectorAll(".columna").forEach((columna) => {
    columna.addEventListener("dragover", (e) => {
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      columna.classList.add("sobre");
    });
    columna.addEventListener("dragleave", () => columna.classList.remove("sobre"));

    columna.addEventListener("drop", async (e) => {
      e.preventDefault();
      columna.classList.remove("sobre");
      if (!arrastrando) return;

      const tarjeta = arrastrando;
      const origen = tarjeta.closest(".columna");
      if (origen === columna) return;

      // Movimiento optimista: se revierte si el servidor lo rechaza.
      columna.appendChild(tarjeta);
      actualizarCuentas();
      const posicion = Array.from(columna.querySelectorAll(".tarjeta")).indexOf(tarjeta);

      try {
        const datos = await guardar(tarjeta.dataset.lead, columna.dataset.estado, posicion);
        sincronizarSelector(tarjeta, datos.estado);
        anunciar("Movido a " + datos.etiqueta, false);
      } catch (err) {
        origen.appendChild(tarjeta);
        actualizarCuentas();
        sincronizarSelector(tarjeta, origen.dataset.estado);
        anunciar("No se pudo guardar el cambio", true);
      }
    });
  });

  /* --- Selector de estado (teclado y lectores de pantalla) --- */

  document.querySelectorAll(".selector-estado").forEach((select) => {
    let anterior = select.value;
    select.addEventListener("change", async () => {
      const tarjeta = select.closest(".tarjeta");
      const origen = tarjeta.closest(".columna");
      const destino = columnaDe(select.value);
      if (!destino || destino === origen) {
        anterior = select.value;
        return;
      }

      select.disabled = true;
      try {
        const datos = await guardar(tarjeta.dataset.lead, select.value, null);
        destino.appendChild(tarjeta);
        actualizarCuentas();
        anterior = select.value;
        anunciar("Movido a " + datos.etiqueta, false);
      } catch (err) {
        select.value = anterior;
        anunciar("No se pudo guardar el cambio", true);
      } finally {
        // Reactivar antes de enfocar: un control deshabilitado no toma foco,
        // y mover la tarjeta de columna lo perdería.
        select.disabled = false;
        select.focus();
      }
    });
  });
})();
