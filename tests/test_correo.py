"""Tests del envío. Nunca se toca la red: el cliente de Gmail se inyecta."""

import base64
from datetime import datetime, timedelta, timezone

import pytest

from talanton.correo import cripto, gmail, plantillas
from talanton.correo import servicio as correo
from talanton.models import CuentaGmail, EstadoLead, EstadoMensaje
from talanton.services import listar_leads


class GmailFalso:
    """Reemplaza al cliente real. Registra lo que se le pidió mandar."""

    ErrorGmail = gmail.ErrorGmail

    def __init__(self, falla: str | None = None):
        self.falla = falla
        self.enviados: list[dict] = []

    def enviar(self, token, *, de, nombre_de, para, asunto, cuerpo):
        if self.falla:
            raise gmail.ErrorGmail(self.falla)
        self.enviados.append(
            {"token": token, "de": de, "para": para, "asunto": asunto, "cuerpo": cuerpo}
        )
        return {"id": f"msg-{len(self.enviados)}", "threadId": "hilo-1"}


@pytest.fixture()
def cuenta(session):
    c = CuentaGmail(
        email="jonatan@talanton.com.ar",
        nombre_remitente="Jonatan de Talanton",
        firma="Jonatan\nTalanton",
        refresh_token_cifrado=cripto.cifrar("refresh-de-mentira"),
        access_token="token-vigente",
        # Vigente: así el servicio no intenta refrescarlo contra Google.
        access_token_expira=datetime.now(timezone.utc).replace(tzinfo=None)
        + timedelta(hours=1),
    )
    session.add(c)
    session.flush()
    return c


# --- Cifrado -----------------------------------------------------------------


def test_el_refresh_token_no_queda_en_texto_plano(session, cuenta):
    assert "refresh-de-mentira" not in cuenta.refresh_token_cifrado
    assert cripto.descifrar(cuenta.refresh_token_cifrado) == "refresh-de-mentira"


def test_descifrar_con_clave_equivocada_falla_claro():
    from cryptography.fernet import Fernet

    ajeno = Fernet(Fernet.generate_key()).encrypt(b"secreto").decode()
    with pytest.raises(ValueError, match="volver a conectar"):
        cripto.descifrar(ajeno)


# --- Plantillas --------------------------------------------------------------


def test_la_plantilla_elegida_usa_la_senal_real(session_con_demo):
    lead = next(
        l for l in listar_leads(session_con_demo) if l.empresa.nombre.startswith("Andes")
    )
    datos = correo.borrador(session_con_demo, lead)

    vieja = max(lead.empresa.vacantes_abiertas, key=lambda v: v.dias_abierta)
    assert datos["plantilla"].clave in ("busqueda_estirada", "rotacion")
    assert vieja.titulo in datos["asunto"] or vieja.titulo in datos["cuerpo"]
    assert str(vieja.dias_abierta) in datos["cuerpo"] or str(vieja.dias_abierta) in datos["asunto"]


def test_el_borrador_prellena_al_decisor(session_con_demo):
    lead = next(
        l for l in listar_leads(session_con_demo) if l.empresa.nombre.startswith("Andes")
    )
    datos = correo.borrador(session_con_demo, lead)
    assert datos["para"] == "mquiroga@andeslogistica.com.ar"
    assert "Marina" in datos["cuerpo"]


def test_siempre_hay_al_menos_una_plantilla(session_con_demo):
    """Sin señal fuerte igual tiene que poder escribirse el mail."""
    for lead in listar_leads(session_con_demo):
        datos = correo.borrador(session_con_demo, lead)
        assert datos["opciones"]
        assert datos["asunto"].strip()
        assert datos["cuerpo"].strip()


def test_pedir_una_plantilla_que_no_aplica_cae_en_la_recomendada(session_con_demo):
    lead = listar_leads(session_con_demo)[0]
    datos = correo.borrador(session_con_demo, lead, clave="inexistente")
    assert datos["plantilla"] in datos["opciones"]


def test_la_plantilla_de_volumen_lista_las_busquedas(session_con_demo):
    lead = next(
        l for l in listar_leads(session_con_demo) if len(l.empresa.vacantes_abiertas) >= 3
    )
    datos = correo.borrador(session_con_demo, lead, clave="volumen")
    for vacante in lead.empresa.vacantes_abiertas[:3]:
        assert vacante.titulo in datos["cuerpo"]


# --- Envío -------------------------------------------------------------------


