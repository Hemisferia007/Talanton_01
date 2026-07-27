from talanton import normalize
from talanton.models import Seniority


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
