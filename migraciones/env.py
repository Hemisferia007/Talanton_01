"""Entorno de Alembic.

La URL sale de la configuración de la app, no de alembic.ini: así las
migraciones apuntan siempre al mismo lugar que el servidor.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from talanton.db import URL_EFECTIVA
from talanton.models import Base

config = context.config
config.set_main_option("sqlalchemy.url", URL_EFECTIVA.replace("%", "%%"))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=URL_EFECTIVA,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # SQLite no sabe hacer ALTER de columnas: sin esto, cualquier
            # cambio de tipo o de nullable falla en desarrollo.
            render_as_batch=connection.dialect.name == "sqlite",
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
