"""Lazy, profile-keyed read-only master database connections."""
from __future__ import annotations

import threading
from typing import Any

import sqlalchemy.ext.asyncio
import sqlalchemy.pool

from .. import client_profile
from ..download import download

_LOCK = threading.RLock()
_SESSIONMAKERS: dict[tuple[client_profile.ClientProfile, str, str], sqlalchemy.ext.asyncio.async_sessionmaker] = {}


def get_sessionmaker(
    database_name: str,
    profile: client_profile.ClientProfile | str | None = None,
) -> sqlalchemy.ext.asyncio.async_sessionmaker:
    normalized = client_profile.current() if profile is None else client_profile.ClientProfile.normalize(profile)
    path = download.get_db_path(database_name, normalized)
    key = (normalized, database_name, path)
    with _LOCK:
        existing = _SESSIONMAKERS.get(key)
        if existing is not None:
            return existing
        engine = sqlalchemy.ext.asyncio.create_async_engine(
            f"sqlite+aiosqlite:///file:{path}?mode=ro&uri=true",
            poolclass=sqlalchemy.pool.NullPool,
            connect_args={"check_same_thread": False},
        )
        result = sqlalchemy.ext.asyncio.async_sessionmaker(engine)
        _SESSIONMAKERS[key] = result
        return result


def clear() -> None:
    # Engines are deliberately process-lifetime objects.  This clears only the
    # lookup cache for tests/config reloads; callers should not use it while
    # requests are active.
    with _LOCK:
        _SESSIONMAKERS.clear()
