#!/usr/bin/env python3
"""Gestion de usuarios desde la consola del servidor.

    docker compose exec medicos python scripts/usuario.py crear NOMBRE
    docker compose exec medicos python scripts/usuario.py password NOMBRE
    docker compose exec medicos python scripts/usuario.py listar
    docker compose exec medicos python scripts/usuario.py borrar NOMBRE
    docker compose exec medicos python scripts/usuario.py cerrar-sesiones

La contrasena se pide por teclado y no se muestra. Para automatizarlo, se
puede pasar por la entrada estandar con --password-stdin.

No hay pagina de registro en la web a proposito: en un servidor accesible
desde la red, cualquiera de la red podria darse de alta.
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import Session, select  # noqa: E402

from app import autenticacion  # noqa: E402
from app.db import crear_tablas, motor  # noqa: E402
from app.modelos import Sesion, Usuario  # noqa: E402
from app.seguridad import LONGITUD_MINIMA  # noqa: E402


def _pedir_password(desde_stdin: bool) -> str:
    if desde_stdin:
        return sys.stdin.readline().rstrip("\n")

    print(
        f"Minimo {LONGITUD_MINIMA} caracteres. Una frase larga es mas segura "
        "y mas facil de recordar que una palabra con simbolos."
    )
    primera = getpass.getpass("Contrasena: ")
    segunda = getpass.getpass("Repitela:   ")
    if primera != segunda:
        raise ValueError("Las contrasenas no coinciden.")
    return primera


def main() -> int:
    analizador = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = analizador.add_subparsers(dest="orden", required=True)

    for orden, ayuda in (
        ("crear", "da de alta un usuario"),
        ("password", "cambia la contrasena y cierra sus sesiones"),
        ("borrar", "elimina un usuario"),
    ):
        p = sub.add_parser(orden, help=ayuda)
        p.add_argument("nombre")
        if orden != "borrar":
            p.add_argument("--password-stdin", action="store_true")

    sub.add_parser("listar", help="muestra los usuarios y sus sesiones abiertas")
    sub.add_parser(
        "cerrar-sesiones",
        help="expulsa a todo el mundo (por ejemplo, si se pierde un movil)",
    )

    args = analizador.parse_args()
    crear_tablas()

    try:
        with Session(motor) as sesion:
            if args.orden == "crear":
                password = _pedir_password(args.password_stdin)
                usuario = autenticacion.crear_usuario(sesion, args.nombre, password)
                print(f"Usuario '{usuario.nombre}' creado.")

            elif args.orden == "password":
                password = _pedir_password(args.password_stdin)
                autenticacion.cambiar_password(sesion, args.nombre, password)
                print("Contrasena cambiada. Sus sesiones abiertas se han cerrado.")

            elif args.orden == "borrar":
                autenticacion.borrar_usuario(sesion, args.nombre)
                print(f"Usuario '{args.nombre}' eliminado.")

            elif args.orden == "listar":
                usuarios = sesion.exec(select(Usuario).order_by(Usuario.nombre)).all()
                if not usuarios:
                    print("No hay usuarios.")
                for u in usuarios:
                    abiertas = len(
                        sesion.exec(select(Sesion).where(Sesion.usuario_id == u.id)).all()
                    )
                    acceso = u.ultimo_acceso.strftime("%d/%m/%Y %H:%M") if u.ultimo_acceso else "nunca"
                    print(f"{u.nombre:<20} ultimo acceso: {acceso:<17} sesiones abiertas: {abiertas}")

            elif args.orden == "cerrar-sesiones":
                n = autenticacion.cerrar_todas_las_sesiones(sesion)
                print(f"{n} sesion(es) cerradas. Todo el mundo tendra que volver a entrar.")

    except ValueError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print("\nCancelado.", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
