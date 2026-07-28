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
    eventos: Mapped[list["Evento"]] = relationship(
        back_populates="empresa",
        cascade="all, delete-orphan",
        order_by="Evento.fecha.desc()",
    )

    @property
    def eventos_vigentes(self) -> list["Evento"]:
        return [e for e in self.eventos if e.vigente]

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
    # La fuente dio la antigüedad en texto relativo: los días abiertos salen
    # con varios días de error y hay que decirlo en vez de fingir precisión.
    fecha_aproximada: Mapped[bool] = mapped_column(Boolean, default=False)
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
    # Orden cronológico ascendente: el hilo se lee como un chat, de arriba
    # hacia abajo.
    mensajes: Mapped[list["Mensaje"]] = relationship(
        back_populates="lead",
        cascade="all, delete-orphan",
        order_by="Mensaje.creado_en",
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


class Usuario(Base):
    """Quién puede entrar. La app maneja datos de contacto de terceros y
    credenciales de Gmail: no puede quedar abierta a quien tenga la URL."""

    __tablename__ = "usuarios"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    nombre: Mapped[str] = mapped_column(String(200))
    # scrypt con salt por usuario. Formato: scrypt$n$r$p$salt_hex$hash_hex
    password_hash: Mapped[str] = mapped_column(String(400))
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime, default=ahora)
    ultimo_ingreso: Mapped[datetime | None] = mapped_column(DateTime)


class CuentaGmail(Base):
    """Una casilla conectada por OAuth desde la que se manda.

    Se guarda el refresh token cifrado (ver correo/cripto.py); el access token
    dura una hora y se renueva solo.
    """

    __tablename__ = "cuentas_gmail"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    nombre_remitente: Mapped[str | None] = mapped_column(String(200))
    firma: Mapped[str | None] = mapped_column(Text)

    refresh_token_cifrado: Mapped[str] = mapped_column(Text)
    access_token: Mapped[str | None] = mapped_column(Text)
    access_token_expira: Mapped[datetime | None] = mapped_column(DateTime)

    activa: Mapped[bool] = mapped_column(Boolean, default=True)
    conectada_en: Mapped[datetime] = mapped_column(DateTime, default=ahora)
    ultimo_error: Mapped[str | None] = mapped_column(Text)

    mensajes: Mapped[list["Mensaje"]] = relationship(back_populates="cuenta")

    @property
    def etiqueta(self) -> str:
        return f"{self.nombre_remitente} <{self.email}>" if self.nombre_remitente else self.email


class EstadoMensaje(str, enum.Enum):
    BORRADOR = "borrador"
    ENVIADO = "enviado"
    ERROR = "error"
    RECIBIDO = "recibido"

    @property
    def etiqueta(self) -> str:
        return {
            "borrador": "Borrador",
            "enviado": "Enviado",
            "error": "Falló",
            "recibido": "Recibido",
        }[self.value]


class Direccion(str, enum.Enum):
    """Quién escribió. Es lo que permite mostrar el hilo como conversación."""

    SALIENTE = "saliente"
    ENTRANTE = "entrante"


class Mensaje(Base):
    """Un mail redactado desde el CRM. Queda registrado se envíe o no."""

    __tablename__ = "mensajes"

    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"), index=True)
    cuenta_id: Mapped[int | None] = mapped_column(ForeignKey("cuentas_gmail.id"))

    direccion: Mapped[Direccion] = mapped_column(
        Enum(Direccion), default=Direccion.SALIENTE, index=True
    )
    para: Mapped[str] = mapped_column(String(300))
    # En los entrantes es quien nos escribió; en los salientes queda en None y
    # se muestra la casilla de la cuenta.
    de: Mapped[str | None] = mapped_column(String(300))
    asunto: Mapped[str] = mapped_column(String(400))
    cuerpo: Mapped[str] = mapped_column(Text)
    plantilla: Mapped[str | None] = mapped_column(String(60))

    estado: Mapped[EstadoMensaje] = mapped_column(
        Enum(EstadoMensaje), default=EstadoMensaje.BORRADOR, index=True
    )
    gmail_message_id: Mapped[str | None] = mapped_column(String(120))
    gmail_thread_id: Mapped[str | None] = mapped_column(String(120))
    error: Mapped[str | None] = mapped_column(Text)

    creado_en: Mapped[datetime] = mapped_column(DateTime, default=ahora)
    enviado_en: Mapped[datetime | None] = mapped_column(DateTime)

    lead: Mapped["Lead"] = relationship(back_populates="mensajes")
    cuenta: Mapped[CuentaGmail | None] = relationship(back_populates="mensajes")

    @property
    def es_entrante(self) -> bool:
        return self.direccion == Direccion.ENTRANTE

    @property
    def fecha(self) -> datetime:
        """La que ordena el hilo: cuándo ocurrió, no cuándo se guardó."""
        return self.enviado_en or self.creado_en


