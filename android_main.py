# Android-specific NPPS4 entrypoint for Chaquopy.
#
# Important: do NOT use Alembic on Android. Alembic is path-oriented and
# expects env.py and migration scripts to exist as normal files. In Chaquopy,
# bundled Python modules may live inside the APK/AssetFinder and are not stable
# filesystem paths. The Android wrapper initializes the server state database
# directly from SQLAlchemy metadata instead.

from __future__ import annotations

import asyncio
import os
import sqlite3
import traceback
import urllib.parse

import uvicorn

import npps4.config.config

npps4.config.config._override_script_mode(False)

had_run_once = False
server_instance = None


async def _create_server_schema_async() -> None:
    """Create or migrate the mutable NPPS4 server DB on Android.

    This is an Android-safe replacement for `alembic upgrade head`: it creates
    the current-head schema from SQLAlchemy metadata, reconciles missing safe
    tables/columns/indexes on older Android DBs, and stamps alembic_version with
    the current head. It does not touch the read-only game master DBs.
    """
    import npps4.android_schema as android_schema

    await android_schema.ensure_schema_async()


def setup_server():
    """Initialize the mutable server DB.

    Desktop NPPS4 runs `alembic upgrade head`. On Android, run the
    Android-safe schema initializer instead: it creates/reconciles the current
    head schema and stamps alembic_version without requiring Alembic script
    files to be addressable as real filesystem paths.
    """
    global had_run_once
    had_run_once = True
    asyncio.run(_create_server_schema_async())


def start_server(host: str = "127.0.0.1", port: int = 51376):
    global server_instance, had_run_once

    if server_instance is not None:
        raise RuntimeError("cannot start server twice")

    had_run_once = True
    import npps4.run.app

    cfg = uvicorn.Config(npps4.run.app.main, host=host, port=port, loop="npps4.evloop:new_event_loop")
    server_instance = uvicorn.Server(cfg)
    server_instance.run()
    server_instance = None


def stop_server():
    global server_instance

    si = server_instance
    if si is None or si.should_exit:
        raise RuntimeError("cannot stop server that's not started")

    si.should_exit = True


def _sqlite_db_path() -> str | None:
    parsed = urllib.parse.urlparse(npps4.config.config.get_database_url())
    if not (parsed.scheme == "sqlite" or parsed.scheme.startswith("sqlite+")):
        return None
    return os.path.join(npps4.config.config.ROOT_DIR, parsed.path[1:])


def import_database(db: bytes):
    if had_run_once:
        return 1  # ERROR_SERVER_ALREADY_RUN_ONCE

    if not db.startswith(b"SQLite format 3\0"):
        return 2  # ERROR_INVALID_SQLITE3

    dbpath = _sqlite_db_path()
    if dbpath is None:
        return 3  # ERROR_DATABASE_URL_NOT_SQLITE3

    try:
        os.makedirs(os.path.dirname(dbpath), exist_ok=True)
        with open(dbpath, "wb") as f:
            f.write(db)
        for suffix in ("-shm", "-wal"):
            try:
                os.remove(dbpath + suffix)
            except FileNotFoundError:
                pass
        return 0  # Ok
    except Exception as e:
        traceback.print_exception(e)
        return 4  # ERROR_UNKNOWN


def export_database():
    dbpath = _sqlite_db_path()
    if dbpath is None:
        return None

    try:
        with sqlite3.connect(f"file:{urllib.parse.quote(dbpath)}?mode=ro", timeout=60, uri=True) as conn:
            return conn.serialize()
    except Exception as e:
        traceback.print_exception(e)
        return None


def nuke_database():
    if had_run_once:
        return 1  # ERROR_SERVER_ALREADY_RUN_ONCE

    dbpath = _sqlite_db_path()
    if dbpath is None:
        return 3  # ERROR_DATABASE_URL_NOT_SQLITE3

    for path in (dbpath, dbpath + "-shm", dbpath + "-wal"):
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        except Exception as e:
            traceback.print_exception(e)
            return 4
    return 0
