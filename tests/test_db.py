"""Tests de la capa de base: normalización de URL y migraciones."""

import subprocess
import sys
from pathlib import Path

import pytest

from talanton.db import _url_normalizada

RAIZ = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize(
    "entrada,esperado",
    [
        # Varios hostings entregan `postgres://`, que SQLAlchemy no reconoce.
        ("postgres://u:p@host/db", "postgresql+psycopg://u:p@host/db"),
        # Sin driver explícito buscaría psycopg2 en vez de psycopg 3.
        ("postgresql://u:p@host/db", "postgresql+psycopg://u:p@host/db"),
        # Si ya viene con driver, no se toca.
        ("postgresql+psycopg://u:p@host/db", "postgresql+psycopg://u:p@host/db"),
        ("sqlite:///data/talanton.db", "sqlite:///data/talanton.db"),
    ],
)
def test_normalizacion_de_url(entrada, esperado):
    assert _url_normalizada(entrada) == esperado


def test_la_contrasena_con_caracteres_raros_sobrevive():
    url = "postgres://u:p%40ss%2Fword@host:5432/db"
    assert _url_normalizada(url) == "postgresql+psycopg://u:p%40ss%2Fword@host:5432/db"


def _alembic(argumentos, url):
    import os

    entorno = {**os.environ, "TALANTON_DATABASE_URL": url}
    return subprocess.run(
        [sys.executable, "-m", "alembic", *argumentos],
        cwd=RAIZ,
        env=entorno,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_la_migracion_compila_para_postgres():
    """Se renderiza el DDL sin conectarse: verifica el dialecto de producción
    aunque no haya un Postgres a mano."""
    r = _alembic(["upgrade", "head", "--sql"], "postgresql://u:p@localhost/talanton")
    assert r.returncode == 0, r.stderr
    assert "CREATE TABLE usuarios" in r.stdout
    assert "CREATE TABLE mensajes" in r.stdout
    # SERIAL confirma que se resolvió el dialecto de Postgres, no el de SQLite.
    assert "SERIAL" in r.stdout


def test_la_migracion_corre_de_verdad_en_sqlite(tmp_path):
    url = f"sqlite:///{tmp_path / 'migrada.db'}"
    r = _alembic(["upgrade", "head"], url)
    assert r.returncode == 0, r.stderr

    import sqlite3

    tablas = {
        fila[0]
        for fila in sqlite3.connect(tmp_path / "migrada.db").execute(
            "select name from sqlite_master where type='table'"
        )
    }
    assert {"usuarios", "leads", "vacantes", "mensajes", "cuentas_gmail"} <= tablas


def test_no_quedan_cambios_de_modelo_sin_migrar(tmp_path):
    """Si alguien agrega una columna y se olvida de generar la migración, este
    test lo agarra antes de que el deploy falle."""
    url = f"sqlite:///{tmp_path / 'comparar.db'}"
    assert _alembic(["upgrade", "head"], url).returncode == 0

    r = _alembic(["check"], url)
    assert r.returncode == 0, (
        "El esquema de models.py no coincide con las migraciones. "
        "Generá una con: alembic revision --autogenerate -m 'descripción'\n"
        f"{r.stdout}\n{r.stderr}"
    )
