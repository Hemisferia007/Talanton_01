"""CLI de Talanton.

    python -m talanton.cli init         crea la base
    python -m talanton.cli usuario      crea un usuario para entrar
    python -m talanton.cli seed         carga datos de demo
    python -m talanton.cli ingestar     corre la ingesta (fuentes.json)
    python -m talanton.cli recalcular   recalcula todos los scores
    python -m talanton.cli servir       levanta la web en localhost:8000
"""

from __future__ import annotations

import argparse
import logging
import sys

from .db import get_session, init_db


def _init(_args) -> int:
    init_db()
    print("Base creada.")
    return 0


def _seed(_args) -> int:
    from .seed import sembrar

    init_db()
    with get_session() as session:
        sembrar(session)
    print("Datos de demo cargados. Levantá la web con: python -m talanton.cli servir")
    return 0


def _ingestar(args) -> int:
    from .ingest.runner import correr

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    init_db()
    with get_session() as session:
        resultados = correr(session)

    if not resultados:
        print("No hay fuentes configuradas. Editá fuentes.json.")
        return 1

    fallidos = 0
    for r in resultados:
        if r.error:
            fallidos += 1
            print(f"  ✗ {r.conector}: {r.error}")
        else:
            print(
                f"  ✓ {r.conector}: {r.encontradas} encontradas, "
                f"{r.nuevas} nuevas, {r.cerradas} cerradas"
            )
    return 1 if fallidos == len(resultados) else 0


def _recalcular(_args) -> int:
    from .services import recalcular_todos

    init_db()
    with get_session() as session:
        total = recalcular_todos(session)
    print(f"{total} leads recalculados.")
    return 0


def _usuario(args) -> int:
    import getpass

    from . import auth

    init_db()
    email = args.email or input("Email: ").strip()
    nombre = args.nombre or input("Nombre: ").strip()
    password = args.password or getpass.getpass("Contraseña (mínimo 10 caracteres): ")

    with get_session() as session:
        try:
            usuario = auth.crear_usuario(session, email, nombre, password)
        except ValueError as exc:
            print(f"Error: {exc}")
            return 1
        print(f"Usuario {usuario.email} creado.")
    return 0


def _servir(args) -> int:
    import uvicorn

    init_db()
    uvicorn.run("talanton.web.app:app", host=args.host, port=args.port, reload=args.reload)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="talanton", description=__doc__)
    sub = parser.add_subparsers(dest="comando", required=True)

    sub.add_parser("init", help="crea el esquema de la base").set_defaults(fn=_init)
    sub.add_parser("seed", help="carga datos de demo").set_defaults(fn=_seed)
    sub.add_parser("ingestar", help="corre la ingesta diaria").set_defaults(fn=_ingestar)
    sub.add_parser("recalcular", help="recalcula los scores").set_defaults(fn=_recalcular)

    usuario = sub.add_parser("usuario", help="crea un usuario para entrar a la web")
    usuario.add_argument("--email")
    usuario.add_argument("--nombre")
    usuario.add_argument(
        "--password",
        help="si se omite, se pide por consola sin mostrarla (preferible: no queda en el historial)",
    )
    usuario.set_defaults(fn=_usuario)

    servir = sub.add_parser("servir", help="levanta la web")
    servir.add_argument("--host", default="127.0.0.1")
    servir.add_argument("--port", type=int, default=8000)
    servir.add_argument("--reload", action="store_true")
    servir.set_defaults(fn=_servir)

    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