def test_enviar_registra_actividad_y_mueve_el_lead(session_con_demo, cuenta):
    lead = next(
        l for l in listar_leads(session_con_demo) if l.estado == EstadoLead.NUEVO
    )
    falso = GmailFalso()

    mensaje = correo.enviar(
        session_con_demo,
        lead,
        cuenta,
        para="contacto@empresa.com",
        asunto="Una búsqueda que se estiró",
        cuerpo="Hola,\n\nTexto del mail.",
        plantilla="busqueda_estirada",
        cliente=falso,
    )
    session_con_demo.commit()

    assert mensaje.estado == EstadoMensaje.ENVIADO
    assert mensaje.gmail_message_id == "msg-1"
    assert len(falso.enviados) == 1
    assert falso.enviados[0]["de"] == "jonatan@talanton.com.ar"

    # Un lead al que ya le escribimos no puede seguir figurando como nuevo.
    assert lead.estado == EstadoLead.CONTACTADO
    assert lead.ultimo_contacto_en is not None
    assert any("Mail enviado" in a.detalle for a in lead.actividades)


def test_un_envio_fallido_queda_registrado(session_con_demo, cuenta):
    lead = listar_leads(session_con_demo)[0]
    estado_previo = lead.estado

    with pytest.raises(correo.ErrorEnvio, match="cuota"):
        correo.enviar(
            session_con_demo,
            lead,
            cuenta,
            para="contacto@empresa.com",
            asunto="Asunto",
            cuerpo="Cuerpo",
            cliente=GmailFalso(falla="Gmail rechazó el envío: cuota diaria superada"),
        )
    session_con_demo.commit()

    fallidos = [m for m in lead.mensajes if m.estado == EstadoMensaje.ERROR]
    assert len(fallidos) == 1
    assert "cuota" in fallidos[0].error
    # El estado del lead no se toca si el mail no salió.
    assert lead.estado == estado_previo


def test_no_se_envia_sin_destinatario_valido(session_con_demo, cuenta):
    lead = listar_leads(session_con_demo)[0]
    with pytest.raises(correo.ErrorEnvio, match="destino"):
        correo.enviar(
            session_con_demo, lead, cuenta,
            para="no-es-un-mail", asunto="A", cuerpo="B", cliente=GmailFalso(),
        )


def test_no_se_envia_sin_asunto(session_con_demo, cuenta):
    lead = listar_leads(session_con_demo)[0]
    with pytest.raises(correo.ErrorEnvio, match="asunto"):
        correo.enviar(
            session_con_demo, lead, cuenta,
            para="a@b.com", asunto="   ", cuerpo="B", cliente=GmailFalso(),
        )


def test_el_tope_diario_frena_el_envio(session_con_demo, cuenta, monkeypatch):
    """El límite protege la reputación del dominio, no es un detalle cosmético."""
    monkeypatch.setattr("talanton.correo.servicio.LIMITE_ENVIOS_DIARIOS", 2)
    lead = listar_leads(session_con_demo)[0]
    falso = GmailFalso()

    for i in range(2):
        correo.enviar(
            session_con_demo, lead, cuenta,
            para=f"a{i}@b.com", asunto="A", cuerpo="B", cliente=falso,
        )
    session_con_demo.commit()

    with pytest.raises(correo.ErrorEnvio, match="tope configurado"):
        correo.enviar(
            session_con_demo, lead, cuenta,
            para="a3@b.com", asunto="A", cuerpo="B", cliente=falso,
        )
    assert len(falso.enviados) == 2


def test_enviados_hoy_cuenta_solo_los_exitosos(session_con_demo, cuenta):
    lead = listar_leads(session_con_demo)[0]
    correo.enviar(
        session_con_demo, lead, cuenta,
        para="a@b.com", asunto="A", cuerpo="B", cliente=GmailFalso(),
    )
    with pytest.raises(correo.ErrorEnvio):
        correo.enviar(
            session_con_demo, lead, cuenta,
            para="c@d.com", asunto="A", cuerpo="B", cliente=GmailFalso(falla="error"),
        )
    session_con_demo.commit()
    assert correo.enviados_hoy(session_con_demo, cuenta) == 1


# --- MIME y OAuth ------------------------------------------------------------


def test_el_mime_lleva_remitente_con_nombre():
    crudo = gmail.armar_mime(
        de="jonatan@talanton.com.ar",
        nombre_de="Jonatan de Talanton",
        para="marina@empresa.com.ar",
        asunto="Jefe de Depósito — hace 92 días",
        cuerpo="Hola Marina,\n\nTexto.",
    )
    # base64 URL-safe, como espera la API de Gmail.
    plano = base64.urlsafe_b64decode(crudo).decode()
    assert "From: Jonatan de Talanton <jonatan@talanton.com.ar>" in plano
    assert "To: marina@empresa.com.ar" in plano
    assert "Hola Marina," in plano


