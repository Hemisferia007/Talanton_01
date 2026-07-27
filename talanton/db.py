"""Sesión y creación del esquema."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from .config import DATABASE_URL
from .models import Base, PerfilConsultora

engine = create_engine(
    DATABASE_URL,
    future=True,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
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
