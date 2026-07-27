"""Modelos de dominio.

Principio de diseño: el histórico es el activo. Las vacantes nunca se borran —
se marcan como cerradas y se conserva `primera_vez_vista` para poder calcular
días abiertas, reposteos y recurrencia. Ver docs/estrategia-leads.md.
"""

from __future__ import annotations

import enum
from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def ahora() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class EstadoLead(str, enum.Enum):
    """Columnas del kanban, en orden de avance."""

    NUEVO = "nuevo"
    CONTACTADO = "contactado"
    EN_CONVERSACION = "en_conversacion"
    REUNION = "reunion"
    PROPUESTA = "propuesta"
    GANADO = "ganado"
    PERDIDO = "perdido"

    @property
    def etiqueta(self) -> str:
        return {
            "nuevo": "Nuevo",
            "contactado": "Contactado",
            "en_conversacion": "En conversación",
            "reunion": "Reunión",
            "propuesta": "Propuesta",
            "ganado": "Ganado",
            "perdido": "Perdido",
        }[self.value]

    @property
    def es_cerrado(self) -> bool:
        return self in (EstadoLead.GANADO, EstadoLead.PERDIDO)


ESTADOS_KANBAN = list(EstadoLead)


class Seniority(str, enum.Enum):
    JUNIOR = "junior"
    SEMI_SENIOR = "semi_senior"
    SENIOR = "senior"
    JEFATURA = "jefatura"
    DIRECCION = "direccion"
    INDEFINIDO = "indefinido"

    @property
    def etiqueta(self) -> str:
        return {
            "junior": "Junior",
            "semi_senior": "Semi Senior",
            "senior": "Senior",
            "jefatura": "Jefatura",
            "direccion": "Dirección",
            "indefinido": "Sin clasificar",
        }[self.value]


class Empresa(Base):
    __tablename__ = "empresas"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(200))
    # Clave de deduplicación preferida. Ver normalize.clave_empresa().
    dominio: Mapped[str | None] = mapped_column(String(200), unique=True)
    nombre_normalizado: Mapped[str] = mapped_column(String(200), index=True)
    pais: Mapped[str | None] = mapped_column(String(2), index=True)
    ciudad: Mapped[str | None] = mapped_column(String(120))
    industria: Mapped[str | None] = mapped_column(String(120), index=True)
    dotacion_estimada: Mapped[int | None] = mapped_column(Integer)
    sitio_web: Mapped[str | None] = mapped_column(String(300))
    linkedin_url: Mapped[str | None] = mapped_column(String(300))
    # Se detecta por la presencia de roles de TA/People entre sus contactos o
    # búsquedas. Si no tiene equipo interno, terceriza sí o sí.
    tiene_equipo_ta: Mapped[bool] = mapped_column(Boolean, default=False)
    creada_en: Mapped[datetime] = mapped_column(DateTime, default=ahora)

    vacantes: Mapped[list["Vacante"]] = relationship(
        back_populates="empresa", cascade="all, delete-orphan"
    )
    contactos: Mapped[list["Contacto"]] = relationship(
        back_populates="empresa", cascade="all, delete-orphan"
    )
    lead: Mapped["Lead | None"] = relationship(
        back_populates="empresa", uselist=False, cascade="all, delete-orphan"
    )

    @property
    def tamano_etiqueta(self) -> str:
        d = self.dotacion_estimada
        if d is None:
            return "Sin datos"
        if d < 25:
            return "Micro (<25)"
        if d < 100:
            return "Pequeña (25-99)"
        if d < 500:
            return "Mediana (100-499)"
        return "Grande (500+)"

    @property
    def vacantes_abiertas(self) -> list["Vacante"]:
        return [v for v in self.vacantes if not v.cerrada]


