"""Alembic environment: runs against the engine handed over in ``config.attributes``."""

from __future__ import annotations

from alembic import context
from sqlalchemy import Engine, create_engine

from astro_canvas.store.models import Base

config = context.config
target_metadata = Base.metadata


def run_migrations() -> None:
    engine: Engine | None = config.attributes.get("engine")
    if engine is None:
        engine = create_engine(config.get_main_option("sqlalchemy.url") or "sqlite://")
    with engine.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata, render_as_batch=True
        )
        with context.begin_transaction():
            context.run_migrations()


run_migrations()
