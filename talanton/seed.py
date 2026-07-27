"""Datos de demo (ficticios) para ver la herramienta funcionando.

Las empresas y personas son inventadas. Sirven para recorrer el flujo completo
sin depender de una corrida de ingesta real.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import delete
from sqlalchemy.orm import Session

from .models import (
    Actividad,
    Contacto,
    CuentaGmail,
    Direccion,
    Empresa,
    EstadoLead,
    EstadoMensaje,
    Lead,
    Mensaje,
    Vacante,
    ahora,
)
from .services import (
    asegurar_lead,
    fecha_hoy,
    mover_lead,
    recalcular_todos,
    registrar_actividad,
    upsert_empresa,
    upsert_vacante,
)

# (nombre, dominio, país, ciudad, industria, dotación, tiene_equipo_ta)
EMPRESAS = [
    ("Andes Logística S.R.L.", "andeslogistica.com.ar", "AR", "Mendoza", "Logística", 140, False),
    ("Fintecho", "fintecho.com.ar", "AR", "CABA", "Fintech", 65, False),
    ("Grupo Sanitario del Plata", "gsplata.com.ar", "AR", "La Plata", "Salud", 420, True),
    ("Cerámica Litoral", "ceramicalitoral.com.ar", "AR", "Paraná", "Industria", 230, False),
    ("Nubaris Cloud", "nubaris.io", "UY", "Montevideo", "Tecnología", 48, False),
    ("Agroexport Pampa", "agroexportpampa.com", "AR", "Rosario", "Agro", 310, False),
    ("Retail Norte", "retailnorte.com.ar", "AR", "Salta", "Retail", 780, True),
    ("Kuna Analytics", "kunaanalytics.cl", "CL", "Santiago", "Tecnología", 90, False),
    ("Constructora Riobamba", "riobamba.com.ar", "AR", "Córdoba", "Construcción", 175, False),
    ("Delta Seguros", "deltaseguros.com.ar", "AR", "CABA", "Seguros", 260, True),
]

# (empresa, título, ubicación, días desde publicación, cerrada, reposteos, por_consultora)
VACANTES = [
    ("Andes Logística S.R.L.", "Jefe de Depósito", "Mendoza, Argentina", 92, False, 2, False),
    ("Andes Logística S.R.L.", "Analista de Comercio Exterior Senior", "Mendoza, Argentina", 61, False, 1, False),
    ("Andes Logística S.R.L.", "Administrativo Junior", "Mendoza, Argentina", 12, False, 0, False),
    ("Andes Logística S.R.L.", "Jefe de Depósito", "Mendoza, Argentina", 210, True, 0, False),

    ("Fintecho", "Desarrollador Full Stack Semi Senior", "CABA, Argentina", 58, False, 1, False),
    ("Fintecho", "Líder Técnico Backend", "CABA, Argentina", 74, False, 0, False),
    ("Fintecho", "Analista de Riesgo Senior", "CABA, Argentina", 33, False, 0, False),
    ("Fintecho", "Product Manager", "Remoto", 21, False, 0, False),

    ("Grupo Sanitario del Plata", "Gerente de Enfermería", "La Plata, Argentina", 47, False, 0, False),
    ("Grupo Sanitario del Plata", "Analista de RRHH Semi Senior", "La Plata, Argentina", 19, False, 0, False),

    ("Cerámica Litoral", "Jefe de Mantenimiento Industrial", "Paraná, Argentina", 118, False, 3, False),
    ("Cerámica Litoral", "Ingeniero de Procesos Senior", "Paraná, Argentina", 55, False, 0, False),

    ("Nubaris Cloud", "DevOps Engineer Senior", "Montevideo, Uruguay", 40, False, 0, False),
    ("Nubaris Cloud", "QA Automation Semi Senior", "Remoto", 26, False, 0, False),

    ("Agroexport Pampa", "Director Comercial", "Rosario, Argentina", 86, False, 1, False),
    ("Agroexport Pampa", "Contador Senior", "Rosario, Argentina", 52, False, 0, False),
    ("Agroexport Pampa", "Analista de Calidad", "Rosario, Argentina", 8, False, 0, False),

    ("Retail Norte", "Gerente de Sucursal", "Salta, Argentina", 35, False, 0, True),
    ("Retail Norte", "Repositor", "Salta, Argentina", 14, False, 0, True),

    ("Kuna Analytics", "Data Scientist Senior", "Santiago, Chile", 63, False, 1, False),
    ("Kuna Analytics", "Analista de Datos Junior", "Santiago, Chile", 17, False, 0, False),

    ("Constructora Riobamba", "Jefe de Obra", "Córdoba, Argentina", 79, False, 2, False),
    ("Constructora Riobamba", "Ingeniero Civil Senior", "Córdoba, Argentina", 44, False, 0, False),
    ("Constructora Riobamba", "Comprador Técnico", "Córdoba, Argentina", 29, False, 0, False),

    ("Delta Seguros", "Suscriptor Senior de Riesgos Patrimoniales", "CABA, Argentina", 38, False, 0, False),
]

# (empresa, nombre, cargo, email, es_decisor)
CONTACTOS = [
    ("Andes Logística S.R.L.", "Marina Quiroga", "Gerenta de Administración", "mquiroga@andeslogistica.com.ar", True),
    ("Fintecho", "Diego Ferrari", "Co-fundador y COO", "diego@fintecho.com.ar", True),
    ("Cerámica Litoral", "Sergio Almada", "Director de Planta", "salmada@ceramicalitoral.com.ar", True),
    ("Agroexport Pampa", "Lucía Bentancur", "Gerenta de RRHH", "lbentancur@agroexportpampa.com", True),
    ("Nubaris Cloud", "Pablo Etchegaray", "CTO", "pablo@nubaris.io", True),
    ("Kuna Analytics", "Camila Rojas", "Head of People", "camila@kunaanalytics.cl", False),
]

# (empresa, estado, responsable, próximo paso)
ESTADOS_INICIALES = [
    ("Andes Logística S.R.L.", EstadoLead.REUNION, "Jonatan", "Enviar propuesta el viernes"),
    ("Cerámica Litoral", EstadoLead.CONTACTADO, "Jonatan", "Rellamar el martes"),
    ("Fintecho", EstadoLead.EN_CONVERSACION, "Sofía", "Definir alcance de la búsqueda de Líder Técnico"),
    ("Agroexport Pampa", EstadoLead.PROPUESTA, "Sofía", "Esperando firma"),
    ("Constructora Riobamba", EstadoLead.CONTACTADO, "Jonatan", "Mail enviado, sin respuesta"),
    ("Retail Norte", EstadoLead.PERDIDO, "Sofía", None),
    ("Nubaris Cloud", EstadoLead.GANADO, "Jonatan", "Búsqueda de DevOps en marcha"),
]


# Hilo de ejemplo, para que la conversación no se vea vacía en la demo.
# (empresa, dirección, días atrás, asunto, cuerpo)
CONVERSACION = [
    (
        "Andes Logística S.R.L.",
        Direccion.SALIENTE,
        9,
        "Jefe de Depósito — hace 83 días",
        "Hola Marina,\n\nVi que en Andes Logística están buscando Jefe de Depósito en "
        "Mendoza desde hace 83 días, y que ya republicaron el aviso.\n\nEs un perfil que "
        "solemos cubrir. Si te sirve, en una llamada de quince minutos te cuento cómo lo "
        "encararíamos y qué plazo real manejamos para una búsqueda así.\n\n¿Te queda "
        "cómodo esta semana?\n\nSaludos,\nJonatan\nTalanton",
    ),
    (
        "Andes Logística S.R.L.",
        Direccion.ENTRANTE,
        7,
        "Re: Jefe de Depósito — hace 83 días",
        "Hola Jonatan, gracias por escribir.\n\nSí, la verdad que con esa búsqueda "
        "venimos remando. Publicamos dos veces y los candidatos que llegan no tienen "
        "experiencia en logística de frío, que es lo que necesitamos.\n\n¿Podés el jueves "
        "a las 10?\n\nMarina",
    ),
    (
        "Andes Logística S.R.L.",
        Direccion.SALIENTE,
        7,
        "Re: Jefe de Depósito — hace 83 días",
        "Perfecto Marina, jueves 10 me queda bien. Te mando la invitación.\n\nSi podés, "
        "traé el perfil que venían usando así lo revisamos juntos: cuando los candidatos "
        "no llegan con la experiencia específica, casi siempre hay algo del aviso que "
        "está filtrando de más.\n\nSaludos,\nJonatan",
    ),
    (
        "Cerámica Litoral",
        Direccion.SALIENTE,
        4,
        "Jefe de Mantenimiento Industrial — hace 114 días",
        "Hola Sergio,\n\nVi que en Cerámica Litoral están buscando Jefe de Mantenimiento "
        "Industrial en Paraná desde hace 114 días, y que ya republicaron el aviso.\n\n"
        "Es un perfil que solemos cubrir. ¿Te sirve una llamada corta esta semana?\n\n"
        "Saludos,\nJonatan\nTalanton",
    ),
]


def limpiar(session: Session) -> None:
    for modelo in (Mensaje, Actividad, Lead, Vacante, Contacto, Empresa, CuentaGmail):
        session.execute(delete(modelo))
    session.commit()


def sembrar(session: Session, *, reiniciar: bool = True) -> None:
    if reiniciar:
        limpiar(session)

    hoy = fecha_hoy()
    por_nombre: dict[str, Empresa] = {}

    for nombre, dominio, pais, ciudad, industria, dotacion, tiene_ta in EMPRESAS:
        empresa = upsert_empresa(
            session,
            nombre,
            dominio=dominio,
            pais=pais,
            ciudad=ciudad,
            industria=industria,
            dotacion_estimada=dotacion,
            sitio_web=f"https://{dominio}",
        )
        empresa.tiene_equipo_ta = tiene_ta
        por_nombre[nombre] = empresa

    for i, (nombre_emp, titulo, ubicacion, dias, cerrada, reposteos, consultora) in enumerate(
        VACANTES
    ):
        empresa = por_nombre[nombre_emp]
        publicacion = hoy - timedelta(days=dias)
        vacante, _ = upsert_vacante(
            session,
            empresa,
            titulo=titulo,
            fuente="demo",
            external_id=f"demo-{i}",
            fuente_url=f"https://{empresa.dominio}/empleos/{i}",
            ubicacion=ubicacion,
            pais=empresa.pais,
            fecha_publicacion=publicacion,
            vista_el=hoy,
        )
        vacante.reposteos = reposteos
        vacante.publicada_por_consultora = consultora
        if cerrada:
            vacante.cerrada = True
            # La cerraron a los ~40 días de publicarla.
            vacante.fecha_cierre = publicacion + timedelta(days=40)

    for nombre_emp, nombre, cargo, email, es_decisor in CONTACTOS:
        session.add(
            Contacto(
                empresa_id=por_nombre[nombre_emp].id,
                nombre=nombre,
                cargo=cargo,
                email=email,
                es_decisor=es_decisor,
                fuente_url=f"https://{por_nombre[nombre_emp].dominio}/nosotros",
            )
        )

    session.flush()
    for empresa in por_nombre.values():
        session.refresh(empresa)
        asegurar_lead(session, empresa)

    session.flush()
    for nombre_emp, estado, responsable, proximo in ESTADOS_INICIALES:
        lead = por_nombre[nombre_emp].lead
        if lead is None:
            continue
        mover_lead(session, lead, estado, autor=responsable)
        lead.responsable = responsable
        lead.proximo_paso = proximo
        if estado == EstadoLead.PERDIDO:
            lead.motivo_perdida = "Ya trabajan con otra consultora"
        lead.ultimo_contacto_en = ahora() - timedelta(days=3)
        registrar_actividad(
            session,
            lead,
            f"Primer contacto por mail con {por_nombre[nombre_emp].nombre}.",
            tipo="contacto",
            autor=responsable,
        )

    # El hilo se arma directo, sin pasar por el envío real: son datos de demo,
    # no hay ninguna casilla conectada.
    for nombre_emp, direccion, dias, asunto, cuerpo in CONVERSACION:
        empresa = por_nombre[nombre_emp]
        contacto = next((c for c in empresa.contactos if c.email), None)
        cuando = ahora() - timedelta(days=dias)
        entrante = direccion == Direccion.ENTRANTE
        session.add(
            Mensaje(
                lead_id=empresa.lead.id,
                direccion=direccion,
                estado=EstadoMensaje.RECIBIDO if entrante else EstadoMensaje.ENVIADO,
                de=(contacto.email if contacto else None) if entrante else None,
                para="" if entrante else (contacto.email if contacto else ""),
                asunto=asunto,
                cuerpo=cuerpo,
                creado_en=cuando,
                enviado_en=cuando,
            )
        )

    session.commit()
    recalcular_todos(session)
    session.commit()