class TipoEvento(str, enum.Enum):
    FINANCIAMIENTO = "financiamiento"
    EXPANSION = "expansion"
    CONTRATACION = "contratacion"

    @property
    def etiqueta(self) -> str:
        return {
            "financiamiento": "Ronda de inversión",
            "expansion": "Expansión",
            "contratacion": "Anuncio de contratación",
        }[self.value]


class Evento(Base):
    """Una señal externa fechada sobre una empresa.

    A diferencia de una vacante, no es un estado que se estira sino un hecho
    puntual: levantaron una ronda, abrieron una planta, anunciaron que suman
    gente. No tiene «días abiertos»; lo que importa es cuán reciente es.

    Una ronda por sí sola no es un lead: una empresa con plata fresca que
    todavía no busca a nadie no necesita una consultora de selección. El valor
    aparece combinado — ronda + búsquedas abiertas es el mejor momento posible,
    y ronda sin búsquedas significa «vigilala, va a contratar en 60-90 días».
    """

    __tablename__ = "eventos"
    __table_args__ = (
        UniqueConstraint("fuente", "external_id", name="uq_evento_fuente_externa"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int | None] = mapped_column(ForeignKey("empresas.id"), index=True)

    tipo: Mapped[TipoEvento] = mapped_column(Enum(TipoEvento), index=True)
    titulo: Mapped[str] = mapped_column(String(400))
    resumen: Mapped[str | None] = mapped_column(Text)
    empresa_mencionada: Mapped[str | None] = mapped_column(String(200))

    fecha: Mapped[date] = mapped_column(Date, index=True)
    fecha_aproximada: Mapped[bool] = mapped_column(Boolean, default=False)

    fuente: Mapped[str] = mapped_column(String(60), index=True)
    fuente_url: Mapped[str | None] = mapped_column(String(600))
    external_id: Mapped[str] = mapped_column(String(200))

    # La detección sobre texto libre tiene falsos positivos, así que nada pesa
    # en el score hasta que una persona lo confirma. Fingir precisión acá
    # significa mandar un mail felicitando por una ronda que no existió.
    confirmado: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    descartado: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime, default=ahora)

    empresa: Mapped["Empresa | None"] = relationship(back_populates="eventos")

    @property
    def dias_desde(self) -> int:
        return max((ahora().date() - self.fecha).days, 0)

    @property
    def vigente(self) -> bool:
        """El efecto de una ronda sobre la contratación dura unos meses."""
        return self.confirmado and not self.descartado and self.dias_desde <= 270

    @property
    def pendiente_revision(self) -> bool:
        return not self.confirmado and not self.descartado


class Objetivo(Base):
    """Una empresa que queremos vigilar.

    Es lo único que el usuario carga a mano: un nombre y, si lo tiene, el
    dominio. El descubridor se encarga de averiguar dónde publica sus avisos.
    """

    __tablename__ = "objetivos"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(200))
    nombre_normalizado: Mapped[str] = mapped_column(String(200), index=True)
    dominio: Mapped[str | None] = mapped_column(String(200))
    activo: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    creado_en: Mapped[datetime] = mapped_column(DateTime, default=ahora)
    # None mientras no se sondeó nunca: así la corrida diaria sabe qué le falta.
    revisado_en: Mapped[datetime | None] = mapped_column(DateTime)
    # None = pendiente | "ok" = se le encontró al menos una fuente | "sin_fuente"
    resultado: Mapped[str | None] = mapped_column(String(20), index=True)
    detalle: Mapped[str | None] = mapped_column(Text)

    fuentes: Mapped[list["Fuente"]] = relationship(
        back_populates="objetivo", cascade="all, delete-orphan"
    )

    @property
    def pendiente(self) -> bool:
        return self.revisado_en is None

    @property
    def estado_etiqueta(self) -> str:
        if self.pendiente:
            return "Pendiente de sondeo"
        if self.resultado == "ok":
            n = len([f for f in self.fuentes if f.activa])
            return f"{n} fuente{'s' if n != 1 else ''}"
        return "Sin fuente automática"


