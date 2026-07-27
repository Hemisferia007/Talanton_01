"""Sesión y creación del esquema."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session, sessionmaker

from .config import BASE_DIR, DATABASE_URL
from .models import Base, PerfilConsultora

log = logging.getLogger("talanton.db")

def _url_normalizada(url: str) -> str:
    """Acepta las URL que entregan los hostings.

    Muchos exportan `postgres://`, que SQLAlchemy no reconoce, y sin driver
    explícito buscaría psycopg2 en lugar de psycopg 3.
    """
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


URL_EFECTIVA = _url_normalizada(DATABASE_URL)
ES_SQLITE = URL_EFECTIVA.startswith("sqlite")

engine = create_engine(
    URL_EFECTIVA,
    future=True,
    # SQLite: la conexión se comparte entre los hilos de uvicorn.
    connect_args={"check_same_thread": False} if ES_SQLITE else {},
    # Postgres: reciclar conexiones evita las que el servidor ya cerró.
    **({} if ES_SQLITE else {"pool_pre_ping": True, "pool_recycle": 1800}),
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _marcar_en_head() -> None:
    """Deja la base recién creada apuntando a la última migración.

    Sin esto, `alembic upgrade` intentaría después crear tablas que ya existen.
    """
    try:
        from alembic import command
        from alembic.config import Config

        ini = BASE_DIR / "alembic.ini"
        if not ini.exists():
            return
        cfg = Config(str(ini))
        cfg.set_main_option("sqlalchemy.url", URL_EFECTIVA.replace("%", "%%"))
        command.stamp(cfg, "head")
    except Exception as exc:  # no vale la pena romper el arranque por esto
        log.warning("No se pudo marcar la base en head de Alembic: %s", exc)


def init_db() -> None:
    """Crea el esquema si la base está vacía.

    En producción las migraciones las corre `alembic upgrade head` antes de
    levantar el servidor; esto es para desarrollo y para el primer arranque.
    """
    inspector = inspect(engine)
    base_vacia = not inspector.has_table("usuarios")

    Base.metadata.create_all(engine)
    if base_vacia:
        _marcar_en_head()

    with SessionLocal() as s:
        from .auth import crear_admin_inicial

        crear_admin_inicial(s)

        if s.scalar(select(PerfilConsultora).limit(1)) is None:
            s.add(
                PerfilConsultora(
                    nombre="Talanton",
                    descripcion="Consultora de RRHH especializada en selección.",
                    paises_objetivo="AR,UY,CL,MX,CO",
                )
            )
            s.commit()


@contextmanager
def get_session() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def db_dependency() -> Iterator[Session]:
    """Dependencia de FastAPI."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