def test_el_asunto_con_acentos_sobrevive_al_mime():
    crudo = gmail.armar_mime(
        de="a@b.com", nombre_de=None, para="c@d.com",
        asunto="Búsqueda de Ingeniero en Paraná", cuerpo="Ñandú",
    )
    from email import message_from_bytes

    mensaje = message_from_bytes(base64.urlsafe_b64decode(crudo))
    from email.header import decode_header, make_header

    assert str(make_header(decode_header(mensaje["Subject"]))) == "Búsqueda de Ingeniero en Paraná"


def test_la_url_de_autorizacion_pide_refresh_token(monkeypatch):
    monkeypatch.setattr("talanton.correo.gmail.GOOGLE_CLIENT_ID", "cliente-de-prueba")
    url = gmail.url_de_autorizacion("estado-123")
    # Sin estos dos parámetros Google no devuelve refresh token y habría que
    # reconectar la cuenta todos los días.
    assert "access_type=offline" in url
    assert "prompt=consent" in url
    assert "state=estado-123" in url
    assert "gmail.send" in url


def test_sin_client_id_el_error_es_accionable(monkeypatch):
    monkeypatch.setattr("talanton.correo.gmail.GOOGLE_CLIENT_ID", "")
    with pytest.raises(gmail.ErrorGmail, match="TALANTON_GOOGLE_CLIENT_ID"):
        gmail.url_de_autorizacion("x")


def test_solo_se_pide_permiso_de_envio():
    """Leer la casilla ajena no hace falta para esto."""
    from talanton.config import GMAIL_SCOPES

    assert "gmail.send" in GMAIL_SCOPES
    assert "gmail.readonly" not in GMAIL_SCOPES
    assert "gmail.modify" not in GMAIL_SCOPES


# --- Hilo de conversación ----------------------------------------------------


def test_el_hilo_mezcla_salientes_y_entrantes_en_orden(session_con_demo, cuenta):
    # Un lead sin hilo previo, para que el orden que se verifica sea el de acá.
    lead = next(l for l in listar_leads(session_con_demo) if not l.mensajes)
    falso = GmailFalso()

    correo.enviar(
        session_con_demo, lead, cuenta,
        para="marina@empresa.com.ar", asunto="Primer contacto", cuerpo="Hola Marina,",
        cliente=falso,
    )
    correo.registrar_respuesta(session_con_demo, lead, cuerpo="Contame más.")
    correo.enviar(
        session_con_demo, lead, cuenta,
        para="marina@empresa.com.ar", asunto="Re: Primer contacto", cuerpo="Va el detalle.",
        cliente=falso,
    )
    session_con_demo.commit()
    session_con_demo.refresh(lead)

    direcciones = [m.direccion.value for m in lead.mensajes]
    assert direcciones == ["saliente", "entrante", "saliente"]
    # Cronológico ascendente: el hilo se lee de arriba hacia abajo.
    fechas = [m.fecha for m in lead.mensajes]
    assert fechas == sorted(fechas)


def test_una_respuesta_mueve_el_lead_a_en_conversacion(session_con_demo, cuenta):
    lead = next(l for l in listar_leads(session_con_demo) if l.estado == EstadoLead.NUEVO)
    correo.enviar(
        session_con_demo, lead, cuenta,
        para="a@b.com", asunto="A", cuerpo="B", cliente=GmailFalso(),
    )
    assert lead.estado == EstadoLead.CONTACTADO

    correo.registrar_respuesta(session_con_demo, lead, cuerpo="Me interesa.")
    session_con_demo.commit()
    assert lead.estado == EstadoLead.EN_CONVERSACION


def test_una_respuesta_no_retrocede_un_lead_avanzado(session_con_demo, cuenta):
    lead = next(l for l in listar_leads(session_con_demo) if l.estado == EstadoLead.PROPUESTA)
    correo.registrar_respuesta(session_con_demo, lead, cuerpo="Lo estamos viendo.")
    session_con_demo.commit()
    assert lead.estado == EstadoLead.PROPUESTA


def test_la_respuesta_hereda_destinatario_y_asunto(session_con_demo, cuenta):
    lead = listar_leads(session_con_demo)[0]
    correo.enviar(
        session_con_demo, lead, cuenta,
        para="marina@empresa.com.ar", asunto="Jefe de Depósito", cuerpo="Hola",
        cliente=GmailFalso(),
    )
    respuesta = correo.registrar_respuesta(session_con_demo, lead, cuerpo="Dale.")
    session_con_demo.commit()

    assert respuesta.de == "marina@empresa.com.ar"
    assert respuesta.asunto == "Re: Jefe de Depósito"
    assert respuesta.para == cuenta.email


def test_una_respuesta_vacia_se_rechaza(session_con_demo):
    lead = listar_leads(session_con_demo)[0]
    with pytest.raises(correo.ErrorEnvio, match="vacía"):
        correo.registrar_respuesta(session_con_demo, lead, cuerpo="   ")