class Fuente(Base):
    """De dónde se leen avisos: un board de ATS o una página de carrera.

    Vive en la base y no en un archivo para que se pueda administrar desde la
    web: en un hosting sin consola, editar un JSON del repo y redesplegar no es
    una opción razonable para una tarea de todos los días.
    """

    __tablename__ = "fuentes"
    __table_args__ = (
        UniqueConstraint("tipo", "identificador", name="uq_fuente_tipo_identificador"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    objetivo_id: Mapped[int | None] = mapped_column(ForeignKey("objetivos.id"), index=True)

    # greenhouse | lever | ashby | recruitee | workable | pagina_carrera
    tipo: Mapped[str] = mapped_column(String(40), index=True)
    # El slug del board, o la URL en el caso de página de carrera.
    identificador: Mapped[str] = mapped_column(String(600))
    empresa: Mapped[str] = mapped_column(String(200))
    dominio: Mapped[str | None] = mapped_column(String(200))
    stealth: Mapped[bool] = mapped_column(Boolean, default=False)

    activa: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    creada_en: Mapped[datetime] = mapped_column(DateTime, default=ahora)
    ultima_corrida: Mapped[datetime | None] = mapped_column(DateTime)
    avisos_ultima_corrida: Mapped[int | None] = mapped_column(Integer)
    ultimo_error: Mapped[str | None] = mapped_column(Text)

    objetivo: Mapped[Objetivo | None] = relationship(back_populates="fuentes")

    @property
    def etiqueta(self) -> str:
        return f"{self.tipo}:{self.identificador}"

    @property
    def anda(self) -> bool | None:
        """None si nunca corrió."""
        if self.ultima_corrida is None:
            return None
        return self.ultimo_error is None


class CorridaIngesta(Base):
    """Qué trajo cada corrida diaria.

    Sin esto, una fuente que se rompe o un fuentes.json mal configurado dan
    exactamente el mismo resultado que un día tranquilo: cero avisos nuevos y
    ningún error a la vista. Y como el histórico es el activo, enterarse dos
    meses después de que no se estaba juntando nada es el peor escenario.
    """

    __tablename__ = "corridas_ingesta"

    id: Mapped[int] = mapped_column(primary_key=True)
    iniciada_en: Mapped[datetime] = mapped_column(DateTime, default=ahora, index=True)
    terminada_en: Mapped[datetime | None] = mapped_column(DateTime)

    fuentes_ok: Mapped[int] = mapped_column(Integer, default=0)
    fuentes_con_error: Mapped[int] = mapped_column(Integer, default=0)
    avisos_encontrados: Mapped[int] = mapped_column(Integer, default=0)
    avisos_nuevos: Mapped[int] = mapped_column(Integer, default=0)
    avisos_cerrados: Mapped[int] = mapped_column(Integer, default=0)

    # Detalle por conector, una línea por fuente. Texto plano a propósito: se
    # lee de un vistazo y no obliga a nada del otro lado.
    detalle: Mapped[str] = mapped_column(Text, default="")

    @property
    def sin_resultados(self) -> bool:
        """Una corrida que no encontró nada casi siempre es un problema."""
        return self.avisos_encontrados == 0

    @property
    def hubo_problemas(self) -> bool:
        return self.fuentes_con_error > 0 or self.sin_resultados

    @property
    def lineas_detalle(self) -> list[str]:
        return [l for l in (self.detalle or "").splitlines() if l.strip()]


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
