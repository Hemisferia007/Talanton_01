"""Chequeos de configuración de producción."""

import pytest

from talanton import config


def test_en_desarrollo_no_exige_nada(monkeypatch):
    monkeypatch.setattr(config, "COOKIES_SEGURAS", False)
    monkeypatch.setattr(config, "SESSION_SECRET", "")
    monkeypatch.setattr(config, "SECRET_KEY", "")
    config.verificar_configuracion_de_produccion()  # no debe lanzar


def test_en_produccion_exige_los_dos_secretos(monkeypatch):
    """Sin ellos la app anda igual, y ahí está el problema: cada reinicio
    desloguea a todos y los tokens de Gmail dejan de descifrarse."""
    monkeypatch.setattr(config, "COOKIES_SEGURAS", True)
    monkeypatch.setattr(config, "SESSION_SECRET", "")
    monkeypatch.setattr(config, "SECRET_KEY", "")

    with pytest.raises(RuntimeError) as error:
        config.verificar_configuracion_de_produccion()
    assert "TALANTON_SESSION_SECRET" in str(error.value)
    assert "TALANTON_SECRET_KEY" in str(error.value)


def test_el_error_nombra_solo_lo_que_falta(monkeypatch):
    monkeypatch.setattr(config, "COOKIES_SEGURAS", True)
    monkeypatch.setattr(config, "SESSION_SECRET", "un-secreto")
    monkeypatch.setattr(config, "SECRET_KEY", "")

    with pytest.raises(RuntimeError) as error:
        config.verificar_configuracion_de_produccion()
    assert "TALANTON_SECRET_KEY" in str(error.value)
    assert "TALANTON_SESSION_SECRET" not in str(error.value)


def test_con_todo_configurado_pasa(monkeypatch):
    monkeypatch.setattr(config, "COOKIES_SEGURAS", True)
    monkeypatch.setattr(config, "SESSION_SECRET", "un-secreto")
    monkeypatch.setattr(config, "SECRET_KEY", "una-clave")
    config.verificar_configuracion_de_produccion()
