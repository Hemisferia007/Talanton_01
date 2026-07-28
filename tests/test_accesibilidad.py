"""Chequeos de accesibilidad sobre el HTML servido.

No reemplazan una auditoría real (foco, lectores de pantalla, zoom), pero
evitan que se pierdan las bases: nombres accesibles en los controles, tablas
con encabezados declarados y una alternativa por teclado al drag & drop.
"""

from html.parser import HTMLParser

import pytest

from talanton import services

RUTAS = ["/", "/leads", "/tablero", "/avisos", "/mi-empresa"]




class Recolector(HTMLParser):
    """Junta controles de formulario, labels, headers de tabla y links."""

    def __init__(self):
        super().__init__()
        self.controles: list[tuple[str, dict]] = []
        self.labels_for: set[str] = set()
        self.th_sin_scope = 0
        self.th_total = 0
        self.enlaces: list[dict] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("input", "select", "textarea"):
            if a.get("type") not in ("submit", "hidden"):
                self.controles.append((tag, a))
        elif tag == "label" and a.get("for"):
            self.labels_for.add(a["for"])
        elif tag == "th":
            self.th_total += 1
            if not a.get("scope"):
                self.th_sin_scope += 1
        elif tag == "a":
            self.enlaces.append(a)


def _parsear(html: str) -> Recolector:
    r = Recolector()
    r.feed(html)
    return r


@pytest.mark.parametrize("ruta", RUTAS)
def test_todo_control_tiene_nombre_accesible(cliente, ruta):
    """Un placeholder no es una etiqueta (WCAG 1.3.1 / 3.3.2)."""
    r = _parsear(cliente.get(ruta).text)
    sin_nombre = [
        a
        for _, a in r.controles
        if not a.get("aria-label")
        and not a.get("aria-labelledby")
        and a.get("id") not in r.labels_for
    ]
    assert not sin_nombre, f"{ruta}: controles sin label → {sin_nombre}"


@pytest.mark.parametrize("ruta", RUTAS)
def test_las_tablas_declaran_scope_en_los_encabezados(cliente, ruta):
    r = _parsear(cliente.get(ruta).text)
    assert r.th_sin_scope == 0, f"{ruta}: {r.th_sin_scope} <th> sin scope"


@pytest.mark.parametrize("ruta", RUTAS)
def test_hay_enlace_para_saltar_al_contenido(cliente, ruta):
    html = cliente.get(ruta).text
    assert 'class="saltar" href="#contenido"' in html
    assert 'id="contenido"' in html


@pytest.mark.parametrize("ruta", RUTAS)
def test_la_navegacion_marca_la_pagina_actual(cliente, ruta):
    """El estado activo no puede depender sólo del color (WCAG 1.4.1)."""
    html = cliente.get(ruta).text
    assert html.count('aria-current="page"') == 1


@pytest.mark.parametrize("ruta", RUTAS)
def test_los_enlaces_externos_no_pierden_el_opener(cliente, ruta):
    r = _parsear(cliente.get(ruta).text)
    externos = [a for a in r.enlaces if a.get("target") == "_blank"]
    assert all("noopener" in (a.get("rel") or "") for a in externos)


def test_el_tablero_es_operable_por_teclado(cliente, session_con_demo):
    """El drag & drop no alcanza: cada tarjeta necesita un control enfocable."""
    html = cliente.get("/tablero").text
    r = _parsear(html)

    leads = services.listar_leads(session_con_demo)
    selectores = [a for tag, a in r.controles if "selector-estado" in (a.get("class") or "")]
    assert len(selectores) == len(leads)

    for lead in leads:
        assert f'id="mover-{lead.id}"' in html
        assert f'for="mover-{lead.id}"' in html


def test_el_tablero_anuncia_el_resultado_del_movimiento(cliente):
    """Sin región viva, quien no ve la pantalla no sabe si se guardó."""
    html = cliente.get("/tablero").text
    assert 'role="status"' in html
    assert 'aria-live="polite"' in html


def test_las_secciones_tienen_titulo_asociado(cliente):
    html = cliente.get("/leads/1").text
    assert 'aria-labelledby="t-score"' in html
    assert 'id="t-score"' in html


def test_la_barra_del_score_esta_oculta_para_lectores(cliente):
    """Es decorativa: el número al lado ya comunica el valor."""
    html = cliente.get("/leads/1").text
    assert '<span class="barra" aria-hidden="true">' in html


def test_los_controles_del_asistente_tambien_tienen_nombre(cliente, monkeypatch):
    """El panel del asistente sólo se renderiza con clave, así que no lo cubren
    las rutas de arriba. Sus controles pasan por la misma regla."""
    from datetime import datetime, timedelta, timezone

    from talanton.asistente import cliente as mod_asistente
    from talanton.correo import cripto
    from talanton.db import SessionLocal
    from talanton.models import CuentaGmail

    monkeypatch.setattr(mod_asistente, "ANTHROPIC_API_KEY", "clave-de-prueba")
    with SessionLocal() as db:
        db.add(
            CuentaGmail(
                email="a11y@talanton.com.ar",
                refresh_token_cifrado=cripto.cifrar("x"),
                access_token="t",
                access_token_expira=datetime.now(timezone.utc).replace(tzinfo=None)
                + timedelta(hours=1),
            )
        )
        db.commit()

    html = cliente.get("/leads/1").text
    assert 'id="t-opinion"' in html and 'id="m-instruccion"' in html

    r = _parsear(html)
    sin_nombre = [
        a
        for _, a in r.controles
        if not a.get("aria-label")
        and not a.get("aria-labelledby")
        and a.get("id") not in r.labels_for
    ]
    assert not sin_nombre, f"controles sin label → {sin_nombre}"
    # El estado de la lectura tiene que anunciarse: tarda varios segundos.
    assert 'id="estado-opinion" role="status"' in html
