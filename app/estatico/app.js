// Unico JavaScript de la aplicacion. Vive en un fichero y no en atributos
// onclick="..." para poder prohibir el JS en linea con la cabecera CSP:
// asi, aunque alguien consiguiera colar HTML en una pagina, no se ejecutaria.
//
// Todo funciona tambien sin JavaScript (hay botones <noscript> de respaldo).

document.addEventListener("DOMContentLoaded", () => {
  // En el movil los menus son una fila que se desliza: si la seccion
  // actual queda fuera de la pantalla (Ajustes, Documentos...), se desliza
  // hasta ella para que se vea donde estas. Sin JavaScript, simplemente
  // no se desliza.
  const activo = document.querySelector(".menus a.activo");
  if (activo) activo.scrollIntoView({ block: "nearest", inline: "nearest" });
});

document.addEventListener("change", (evento) => {
  // "+ Nuevo centro..." en el selector de centro de una cita: abre el
  // formulario de alta de debajo y pone el cursor en el nombre. Si luego se
  // elige otro centro, se cierra y se vacia: lo escrito ahi tiene prioridad
  // al guardar y crearia un centro sin querer.
  const selector = evento.target.closest("[data-centro-nuevo]");
  if (!selector) return;
  const alta = document.getElementById(selector.dataset.centroNuevo);
  if (!alta) return;
  if (selector.value === "nuevo") {
    alta.open = true;
    const nombre = alta.querySelector("input[name=centro_nuevo]");
    if (nombre) nombre.focus();
  } else {
    alta.open = false;
    alta.querySelectorAll("input").forEach((campo) => { campo.value = ""; });
  }
});

document.addEventListener("change", (evento) => {
  // Selectores y casillas que envian su formulario al cambiar.
  const campo = evento.target.closest("[data-autoenvio]");
  if (campo && campo.form) campo.form.submit();
});

document.addEventListener("submit", (evento) => {
  // Confirmacion antes de acciones que no se pueden deshacer.
  const mensaje = evento.target.dataset.confirmar;
  if (mensaje && !window.confirm(mensaje)) evento.preventDefault();
});

document.addEventListener("click", (evento) => {
  // "Cancelar": cierra el desplegable en el que esta, al lado del boton de
  // guardar, que es donde se busca. Sin JavaScript es un boton de tipo
  // reset, asi que al menos vacia lo escrito.
  const cerrar = evento.target.closest("[data-cerrar]");
  if (cerrar) {
    const panel = cerrar.closest("details");
    if (panel) panel.open = false;
  }
});

document.addEventListener("click", (evento) => {
  // Boton "Atras". El enlace lleva siempre un destino de verdad en href,
  // asi que si no hay historial (se entro por un enlace directo o desde
  // una notificacion) sigue funcionando como enlace normal.
  const atras = evento.target.closest("[data-atras]");
  if (atras && window.history.length > 1) {
    evento.preventDefault();
    window.history.back();
  }
});
