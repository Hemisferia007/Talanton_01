/* Drag & drop del tablero. Sin dependencias: HTML5 drag events. */
(function () {
  const aviso = document.getElementById("aviso-guardado");
  let arrastrando = null;

  function mostrarGuardado(texto, esError) {
    if (!aviso) return;
    aviso.textContent = texto;
    aviso.className = esError ? "chip urgente" : "chip ok";
    aviso.style.visibility = "visible";
    clearTimeout(aviso._t);
    aviso._t = setTimeout(() => (aviso.style.visibility = "hidden"), 2200);
  }

  function actualizarCuentas() {
    document.querySelectorAll(".columna").forEach((col) => {
      const n = col.querySelectorAll(".tarjeta").length;
      col.querySelector(".cuenta").textContent = n;
      const vacio = col.querySelector(".vacio");
      if (n > 0 && vacio) vacio.remove();
      if (n === 0 && !vacio) {
        const p = document.createElement("p");
        p.className = "vacio";
        p.textContent = "Vacío";
        col.appendChild(p);
      }
    });
  }

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
    // Los links dentro de la tarjeta no deben disparar el arrastre.
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

      const origen = arrastrando.closest(".columna");
      const estado = columna.dataset.estado;
      if (origen === columna) return;

      // Movimiento optimista: se revierte si el servidor rechaza.
      columna.appendChild(arrastrando);
      actualizarCuentas();

      const posicion = Array.from(columna.querySelectorAll(".tarjeta")).indexOf(arrastrando);
      try {
        const r = await fetch(`/api/leads/${arrastrando.dataset.lead}/mover`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ estado, posicion }),
        });
        if (!r.ok) throw new Error(r.statusText);
        const datos = await r.json();
        mostrarGuardado("Movido a " + datos.etiqueta, false);
      } catch (err) {
        origen.appendChild(arrastrando);
        actualizarCuentas();
        mostrarGuardado("No se pudo guardar", true);
      }
    });
  });
})();
