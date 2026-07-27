from __future__ import annotations

import os
import tempfile
from pathlib import Path

# La base se resuelve en tiempo de import, así que hay que apuntarla antes de
# importar cualquier módulo de talanton.
_TMP = Path(tempfile.mkdtemp(prefix="talanton-tests-"))
os.environ["TALANTON_DATA_DIR"] = str(_TMP)
os.environ["TALANTON_DATABASE_URL"] = f"sqlite:///{_TMP / 'test.db'}"

import pytest  # noqa: E402

from talanton.db import SessionLocal, init_db  # noqa: E402
from talanton.models import Base  # noqa: E402
from talanton.db import engine  # noqa: E402


@pytest.fixture()
def session():
    Base.metadata.drop_all(engine)
    init_db()
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def session_con_demo(session):
    from talanton.seed import sembrar

    sembrar(session)
    return session


EMAIL_PRUEBA = "test@talanton.com.ar"
PASSWORD_PRUEBA = "contrasena-de-prueba"


@pytest.fixture()
def usuario(session):
    from talanton import auth

    u = auth.crear_usuario(session, EMAIL_PRUEBA, "Usuaria de prueba", PASSWORD_PRUEBA)
    session.commit()
    return u


@pytest.fixture()
def cliente(session_con_demo, usuario):
    """Cliente ya logueado. Toda la app exige sesión."""
    from fastapi.testclient import TestClient

    from talanton.web.app import app

    c = TestClient(app)
    respuesta = c.post(
        "/login",
        data={"email": EMAIL_PRUEBA, "password": PASSWORD_PRUEBA},
        follow_redirects=False,
    )
    assert respuesta.status_code == 303, "el login de prueba falló"
    return c


@pytest.fixture()
def cliente_anonimo(session):
    from fastapi.testclient import TestClient

    from talanton.web.app import app

    return TestClient(app)
