"""Piezas de seguridad puras: sin FastAPI, sin base de datos, sin red.

Aqui vive todo lo que decide si una peticion es de fiar: contrasenas, tokens
de sesion, redirecciones, nombres de host y origen de los formularios. Esta
separado del resto para poder probarlo a fondo sin levantar la aplicacion.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import cache
from urllib.parse import urlsplit

# --------------------------------------------------------------------------
# Contrasenas
# --------------------------------------------------------------------------

# Parametros de scrypt. n=2**15 con r=8 cuesta unos 32 MB de memoria y del
# orden de 50-100 ms por intento: imperceptible al entrar, carisimo para
# quien intente probar millones de contrasenas con una copia de la base.
_N = 2**15
_R = 8
_P = 1
_MAXMEM = 64 * 1024 * 1024
_LONGITUD_CLAVE = 32

LONGITUD_MINIMA = 10


def _b64(datos: bytes) -> str:
    return base64.urlsafe_b64encode(datos).decode("ascii").rstrip("=")


def _desde_b64(texto: str) -> bytes:
    return base64.urlsafe_b64decode(texto + "=" * (-len(texto) % 4))


def hash_password(password: str) -> str:
    """Hash de una contrasena, con su sal y parametros incluidos.

    Formato: ``scrypt$n$r$p$sal$hash``. Guardar los parametros permite
    endurecerlos en el futuro sin invalidar las contrasenas existentes.
    """
    sal = secrets.token_bytes(16)
    derivada = hashlib.scrypt(
        password.encode("utf-8"),
        salt=sal,
        n=_N,
        r=_R,
        p=_P,
        maxmem=_MAXMEM,
        dklen=_LONGITUD_CLAVE,
    )
    return f"scrypt${_N}${_R}${_P}${_b64(sal)}${_b64(derivada)}"


def verificar_password(password: str, almacenado: str) -> bool:
    """Comprueba una contrasena contra su hash, en tiempo constante."""
    try:
        algoritmo, n, r, p, sal, esperado = almacenado.split("$")
        if algoritmo != "scrypt":
            return False
        esperado_bytes = _desde_b64(esperado)
        derivada = hashlib.scrypt(
            password.encode("utf-8"),
            salt=_desde_b64(sal),
            n=int(n),
            r=int(r),
            p=int(p),
            maxmem=_MAXMEM,
            dklen=len(esperado_bytes),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(derivada, esperado_bytes)


@cache
def _hash_ficticio() -> str:
    return hash_password(secrets.token_urlsafe(16))


def verificar_sin_usuario(password: str) -> bool:
    """Gasta el mismo tiempo que una verificacion real y devuelve False.

    Si un nombre de usuario inexistente se rechazase al instante, midiendo
    el tiempo de respuesta se podria averiguar que usuarios existen.
    """
    verificar_password(password, _hash_ficticio())
    return False


def problema_password(password: str, nombre_usuario: str = "") -> str | None:
    """Motivo por el que una contrasena no vale, o None si es aceptable.

    Se exige longitud y poco mas: las reglas de "una mayuscula y un simbolo"
    empujan a contrasenas cortas y predecibles. Una frase larga es mejor.
    """
    if len(password) < LONGITUD_MINIMA:
        return f"Debe tener al menos {LONGITUD_MINIMA} caracteres."
    if nombre_usuario and password.lower() == nombre_usuario.lower():
        return "No puede ser igual que el nombre de usuario."
    if len(set(password)) < 4:
        return "Es demasiado repetitiva."
    return None


# --------------------------------------------------------------------------
# Tokens de sesion
# --------------------------------------------------------------------------


def nuevo_token() -> str:
    """Token aleatorio para la cookie de sesion (256 bits)."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Lo que se guarda en la base en lugar del token.

    Si alguien se lleva una copia de la base de datos, los hashes no le
    sirven para suplantar ninguna sesion abierta.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# Redirecciones
# --------------------------------------------------------------------------


def ruta_segura(destino: str | None, por_defecto: str = "/") -> str:
    """Solo deja pasar rutas internas de la propia aplicacion.

    Evita que un enlace como ``/login?siguiente=https://web-falsa`` saque
    al usuario de la aplicacion justo despues de meter su contrasena.
    """
    if not destino:
        return por_defecto
    destino = destino.strip()
    if (
        not destino.startswith("/")
        # "//web-falsa" es una URL absoluta sin esquema.
        or destino.startswith("//")
        # Algunos navegadores tratan "\" como "/".
        or "\\" in destino
        or any(ord(c) < 32 for c in destino)
    ):
        return por_defecto
    partes = urlsplit(destino)
    if partes.scheme or partes.netloc:
        return por_defecto
    return destino


# --------------------------------------------------------------------------
# Hosts y origen de las peticiones
# --------------------------------------------------------------------------

#: Siempre permitidos: acceso desde el propio servidor y el healthcheck.
HOSTS_LOCALES = frozenset({"localhost", "127.0.0.1", "::1"})


