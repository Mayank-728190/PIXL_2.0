import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from pixl.core.config import settings
from pixl.core.database import Base

# Import all models for migration autogeneration
import pixl.core.identifiers  # noqa
import pixl.modules.auth.models  # noqa
import pixl.modules.organizations.models  # noqa
import pixl.modules.screens.models  # noqa
import pixl.modules.media.models  # noqa
import pixl.modules.playlists.models  # noqa
import pixl.modules.campaigns.models  # noqa
import pixl.modules.ingestion.models  # noqa

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata
# ConfigParser treats percent-encoded URL credentials as interpolation syntax.
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL.replace("%", "%%"))


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
