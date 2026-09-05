"""The identity database behind ``--auth users``: ``users`` and ``oauth_accounts`` (design 12).

Deliberately a **second** database. Everything else the app persists lives in
``<workspace>/.astro-canvas/app.db``, and in a lab deployment every user has their own workspace --
so the one table they must all share cannot live there. ``DATABASE_URL`` points it at Postgres for
a real deployment and it falls back to ``<config>/users.db`` for a single-host trial.

fastapi-users talks to SQLAlchemy asynchronously, so this module owns an ``AsyncEngine`` while
``store/db.py`` keeps the synchronous workspace engines. The two Alembic trees are independent:
``store/migrations`` upgrades a workspace, ``store/identity_migrations`` upgrades this one.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING, Any

from alembic import command
from alembic.config import Config
from fastapi_users_db_sqlalchemy import (
    SQLAlchemyBaseOAuthAccountTableUUID,
    SQLAlchemyBaseUserTableUUID,
    SQLAlchemyUserDatabase,
)
from fastapi_users_db_sqlalchemy.generics import GUID
from sqlalchemy import ForeignKey, String
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

if TYPE_CHECKING:  # pragma: no cover - typing only
    from astro_canvas.settings import Settings

MIGRATIONS_DIR = Path(__file__).resolve().parent / "identity_migrations"
DEFAULT_DB_NAME = "users.db"

ASYNC_DRIVERS = {
    "postgres": "postgresql+asyncpg",
    "postgresql": "postgresql+asyncpg",
    "postgresql+psycopg": "postgresql+asyncpg",
    "postgresql+psycopg2": "postgresql+asyncpg",
    "sqlite": "sqlite+aiosqlite",
}
"""URL schemes rewritten to the async driver this app actually installs."""


class IdentityBase(DeclarativeBase):
    """Declarative base for the identity tables (kept apart from ``store.models.Base``)."""


class OAuthAccount(SQLAlchemyBaseOAuthAccountTableUUID, IdentityBase):
    """One linked GitHub or OpenID account (ORCID arrives through the generic OIDC client)."""

    __tablename__ = "oauth_accounts"

    # fastapi-users' base points this at its own default table name (``user``); the tables here
    # are plural, so the foreign key has to be restated.
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="cascade"), nullable=False
    )


class User(SQLAlchemyBaseUserTableUUID, IdentityBase):
    """A login. ``is_superuser`` is the admin flag that unlocks the pack manager (design 12)."""

    __tablename__ = "users"

    display_name: Mapped[str] = mapped_column(String(255), default="", server_default="")
    oauth_accounts: Mapped[list[OAuthAccount]] = relationship(
        "OAuthAccount", lazy="joined", cascade="all, delete-orphan"
    )


def async_url(raw: str) -> str:
    """Rewrite a database URL to the async driver, leaving an explicit one alone.

    Args:
        raw: A SQLAlchemy URL, possibly with a synchronous driver (``postgresql://``).

    Returns:
        The same URL with an async driver (``postgresql+asyncpg://``).
    """
    scheme, separator, rest = raw.partition("://")
    if not separator:
        return raw
    return f"{ASYNC_DRIVERS.get(scheme, scheme)}://{rest}"


def identity_url(settings: Settings) -> str:
    """The identity database URL for ``settings`` (``DATABASE_URL`` or ``<config>/users.db``)."""
    if settings.database_url:
        return async_url(settings.database_url)
    path = Path(settings.config_dir) / DEFAULT_DB_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite+aiosqlite:///{path.as_posix()}"


def alembic_config(url: str) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    # Alembic reads the URL through ConfigParser, which treats ``%`` as interpolation.
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


def migrate_identity(url: str, revision: str = "head") -> None:
    """Upgrade the identity database, from inside or outside a running event loop.

    Alembic's ``upgrade`` is synchronous and the engine is not, so the migration runs its own
    loop. Called from ``create_app`` that loop does not exist yet; called from a test (or any
    other already-async caller) it cannot be nested, so it goes to a worker thread instead.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        command.upgrade(alembic_config(url), revision)
        return
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="astro-identity") as pool:
        pool.submit(command.upgrade, alembic_config(url), revision).result()


class IdentityStore:
    """Engine, sessions and the fastapi-users adapter for one identity database."""

    def __init__(self, url: str, *, engine: AsyncEngine | None = None) -> None:
        self.url = url
        self.engine = engine if engine is not None else create_async_engine(url)
        self.sessions: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self.engine, expire_on_commit=False
        )

    @classmethod
    def open(cls, settings: Settings) -> IdentityStore:
        """Migrate the configured identity database and return a store bound to it."""
        url = identity_url(settings)
        migrate_identity(url)
        return cls(url)

    async def session(self) -> AsyncIterator[AsyncSession]:
        """One ``AsyncSession`` (a FastAPI dependency)."""
        async with self.sessions() as session:
            yield session

    async def user_db(self) -> AsyncIterator[SQLAlchemyUserDatabase[User, Any]]:
        """The fastapi-users database adapter (a FastAPI dependency)."""
        async with self.sessions() as session:
            yield SQLAlchemyUserDatabase(session, User, OAuthAccount)

    async def close(self) -> None:
        await self.engine.dispose()


__all__ = [
    "IdentityBase",
    "IdentityStore",
    "OAuthAccount",
    "User",
    "async_url",
    "identity_url",
    "migrate_identity",
]