def nombre_host(valor: str) -> str:
    """Quita el puerto y normaliza: 'Servidor.lan:8080' -> 'servidor.lan'."""
    valor = valor.strip().lower()
    if valor.startswith("["):
        # IPv6 con corchetes: [::1]:8080
        fin = valor.find("]")
        return valor[1:fin] if fin != -1 else valor
    if valor.count(":") == 1:
        return valor.split(":", 1)[0]
    return valor


def host_permitido(cabecera_host: str | None, permitidos: frozenset[str]) -> bool:
    """Protege contra DNS rebinding.

    Una web maliciosa puede hacer que su propio dominio apunte a la IP del
    servidor. El navegador la trataria entonces como "la misma web" y le
    dejaria leer las respuestas. Rechazar cualquier nombre que no sea uno
    de los esperados corta el ataque de raiz.
    """
    if not cabecera_host:
        return False
    return nombre_host(cabecera_host) in permitidos


METODOS_SEGUROS = frozenset({"GET", "HEAD", "OPTIONS"})


def origen_valido(
    metodo: str,
    origin: str | None,
    referer: str | None,
    cabecera_host: str | None,
    permitidos: frozenset[str],
) -> bool:
    """Protege contra CSRF: un formulario debe venir de la propia aplicacion.

    Los navegadores envian la cabecera Origin en todo POST entre sitios, asi
    que basta con comprobar que coincide con el servidor. Si no hay ni
    Origin ni Referer, no es un navegador (curl, un script): esos no son
    vector de CSRF y ademas necesitarian la cookie de sesion.
    """
    if metodo.upper() in METODOS_SEGUROS:
        return True

    fuente = origin or referer
    if not fuente:
        return True
    if fuente == "null":
        # Iframes aislados y redirecciones raras: nunca legitimo aqui.
        return False

    remitente = urlsplit(fuente).netloc.lower()
    if not remitente:
        return False
    if cabecera_host and remitente == cabecera_host.strip().lower():
        return True
    # Detras de un proxy (tailscale serve) la cabecera Host puede llegar
    # reescrita; entonces vale cualquier nombre de la lista de permitidos.
    return nombre_host(remitente) in permitidos


# --------------------------------------------------------------------------
# Limite de intentos de acceso
# --------------------------------------------------------------------------


@dataclass
class _Registro:
    fallos: int = 0
    ultimo_fallo: float = 0.0
    bloqueado_hasta: float = 0.0


class ControlIntentos:
    """Bloquea temporalmente un usuario tras varios fallos seguidos.

    Se cuenta por nombre de usuario y no por IP: detras de Tailscale o de un
    proxy todas las peticiones pueden llegar desde la misma direccion, y
    bloquear esa IP dejaria fuera a todo el mundo.

    Vive en memoria: reiniciar el contenedor lo pone a cero, que es
    aceptable para una aplicacion domestica.
    """

    def __init__(
        self,
        maximo: int = 5,
        bloqueo_s: float = 15 * 60,
        reloj: Callable[[], float] = time.monotonic,
    ) -> None:
        self.maximo = maximo
        self.bloqueo_s = bloqueo_s
        self._reloj = reloj
        self._registros: dict[str, _Registro] = {}

    @staticmethod
    def _clave(usuario: str) -> str:
        return usuario.strip().lower()

    def segundos_bloqueo(self, usuario: str) -> int:
        """Segundos que faltan para poder volver a intentarlo (0 = libre)."""
        registro = self._registros.get(self._clave(usuario))
        if registro is None:
            return 0
        restante = registro.bloqueado_hasta - self._reloj()
        return max(0, int(restante + 0.999))

    def fallo(self, usuario: str) -> None:
        ahora = self._reloj()
        registro = self._registros.setdefault(self._clave(usuario), _Registro())
        # Fallos antiguos no deben sumar con los nuevos.
        if ahora - registro.ultimo_fallo > self.bloqueo_s:
            registro.fallos = 0
        registro.fallos += 1
        registro.ultimo_fallo = ahora
        if registro.fallos >= self.maximo:
            registro.bloqueado_hasta = ahora + self.bloqueo_s
            registro.fallos = 0

    def exito(self, usuario: str) -> None:
        self._registros.pop(self._clave(usuario), None)


# --------------------------------------------------------------------------
# Cabeceras de respuesta
# --------------------------------------------------------------------------

#: Politica de contenido estricta. Funciona porque la interfaz no usa ni
#: scripts ni estilos en linea, ni carga nada de fuera: todo sale de /estatico.
POLITICA_CONTENIDO = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self'",
        # El favicon es un SVG en linea (data:).
        "img-src 'self' data:",
        "form-action 'self'",
        "frame-ancestors 'none'",
        "base-uri 'none'",
        "object-src 'none'",
    ]
)

CABECERAS_SEGURIDAD: dict[str, str] = {
    "Content-Security-Policy": POLITICA_CONTENIDO,
    # Nadie puede meter la aplicacion en un iframe para enganar clics.
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    # Datos medicos: que no queden copias en la cache del navegador, por
    # ejemplo en un movil prestado o un ordenador compartido.
    "Cache-Control": "no-store",
}
