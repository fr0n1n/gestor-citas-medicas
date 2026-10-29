"""Iconos de la interfaz, dibujados en SVG dentro del propio HTML.

Sustituyen a los emojis (☎ 🚑 📎...): cada sistema dibuja un emoji a su
manera y en sus colores, y no siguen el color del texto. Estos son de trazo
fino, del color del texto (se adaptan solos al modo oscuro) y no cargan
nada de fuera (la CSP no lo permitiria y la app tiene que ir sin internet).

Trazados de Tabler Icons (https://tabler.io/icons), con licencia MIT:

    MIT License. Copyright (c) 2020-2026 Pawel Kuna

    Permission is hereby granted, free of charge, to any person obtaining a
    copy of this software and associated documentation files (the
    "Software"), to deal in the Software without restriction, including
    without limitation the rights to use, copy, modify, merge, publish,
    distribute, sublicense, and/or sell copies of the Software, and to
    permit persons to whom the Software is furnished to do so, subject to
    the following conditions: The above copyright notice and this
    permission notice shall be included in all copies or substantial
    portions of the Software. THE SOFTWARE IS PROVIDED "AS IS", WITHOUT
    WARRANTY OF ANY KIND, EXPRESS OR IMPLIED.
"""

from __future__ import annotations

from markupsafe import Markup

ICONOS: dict[str, tuple[str, ...]] = {
    "telefono": ("M5 4h4l2 5l-2.5 1.5a11 11 0 0 0 5 5l1.5 -2.5l5 2v4a2 2 0 0 1 -2 2a16 16 0 0 1 -15 -15a2 2 0 0 1 2 -2",),
    "ambulancia": (
        "M5 17m-2 0a2 2 0 1 0 4 0a2 2 0 1 0 -4 0",
        "M17 17m-2 0a2 2 0 1 0 4 0a2 2 0 1 0 -4 0",
        "M5 17h-2v-11a1 1 0 0 1 1 -1h9v12m-4 0h6m4 0h2v-6h-8m0 -5h5l3 5",
        "M6 10h4m-2 -2v4",
    ),
    "clip": ("M15 7l-6.5 6.5a1.5 1.5 0 0 0 3 3l6.5 -6.5a3 3 0 0 0 -6 -6l-6.5 6.5a4.5 4.5 0 0 0 9 9l6.5 -6.5",),
    "lista": (
        "M9 5h-2a2 2 0 0 0 -2 2v12a2 2 0 0 0 2 2h10a2 2 0 0 0 2 -2v-12a2 2 0 0 0 -2 -2h-2",
        "M9 5a2 2 0 0 1 2 -2h2a2 2 0 0 1 2 2a2 2 0 0 1 -2 2h-2a2 2 0 0 1 -2 -2z",
        "M9 12h6", "M9 16h6",
    ),
    "mensaje": ("M8 9h8", "M8 13h6", "M18 4a3 3 0 0 1 3 3v8a3 3 0 0 1 -3 3h-5l-5 3v-3h-2a3 3 0 0 1 -3 -3v-8a3 3 0 0 1 3 -3h12z"),
    "documento": ("M14 3v4a1 1 0 0 0 1 1h4", "M17 21h-10a2 2 0 0 1 -2 -2v-14a2 2 0 0 1 2 -2h7l5 5v11a2 2 0 0 1 -2 2z"),
    "editar": ("M4 20h4l10.5 -10.5a2.828 2.828 0 1 0 -4 -4l-10.5 10.5v4", "M13.5 6.5l4 4"),
    "aviso": (
        "M12 9v4",
        "M10.363 3.591l-8.106 13.534a1.914 1.914 0 0 0 1.636 2.871h16.214a1.914 1.914 0 0 0 1.636 -2.87l-8.106 -13.536a1.914 1.914 0 0 0 -3.274 0z",
        "M12 16h.01",
    ),
    "pantalla": ("M3 5a1 1 0 0 1 1 -1h16a1 1 0 0 1 1 1v10a1 1 0 0 1 -1 1h-16a1 1 0 0 1 -1 -1v-10z", "M7 20h10", "M9 16v4", "M15 16v4"),
    "sol": ("M8 12a4 4 0 1 0 8 0a4 4 0 1 0 -8 0", "M3 12h1m8 -9v1m8 8h1m-9 8v1m-6.4 -15.4l.7 .7m12.1 -.7l-.7 .7m0 11.4l.7 .7m-12.1 -.7l-.7 .7"),
    "luna": ("M12 3c.132 0 .263 0 .393 0a7.5 7.5 0 0 0 7.92 12.446a9 9 0 1 1 -8.313 -12.454z",),
    "destello": ("M16 18a2 2 0 0 1 2 2a2 2 0 0 1 2 -2a2 2 0 0 1 -2 -2a2 2 0 0 1 -2 2zm0 -12a2 2 0 0 1 2 2a2 2 0 0 1 2 -2a2 2 0 0 1 -2 -2a2 2 0 0 1 -2 2zm-7 12a6 6 0 0 1 6 -6a6 6 0 0 1 -6 -6a6 6 0 0 1 -6 6a6 6 0 0 1 6 6z",),
    "reloj": ("M3 12a9 9 0 1 0 18 0a9 9 0 0 0 -18 0", "M12 7v5l3 3"),
}


def icono(nombre: str) -> Markup:
    """El SVG de un icono, listo para la plantilla: {{ icono('telefono') }}.

    Decorativo (aria-hidden): el texto de al lado ya dice lo que es. Un
    nombre que no existe falla en el acto, en vez de pintar un hueco.
    """
    trazos = "".join(f'<path d="{d}"/>' for d in ICONOS[nombre])
    return Markup(
        '<svg class="ico" viewBox="0 0 24 24" aria-hidden="true" focusable="false" '
        'fill="none" stroke="currentColor" stroke-width="2" '
        f'stroke-linecap="round" stroke-linejoin="round">{trazos}</svg>'
    )
