/* Ventana de redacción.
   El <dialog> nativo ya resuelve foco atrapado, Esc y fondo inerte; acá sólo
   queda abrir/cerrar y recargar el borrador cuando cambia la plantilla. */
(function () {
  const dialogo = document.getElementById("redactar");
  if (!dialogo) return;

  const abrir = document.getElementById("abrir-redactar");
  const selPlantilla = document.getElementById("m-plantilla");
  const selCuenta = document.getElementById("m-cuenta");
  const campoPara = document.getElementById("m-para");
  const campoAsunto = document.getElementById("m-asunto");
  const campoCuerpo = document.getElementById("m-cuerpo");
  const estado = document.getElementById("estado-redaccion");
  const ayuda = document.getElementById("ayuda-plantilla");

  function avisar(texto) {
    if (estado) estado.textContent = texto || "";
  }

  if (abrir) {
    abrir.addEventListener("click", () => {
      dialogo.showModal();
      // El asunto suele venir bien; lo que se retoca es el cuerpo.
      campoCuerpo.focus();
      campoCuerpo.setSelectionRange(0, 0);
    });
  }

  dialogo.querySelectorAll("[data-cerrar-ventana]").forEach((b) =>
    b.addEventListener("click", () => dialogo.close())
  );

  // Clic sobre el backdrop (fuera del formulario) cierra, como en Gmail.
  dialogo.addEventListener("click", (e) => {
    if (e.target === dialogo) dialogo.close();
  });

  async function recargarBorrador() {
    const leadId = selPlantilla.dataset.lead;
    const parametros = new URLSearchParams({ plantilla: selPlantilla.value });
    if (selCuenta && selCuenta.value) parametros.set("cuenta_id", selCuenta.value);

    avisar("Reescribiendo el borrador…");
    try {
      const r = await fetch(`/leads/${leadId}/redactar?${parametros}`);
      if (!r.ok) throw new Error(r.statusText);
      const datos = await r.json();
      if (!campoPara.value) campoPara.value = datos.para;
      campoAsunto.value = datos.asunto;
      campoCuerpo.value = datos.cuerpo;
      const opcion = selPlantilla.selectedOptions[0];
      avisar("Borrador actualizado: " + (opcion ? opcion.textContent.trim() : ""));
    } catch (err) {
      avisar("No se pudo cargar la plantilla. Escribilo a mano.");
    }
  }

  if (selPlantilla) {
    selPlantilla.addEventListener("change", () => {
      if (ayuda) ayuda.textContent = "";
      recargarBorrador();
    });
  }
  if (selCuenta) selCuenta.addEventListener("change", recargarBorrador);

  dialogo.querySelector("form").addEventListener("submit", () => {
    avisar("Enviando…");
    dialogo.querySelector('button[type="submit"]').disabled = true;
  });
})();
