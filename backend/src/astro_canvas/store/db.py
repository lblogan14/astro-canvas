"""SQLite engine construction and Alembic migrations run programmatically."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, event

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def make_engine(path: Path | str) -> Engine:
    """SQLite engine with WAL, foreign keys and cross-thread connections enabled."""
    url = "sqlite:///:memory:" if str(path) == ":memory:" else f"sqlite:///{Path(path).as_posix()}"
    engine = create_engine(url, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_connection: Any, _record: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        if str(path) != ":memory:":
            cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    return engine


def alembic_config(engine: Engine | None = None) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.set_main_option("sqlalchemy.url", str(engine.url) if engine is not None else "")
    if engine is not None:
        config.attributes["engine"] = engine
    return config


def migrate(engine: Engine, revision: str = "head") -> None:
    """Upgrade ``engine``'s database to ``revision`` (creates it when missing)."""
    command.upgrade(alembic_config(engine), revision)


def current_revision(engine: Engine) -> str | None:
    from alembic.runtime.migration import MigrationContext  # noqa: PLC0415

    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()
