/* La lectura del lead tarda varios segundos. Sin esto el formulario se envía y
   la pantalla se queda igual, y la reacción natural es apretar de nuevo. */
(function () {
  const forma = document.getElementById("forma-opinion");
  if (!forma) return;

  const boton = document.getElementById("boton-opinion");
  const estado = document.getElementById("estado-opinion");

  forma.addEventListener("submit", () => {
    if (boton) boton.disabled = true;
    if (estado) {
      estado.textContent =
        "Leyendo el lead… tarda unos segundos. La página se recarga sola cuando termina.";
    }
  });
})();
