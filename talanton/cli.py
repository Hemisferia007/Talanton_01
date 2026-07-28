"""CLI de Talanton.

    python -m talanton.cli init         crea la base
    python -m talanton.cli usuario      crea un usuario para entrar
    python -m talanton.cli descubrir    arma fuentes.json sondeando ATS
    python -m talanton.cli seed         carga datos de demo
    python -m talanton.cli ingestar     corre la ingesta (fuentes.json)
    python -m talanton.cli enriquecer   busca contactos en los avisos
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
        # No es un error: un despliegue nuevo todavía no tiene fuentes. Salir
        # con 1 dejaría el cron en rojo todos los días por algo que sólo se
        # arregla desde la web, y una alarma que siempre suena no es una alarma.
        # El panel ya avisa que la ingesta no está trayendo nada.
        print("No hay fuentes configuradas todavía. Cargalas en la pantalla Fuentes.")
        return 0

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


def _descubrir(args) -> int:
    from pathlib import Path

    from .ingest.descubridor import descubrir, escribir_fuentes, leer_empresas

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    archivo = Path(args.empresas)
    if not archivo.exists():
        print(f"No existe {archivo}. Formato: una empresa por línea, 'Nombre, dominio.com.ar'.")
        return 1

    empresas = leer_empresas(archivo)
    if not empresas:
        print(f"{archivo} está vacío.")
        return 1

    print(f"Sondeando {len(empresas)} empresas en {len(['greenhouse','lever','ashby','recruitee','workable'])} plataformas…\n")
    reporte = descubrir(empresas, pausa=args.pausa, probar_pagina=not args.sin_pagina)

    print(f"\n{'='*60}")
    print(f"Encontradas: {len(reporte.encontradas)} fuentes, {reporte.total_avisos} avisos hoy")
    for h in reporte.encontradas:
        print(f"  ✓ {h.empresa}: {h.plataforma}/{h.slug_o_url} ({h.avisos} avisos)")

    if reporte.sin_suerte:
        print(f"\nSin fuente automática: {len(reporte.sin_suerte)}")
        for s in reporte.sin_suerte:
            print(f"  · {s}")
        print("  → Para estas hay que buscar la página de carrera a mano.")

    if reporte.errores:
        print(f"\nErrores: {len(reporte.errores)}")
        for e in reporte.errores:
            print(f"  ✗ {e}")

    if reporte.encontradas:
        nuevas = escribir_fuentes(reporte, Path(args.salida), fusionar=not args.reemplazar)
        print(f"\n{nuevas} fuentes nuevas escritas en {args.salida}")
        print("Probalas con: python -m talanton.cli ingestar")
    return 0


def _enriquecer(args) -> int:
    from .enriquecer import correr

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    init_db()
    with get_session() as session:
        resumen = correr(session, verificar_dns=not args.sin_dns, limite=args.limite)

    print(f"Empresas revisadas:   {resumen.empresas_revisadas}")
    print(f"Contactos nuevos:     {resumen.contactos_nuevos}")
    print(f"Decisores marcados:   {resumen.decisores_marcados}")
    if resumen.empresas_revisadas and not resumen.contactos_nuevos:
        print(
            "\nNingún aviso traía email de contacto. Es normal en portales que "
            "ocultan el dato; hay que buscarlos en la página de carrera."
        )
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

    descubrir = sub.add_parser(
        "descubrir", help="sondea ATS y páginas de carrera para armar fuentes.json"
    )
    descubrir.add_argument(
        "--empresas",
        default="empresas.txt",
        help="archivo con una empresa por línea: 'Nombre, dominio.com.ar'",
    )
    descubrir.add_argument("--salida", default="fuentes.json")
    descubrir.add_argument(
        "--pausa", type=float, default=0.5, help="segundos entre pedidos (default 0.5)"
    )
    descubrir.add_argument(
        "--sin-pagina", action="store_true", help="no sondear páginas de carrera"
    )
    descubrir.add_argument(
        "--reemplazar", action="store_true", help="pisar fuentes.json en vez de fusionar"
    )
    descubrir.set_defaults(fn=_descubrir)

    enriquecer = sub.add_parser(
        "enriquecer", help="busca contactos y decisores en los avisos ya cargados"
    )
    enriquecer.add_argument("--limite", type=int, help="máximo de empresas a revisar")
    enriquecer.add_argument(
        "--sin-dns", action="store_true", help="no verificar que el dominio resuelva"
    )
    enriquecer.set_defaults(fn=_enriquecer)

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
