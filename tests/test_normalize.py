import pytest

from talanton import normalize
from talanton.models import Seniority
from talanton.normalize import detectar_seniority, normalizar_rol


def test_nombre_empresa_ignora_sufijos_societarios():
    assert (
        normalize.normalizar_nombre_empresa("Grupo Logístico del Sur S.R.L.")
        == normalize.normalizar_nombre_empresa("grupo logistico del sur")
    )
    assert normalize.normalizar_nombre_empresa("Fintecho S.A.") == "fintecho"


def test_dominio_descarta_genericos_y_www():
    assert normalize.normalizar_dominio("https://www.Andes.com.ar/empleos") == "andes.com.ar"
    assert normalize.normalizar_dominio("marina@andeslogistica.com.ar") == "andeslogistica.com.ar"
    assert normalize.normalizar_dominio("alguien@gmail.com") is None
    assert normalize.normalizar_dominio(None) is None


def test_rol_colapsa_redacciones_del_mismo_puesto():
    """Sin esto no existen las señales de reposteo ni de recurrencia."""
    a = normalize.normalizar_rol("Programador Full-Stack Semi Senior (Remoto)")
    b = normalize.normalizar_rol("Desarrollador Full Stack Ssr")
    c = normalize.normalizar_rol("Full Stack Developer Senior - Buenos Aires")
    assert a == b == c


def test_rol_distingue_puestos_distintos():
    assert normalize.normalizar_rol("Jefe de Obra") != normalize.normalizar_rol("Jefe de Depósito")


def test_seniority():
    assert normalize.detectar_seniority("Analista de Riesgo Senior") == Seniority.SENIOR
    assert normalize.detectar_seniority("Desarrollador Ssr") == Seniority.SEMI_SENIOR
    assert normalize.detectar_seniority("Gerente de Enfermería") == Seniority.JEFATURA
    assert normalize.detectar_seniority("Director Comercial") == Seniority.DIRECCION
    assert normalize.detectar_seniority("Analista de Calidad") == Seniority.INDEFINIDO


def test_detecta_avisos_publicados_por_consultora():
    assert normalize.publicado_por_consultora("Randstad Argentina")
    assert normalize.publicado_por_consultora("Confidencial", "Importante empresa del rubro busca…")
    assert not normalize.publicado_por_consultora("Andes Logística", "Buscamos jefe de depósito")


# --- Vocabulario de IT -------------------------------------------------------
#
# IT es el rubro con más volumen de búsquedas en Argentina y el que más mezcla
# español e inglés en el mismo aviso. Cada par que no colapsa a la misma clave
# es un reposteo invisible, y el reposteo es la señal más fuerte del producto.


@pytest.mark.parametrize(
    "titulo,esperado",
    [
        # En IT la jefatura casi nunca dice "jefe": dice "lead".
        ("Tech Lead Backend", Seniority.JEFATURA),
        ("Team Lead de Desarrollo", Seniority.JEFATURA),
        ("Engineering Manager", Seniority.JEFATURA),
        ("Scrum Master", Seniority.JEFATURA),
        # Staff y Principal están arriba de Senior, pero son roles individuales.
        ("Staff Engineer", Seniority.SENIOR),
        ("Principal Software Engineer", Seniority.SENIOR),
        ("Arquitecto de Software", Seniority.SENIOR),
        ("Cybersecurity Specialist", Seniority.SENIOR),
        ("CTO", Seniority.DIRECCION),
        ("CISO", Seniority.DIRECCION),
        ("Co-Founder", Seniority.DIRECCION),
    ],
)
def test_seniority_de_titulos_de_it(titulo, esperado):
    assert detectar_seniority(titulo) == esperado


@pytest.mark.parametrize(
    "uno,otro",
    [
        # El orden de las palabras cambia entre idiomas.
        ("DevOps Engineer", "Ingeniero DevOps Semi Senior"),
        ("Site Reliability Engineer", "SRE Senior"),
        ("Ingeniero de Datos", "Data Engineer Senior"),
        ("Científico de Datos", "Data Scientist Senior"),
        ("Product Owner", "Product Manager Sr"),
        ("Especialista en Ciberseguridad", "Cybersecurity Specialist"),
        ("Analista QA", "QA Analyst"),
        ("Desarrollador Backend Java", "Java Backend Developer"),
        ("Programador Full-Stack Ssr", "Full Stack Developer Semi Senior"),
    ],
)
def test_el_mismo_puesto_de_it_colapsa_a_una_clave(uno, otro):
    assert normalizar_rol(uno) == normalizar_rol(otro), (
        f"{uno!r} -> {normalizar_rol(uno)!r} vs {otro!r} -> {normalizar_rol(otro)!r}"
    )


def test_roles_de_it_distintos_no_se_mezclan():
    """Colapsar de más es tan malo como de menos: inventaría reposteos."""
    claves = {
        normalizar_rol(t)
        for t in ("Data Engineer", "Data Scientist", "DevOps Engineer", "SRE",
                  "Product Owner", "QA Analyst", "Frontend Developer",
                  "Backend Developer")
    }
    assert len(claves) == 8
