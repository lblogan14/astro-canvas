"""The identity database: URL normalisation and its own Alembic head."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from astro_canvas.settings import Settings
from astro_canvas.store.identity import (
    IdentityStore,
    async_url,
    identity_url,
    migrate_identity,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("postgresql://u:p@host/db", "postgresql+asyncpg://u:p@host/db"),
        ("postgres://u:p@host/db", "postgresql+asyncpg://u:p@host/db"),
        ("postgresql+psycopg://u:p@host/db", "postgresql+asyncpg://u:p@host/db"),
        ("postgresql+asyncpg://u:p@host/db", "postgresql+asyncpg://u:p@host/db"),
        ("sqlite:///./users.db", "sqlite+aiosqlite:///./users.db"),
        ("mysql+aiomysql://host/db", "mysql+aiomysql://host/db"),
        ("not-a-url", "not-a-url"),
    ],
)
def test_a_sync_driver_is_rewritten_to_the_async_one(raw: str, expected: str) -> None:
    """``DATABASE_URL`` is written by operators from Postgres docs, not from SQLAlchemy's."""
    assert async_url(raw) == expected


def test_the_default_url_is_a_sqlite_file_in_the_config_folder(tmp_path: Path) -> None:
    settings = Settings(workspace=tmp_path / "d", config_dir=tmp_path / "cfg")
    url = identity_url(settings)
    assert url.startswith("sqlite+aiosqlite:///")
    assert url.endswith("users.db")
    assert (tmp_path / "cfg").is_dir()


def test_database_url_wins_over_the_default(tmp_path: Path) -> None:
    settings = Settings(
        workspace=tmp_path / "d",
        config_dir=tmp_path / "cfg",
        database_url="postgresql://canvas@db/canvas",
    )
    assert identity_url(settings) == "postgresql+asyncpg://canvas@db/canvas"


def test_migrating_creates_the_two_tables(tmp_path: Path) -> None:
    path = tmp_path / "users.db"
    migrate_identity(f"sqlite+aiosqlite:///{path.as_posix()}")
    tables = {
        row[0]
        for row in sqlite3.connect(path).execute(
            "select name from sqlite_master where type='table'"
        )
    }
    assert {"users", "oauth_accounts", "alembic_version"} <= tables


def test_migrating_twice_is_a_no_op(tmp_path: Path) -> None:
    url = f"sqlite+aiosqlite:///{(tmp_path / 'users.db').as_posix()}"
    migrate_identity(url)
    migrate_identity(url)


async def test_migrating_works_from_inside_a_running_loop(tmp_path: Path) -> None:
    """``create_app`` runs before the loop, but a test (or an async host) runs inside one."""
    url = f"sqlite+aiosqlite:///{(tmp_path / 'users.db').as_posix()}"
    migrate_identity(url)
    store = IdentityStore(url)
    try:
        async for user_db in store.user_db():
            assert await user_db.get_by_email("nobody@example.com") is None
    finally:
        await store.close()


async def test_open_migrates_and_yields_a_usable_store(tmp_path: Path) -> None:
    settings = Settings(workspace=tmp_path / "d", config_dir=tmp_path / "cfg")
    store = IdentityStore.open(settings)
    try:
        assert (tmp_path / "cfg" / "users.db").is_file()
        async for session in store.session():
            assert session is not None
    finally:
        await store.close()
