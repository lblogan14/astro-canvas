"""Alembic environment for the identity database (async engine, own metadata).

The engine is asynchronous, so the migration runs inside ``connection.run_sync``. The caller
(``migrate_identity``) has already made sure no event loop is running in this thread.
"""

from __future__ import annotations

import asyncio

from alembic import context
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from astro_canvas.store.identity import IdentityBase

config = context.config
target_metadata = IdentityBase.metadata


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    engine = create_async_engine(config.get_main_option("sqlalchemy.url") or "sqlite+aiosqlite://")
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


asyncio.run(run_async_migrations())