class Vacante(Base):
    """Un aviso de búsqueda observado en alguna fuente."""

    __tablename__ = "vacantes"
    __table_args__ = (
        # Un mismo aviso en una misma fuente se actualiza, no se duplica.
        UniqueConstraint("fuente", "external_id", name="uq_vacante_fuente_externa"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"), index=True)

    titulo: Mapped[str] = mapped_column(String(300))
    # Título canónico: "Dev Full Stack Ssr" y "Programador Full-Stack Semi Senior"
    # colapsan al mismo valor. Sin esto no existen reposteos ni recurrencia.
    rol_normalizado: Mapped[str] = mapped_column(String(200), index=True)
    seniority: Mapped[Seniority] = mapped_column(
        Enum(Seniority), default=Seniority.INDEFINIDO
    )
    ubicacion: Mapped[str | None] = mapped_column(String(200))
    pais: Mapped[str | None] = mapped_column(String(2), index=True)
    modalidad: Mapped[str | None] = mapped_column(String(40))
    descripcion: Mapped[str | None] = mapped_column(Text)

    fuente: Mapped[str] = mapped_column(String(60), index=True)
    fuente_url: Mapped[str | None] = mapped_column(String(600))
    external_id: Mapped[str] = mapped_column(String(200))

    # El corazón del sistema: cuándo la vimos por primera vez y por última.
    fecha_publicacion: Mapped[date | None] = mapped_column(Date)
    primera_vez_vista: Mapped[date] = mapped_column(Date, default=lambda: ahora().date())
    ultima_vez_vista: Mapped[date] = mapped_column(Date, default=lambda: ahora().date())
    cerrada: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    fecha_cierre: Mapped[date | None] = mapped_column(Date)

    # Veces que el aviso desapareció y volvió a publicarse.
    reposteos: Mapped[int] = mapped_column(Integer, default=0)
    # Si ya la publica una consultora, el lead está tomado.
    publicada_por_consultora: Mapped[bool] = mapped_column(Boolean, default=False)

    empresa: Mapped[Empresa] = relationship(back_populates="vacantes")

    @property
    def dias_abierta(self) -> int:
        fin = self.fecha_cierre or ahora().date()
        inicio = self.fecha_publicacion or self.primera_vez_vista
        return max((fin - inicio).days, 0)

    @property
    def es_urgente(self) -> bool:
        """Umbral en el que la búsqueda propia ya falló."""
        return not self.cerrada and self.dias_abierta >= 45


class Contacto(Base):
    __tablename__ = "contactos"

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"), index=True)
    nombre: Mapped[str] = mapped_column(String(200))
    cargo: Mapped[str | None] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(200))
    telefono: Mapped[str | None] = mapped_column(String(60))
    linkedin_url: Mapped[str | None] = mapped_column(String(300))
    es_decisor: Mapped[bool] = mapped_column(Boolean, default=False)
    # Trazabilidad: de dónde salió el dato, para poder auditarlo y borrarlo a pedido.
    fuente_url: Mapped[str | None] = mapped_column(String(600))
    creado_en: Mapped[datetime] = mapped_column(DateTime, default=ahora)

    empresa: Mapped[Empresa] = relationship(back_populates="contactos")


class Lead(Base):
    """Una empresa vista como oportunidad comercial. Uno por empresa."""

    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(
        ForeignKey("empresas.id"), unique=True, index=True
    )

    estado: Mapped[EstadoLead] = mapped_column(
        Enum(EstadoLead), default=EstadoLead.NUEVO, index=True
    )
    # Posición dentro de la columna del kanban.
    orden: Mapped[int] = mapped_column(Integer, default=0)

    score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    score_urgencia: Mapped[float] = mapped_column(Float, default=0.0)
    score_fit: Mapped[float] = mapped_column(Float, default=0.0)
    score_accesibilidad: Mapped[float] = mapped_column(Float, default=0.0)
    score_pago: Mapped[float] = mapped_column(Float, default=0.0)
    # Razones legibles, una por línea. El comercial tiene que poder explicar el score.
    razones: Mapped[str] = mapped_column(Text, default="")
    # Frase lista para abrir la conversación, derivada de la señal concreta.
    gancho: Mapped[str | None] = mapped_column(Text)

    responsable: Mapped[str | None] = mapped_column(String(120))
    proximo_paso: Mapped[str | None] = mapped_column(String(300))
    motivo_perdida: Mapped[str | None] = mapped_column(String(300))

    creado_en: Mapped[datetime] = mapped_column(DateTime, default=ahora)
    actualizado_en: Mapped[datetime] = mapped_column(
        DateTime, default=ahora, onupdate=ahora
    )
    ultimo_contacto_en: Mapped[datetime | None] = mapped_column(DateTime)

    empresa: Mapped[Empresa] = relationship(back_populates="lead")
    actividades: Mapped[list["Actividad"]] = relationship(
        back_populates="lead",
        cascade="all, delete-orphan",
        order_by="Actividad.creada_en.desc()",
    )

    @property
    def lista_razones(self) -> list[str]:
        return [r for r in (self.razones or "").splitlines() if r.strip()]

    @property
    def dias_sin_contacto(self) -> int | None:
        if self.ultimo_contacto_en is None:
            return None
        return (ahora() - self.ultimo_contacto_en.replace(tzinfo=timezone.utc)).days


class Actividad(Base):
    """Timeline del lead: qué se hizo y qué detectó el sistema."""

    __tablename__ = "actividades"

    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"), index=True)
    # "nota" | "cambio_estado" | "contacto" | "senal" (generada por la ingesta)
    tipo: Mapped[str] = mapped_column(String(40), default="nota")
    detalle: Mapped[str] = mapped_column(Text)
    autor: Mapped[str | None] = mapped_column(String(120))
    creada_en: Mapped[datetime] = mapped_column(DateTime, default=ahora)

    lead: Mapped[Lead] = relationship(back_populates="actividades")


class PerfilConsultora(Base):
    """Los datos de Talanton y su ICP. Alimenta el eje de fit del scoring."""

    __tablename__ = "perfil_consultora"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(200), default="Talanton")
    descripcion: Mapped[str | None] = mapped_column(Text)
    sitio_web: Mapped[str | None] = mapped_column(String(300))
    email_contacto: Mapped[str | None] = mapped_column(String(200))

    # ICP: listas separadas por coma. Vacío = sin filtro en ese eje.
    industrias_objetivo: Mapped[str] = mapped_column(Text, default="")
    paises_objetivo: Mapped[str] = mapped_column(Text, default="AR")
    dotacion_min: Mapped[int] = mapped_column(Integer, default=20)
    dotacion_max: Mapped[int] = mapped_column(Integer, default=2000)
    seniorities_objetivo: Mapped[str] = mapped_column(
        Text, default="senior,jefatura,direccion"
    )
    fee_promedio: Mapped[int | None] = mapped_column(Integer)

    @staticmethod
    def _lista(valor: str | None) -> list[str]:
        return [x.strip() for x in (valor or "").split(",") if x.strip()]

    @property
    def industrias(self) -> list[str]:
        return self._lista(self.industrias_objetivo)

    @property
    def paises(self) -> list[str]:
        return self._lista(self.paises_objetivo)

    @property
    def seniorities(self) -> list[str]:
        return self._lista(self.seniorities_objetivo)
