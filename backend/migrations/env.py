"""Alembic setup. The connection string and the tables both come from the application, so there is one
source of truth: change a model, generate a revision, and upgrade."""
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from app.core.database import Base

# Importing these registers every table on Base.metadata; without them a revision would drop tables.
from app.core import audit  # noqa: F401
from app.integrations import models as integration_models  # noqa: F401
from app.modules.dispatch import models as dispatch_models  # noqa: F401
from app.modules.forecast import supply as supply_models  # noqa: F401
from app.modules.users import models as user_models  # noqa: F401
from app.modules.alerts import models as alert_models  # noqa: F401
from app.modules.stock import models as stock_models  # noqa: F401

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _run(connection):
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True,
                      render_as_batch=connection.dialect.name == "sqlite")
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_offline() -> None:
    context.configure(url=settings.database_url, target_metadata=target_metadata, literal_binds=True,
                      dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(settings.database_url, poolclass=None)
    async with engine.connect() as connection:
        await connection.run_sync(_run)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
