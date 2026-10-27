"""Usuarios y sesiones: la parte de la autenticacion que toca la base.

Las decisiones delicadas (hash, tokens, limite de intentos) estan en
`seguridad.py`, probadas por separado. Aqui solo se guardan y se consultan.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlmodel import Session, delete, select

from . import seguridad
from .config import ahora, config
from .modelos import Sesion, Usuario

#: Fallos de acceso por usuario, compartido por toda la aplicacion.
intentos = seguridad.ControlIntentos()

#: Cada cuanto se prolonga una sesion en uso. Prolongarla en cada peticion
#: supondria una escritura en la base por cada pagina vista.
_PROLONGAR_CADA = timedelta(hours=12)


class ErrorAcceso(Exception):
    """Credenciales rechazadas. El mensaje es apto para el usuario."""


def hay_usuarios(sesion: Session) -> bool:
    return sesion.exec(select(Usuario.id)).first() is not None


def buscar_usuario(sesion: Session, nombre: str) -> Usuario | None:
    return sesion.exec(
        select(Usuario).where(Usuario.nombre == nombre.strip().lower())
    ).first()


# --------------------------------------------------------------------------
# Entrar y salir
# --------------------------------------------------------------------------


def autenticar(sesion: Session, nombre: str, password: str) -> Usuario:
    """Comprueba las credenciales o lanza ErrorAcceso.

    El mensaje de error es el mismo exista o no el usuario, para no
    confirmar a un atacante que nombres son validos.
    """
    espera = intentos.segundos_bloqueo(nombre)
    if espera:
        minutos = max(1, round(espera / 60))
        raise ErrorAcceso(
            f"Demasiados intentos fallidos. Prueba de nuevo en {minutos} min."
        )

    usuario = buscar_usuario(sesion, nombre)
    if usuario is None or not usuario.activo:
        seguridad.verificar_sin_usuario(password)
        valido = False
    else:
        valido = seguridad.verificar_password(password, usuario.hash_password)

    if not valido:
        intentos.fallo(nombre)
        raise ErrorAcceso("Usuario o contrasena incorrectos.")

    intentos.exito(nombre)
    return usuario


def abrir_sesion(sesion: Session, usuario: Usuario, agente: str | None) -> str:
    """Crea una sesion y devuelve el token para la cookie."""
    momento = ahora()

    # Limpieza de paso: las sesiones caducadas no sirven para nada.
    sesion.exec(delete(Sesion).where(Sesion.expira_en < momento))

    token = seguridad.nuevo_token()
    sesion.add(
        Sesion(
            hash_token=seguridad.hash_token(token),
            usuario_id=usuario.id,
            expira_en=momento + timedelta(days=config.dias_sesion),
            agente=(agente or "")[:200] or None,
        )
    )
    usuario.ultimo_acceso = momento
    sesion.add(usuario)
    sesion.commit()
    return token


def usuario_de_token(sesion: Session, token: str | None) -> Usuario | None:
    """El usuario dueno de una cookie de sesion, o None si no vale."""
    if not token:
        return None

    fila = sesion.exec(
        select(Sesion).where(Sesion.hash_token == seguridad.hash_token(token))
    ).first()
    if fila is None:
        return None

    momento = ahora()
    if fila.expira_en < momento:
        sesion.delete(fila)
        sesion.commit()
        return None

    usuario = sesion.get(Usuario, fila.usuario_id)
    if usuario is None or not usuario.activo:
        return None

    # Caducidad deslizante: mientras se use, la sesion no caduca.
    nueva_expiracion = momento + timedelta(days=config.dias_sesion)
    if nueva_expiracion - fila.expira_en > _PROLONGAR_CADA:
        fila.expira_en = nueva_expiracion
        sesion.add(fila)
        sesion.commit()

    return usuario


def cerrar_sesion(sesion: Session, token: str | None) -> None:
    if not token:
        return
    sesion.exec(
        delete(Sesion).where(Sesion.hash_token == seguridad.hash_token(token))
    )
    sesion.commit()


# --------------------------------------------------------------------------
# Gestion de usuarios (desde scripts/usuario.py)
# --------------------------------------------------------------------------


def crear_usuario(sesion: Session, nombre: str, password: str) -> Usuario:
    nombre = nombre.strip().lower()
    if not nombre:
        raise ValueError("El nombre de usuario no puede estar vacio.")
    if buscar_usuario(sesion, nombre) is not None:
        raise ValueError(f"Ya existe un usuario llamado '{nombre}'.")
    problema = seguridad.problema_password(password, nombre)
    if problema:
        raise ValueError(problema)

    usuario = Usuario(nombre=nombre, hash_password=seguridad.hash_password(password))
    sesion.add(usuario)
    sesion.commit()
    sesion.refresh(usuario)
    return usuario


def cambiar_password(sesion: Session, nombre: str, password: str) -> None:
    """Cambia la contrasena y cierra todas las sesiones de ese usuario.

    Si se cambia porque se sospecha que alguien la conoce, no serviria de
    nada dejar abiertas las sesiones que ese alguien ya tuviera.
    """
    usuario = buscar_usuario(sesion, nombre)
    if usuario is None:
        raise ValueError(f"No existe el usuario '{nombre}'.")
    problema = seguridad.problema_password(password, usuario.nombre)
    if problema:
        raise ValueError(problema)

    usuario.hash_password = seguridad.hash_password(password)
    sesion.add(usuario)
    sesion.exec(delete(Sesion).where(Sesion.usuario_id == usuario.id))
    sesion.commit()


def borrar_usuario(sesion: Session, nombre: str) -> None:
    usuario = buscar_usuario(sesion, nombre)
    if usuario is None:
        raise ValueError(f"No existe el usuario '{nombre}'.")
    sesion.exec(delete(Sesion).where(Sesion.usuario_id == usuario.id))
    sesion.delete(usuario)
    sesion.commit()


def cerrar_todas_las_sesiones(sesion: Session) -> int:
    """Expulsa a todo el mundo. Util si se pierde un movil."""
    resultado = sesion.exec(delete(Sesion))
    sesion.commit()
    return resultado.rowcount or 0
