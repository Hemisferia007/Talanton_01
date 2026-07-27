import pytest

from talanton import services
from talanton.models import EstadoLead




@pytest.mark.parametrize(
    "ruta", ["/", "/leads", "/tablero", "/avisos", "/mi-empresa"]
)
def test_las_paginas_responden(cliente, ruta):
    r = cliente.get(ruta)
    assert r.status_code == 200
    assert "Talanton" in r.text


def test_detalle_de_lead_muestra_las_razones(cliente, session_con_demo):
    lead = services.listar_leads(session_con_demo)[0]
    r = cliente.get(f"/leads/{lead.id}")
    assert r.status_code == 200
    assert lead.empresa.nombre in r.text
    assert lead.lista_razones[0][:30] in r.text


def test_lead_inexistente_da_404(cliente):
    assert cliente.get("/leads/999999").status_code == 404


def test_mover_lead_por_api(cliente, session_con_demo):
    lead = services.listar_leads(session_con_demo)[0]
    r = cliente.post(f"/api/leads/{lead.id}/mover", json={"estado": "reunion", "posicion": 0})
    assert r.status_code == 200
    assert r.json()["estado"] == "reunion"

    session_con_demo.expire_all()
    assert services.listar_leads(session_con_demo, estado=EstadoLead.REUNION)


def test_mover_con_estado_invalido_da_400(cliente, session_con_demo):
    lead = services.listar_leads(session_con_demo)[0]
    r = cliente.post(f"/api/leads/{lead.id}/mover", json={"estado": "inventado"})
    assert r.status_code == 400


def test_filtro_de_avisos_urgentes(cliente):
    r = cliente.get("/avisos", params={"estado_aviso": "urgentes"})
    assert r.status_code == 200


def test_agregar_nota_al_lead(cliente, session_con_demo):
    lead = services.listar_leads(session_con_demo)[0]
    r = cliente.post(
        f"/leads/{lead.id}/nota",
        data={"detalle": "Hablé con el gerente", "tipo": "contacto"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    session_con_demo.expire_all()
    detalle = cliente.get(f"/leads/{lead.id}")
    assert "Hablé con el gerente" in detalle.text


def test_guardar_icp_recalcula_los_scores(cliente, session_con_demo):
    lead = services.listar_leads(session_con_demo)[0]
    score_previo = lead.score

    r = cliente.post(
        "/mi-empresa",
        data={
            "nombre": "Talanton",
            "descripcion": "",
            "sitio_web": "",
            "email_contacto": "",
            "industrias_objetivo": "",
            "paises_objetivo": "MX",  # deja a las empresas argentinas fuera del ICP
            "dotacion_min": 20,
            "dotacion_max": 2000,
            "seniorities_objetivo": "senior,jefatura,direccion",
            "fee_promedio": "",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303

    session_con_demo.expire_all()
    actualizado = session_con_demo.get(type(lead), lead.id)
    assert actualizado.score != score_previo
