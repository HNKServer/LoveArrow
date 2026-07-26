"""Exact profile-specific immutable accessory master access.

The CN and GL clients do not ship the same accessory catalogue.  Mutable player
inventory remains in ``main.sqlite3``; this module only reads the supplied
clients' decrypted read-only unit masters.  Results which are requested many
times during one API call use NPPS4's ordinary request-local context cache and
are released at the end of that request.  No per-user or session inventory is
preloaded or retained.
"""
from __future__ import annotations

from contextlib import closing
import importlib.resources as resources
from pathlib import Path
import sqlite3
from typing import Any

from . import common
from .. import idol

_ALLOWED_PROFILES = frozenset({"cn", "gl"})


def _normalize_profile(value: str) -> str:
    profile = str(value).lower()
    if profile not in _ALLOWED_PROFILES:
        raise ValueError(f"unsupported client profile: {value}")
    return profile


def database_path(profile: str) -> str:
    normalized = _normalize_profile(profile)
    filename = "cn_client_master.db" if normalized == "cn" else "gl_client_master.db"
    ref = resources.files("npps4.assets").joinpath(filename)
    path = Path(str(ref))
    if not path.is_file():
        raise RuntimeError(f"Bundled {normalized.upper()} accessory master is unavailable: {filename}")
    return str(path)


def _query(profile: str, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    path = database_path(profile)
    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        return [dict(row) for row in db.execute(sql, params or {}).fetchall()]


def _table_exists(profile: str, table: str) -> bool:
    rows = _query(
        profile,
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=:name LIMIT 1",
        {"name": str(table)},
    )
    return bool(rows)


@common.context_cacheable("profile_accessory_table_exists")
async def _table_exists_cached(
    context: idol.BasicSchoolIdolContext, key: tuple[str, str], /
) -> bool:
    del context
    profile, table = key
    return _table_exists(profile, table)


async def table_exists(context: idol.BasicSchoolIdolContext, table: str) -> bool:
    return await _table_exists_cached(context, (context.profile.value, str(table)))


async def raw_rows(
    context: idol.BasicSchoolIdolContext,
    sql: str,
    params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    # This helper intentionally does not cache arbitrary SQL. Callers which
    # repeatedly fetch the same master object use the typed cached functions
    # below. It exists for the small lottery/base-setting tables and validators.
    return _query(context.profile.value, str(sql), params)


def raw_rows_for_profile(
    profile: str,
    sql: str,
    params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Read one immutable accessory Master explicitly by profile.

    Shared player inventory can contain a dedicated accessory obtained while
    using the other client family.  Serial-code repair therefore has to resolve
    the official target card from the Master which owns that accessory, not
    merely from the currently selected profile.  This helper never reads APKs
    or mutable player data and opens the bundled database read-only.
    """
    return _query(_normalize_profile(profile), str(sql), params)


@common.context_cacheable("profile_accessory_master_by_id")
async def _accessory_by_key(
    context: idol.BasicSchoolIdolContext, key: tuple[str, int], /
) -> dict[str, Any] | None:
    del context
    profile, accessory_id = key
    rows = _query(
        profile,
        """SELECT accessory_id, name, name_en, rarity,
                  COALESCE(smile_max,0) AS smile_max,
                  COALESCE(pure_max,0) AS pure_max,
                  COALESCE(cool_max,0) AS cool_max,
                  COALESCE(is_material,0) AS is_material,
                  COALESCE(effect_type,0) AS effect_type,
                  COALESCE(default_max_level,1) AS default_max_level,
                  COALESCE(max_level,COALESCE(default_max_level,1)) AS max_level,
                  COALESCE(accessory_asset_id,accessory_id) AS accessory_asset_id,
                  COALESCE(trigger_type,0) AS trigger_type,
                  COALESCE(trigger_effect_type,0) AS trigger_effect_type,
                  open_date
             FROM accessory_m WHERE accessory_id=:id LIMIT 1""",
        {"id": int(accessory_id)},
    )
    return rows[0] if rows else None


async def accessory_by_id(
    context: idol.BasicSchoolIdolContext, accessory_id: int
) -> dict[str, Any] | None:
    return await _accessory_by_key(context, (context.profile.value, int(accessory_id)))


@common.context_cacheable("profile_accessory_level_rows")
async def _level_rows_by_key(
    context: idol.BasicSchoolIdolContext, key: tuple[str, int], /
) -> tuple[dict[str, Any], ...]:
    del context
    profile, accessory_id = key
    return tuple(
        _query(
            profile,
            """SELECT accessory_id, level, COALESCE(next_exp,0) AS next_exp,
                      COALESCE(effect_range,0) AS effect_range,
                      COALESCE(effect_value,0) AS effect_value,
                      COALESCE(discharge_time,0) AS discharge_time,
                      COALESCE(trigger_value,0) AS trigger_value,
                      COALESCE(activation_rate,0) AS activation_rate,
                      COALESCE(unit_skill_combo_pattern_id,0) AS unit_skill_combo_pattern_id,
                      COALESCE(spark_count_limit,0) AS spark_count_limit,
                      COALESCE(smile_diff,0) AS smile_diff,
                      COALESCE(pure_diff,0) AS pure_diff,
                      COALESCE(cool_diff,0) AS cool_diff,
                      COALESCE(grant_exp,0) AS grant_exp,
                      COALESCE(merge_cost,0) AS merge_cost,
                      COALESCE(sale_price,0) AS sale_price
                 FROM accessory_level_m
                WHERE accessory_id=:id ORDER BY level ASC""",
            {"id": int(accessory_id)},
        )
    )


async def level_rows(
    context: idol.BasicSchoolIdolContext, accessory_id: int
) -> list[dict[str, Any]]:
    return list(await _level_rows_by_key(context, (context.profile.value, int(accessory_id))))


@common.context_cacheable("profile_accessory_rows")
async def _accessory_rows_by_key(
    context: idol.BasicSchoolIdolContext, key: tuple[str, int], /
) -> tuple[dict[str, Any], ...]:
    del context
    profile, material_filter = key
    where = ""
    if material_filter > 0:
        where = " WHERE COALESCE(is_material,0) != 0"
    elif material_filter == 0:
        where = " WHERE COALESCE(is_material,0) = 0"
    return tuple(
        _query(
            profile,
            """SELECT accessory_id, name, name_en, rarity,
                      COALESCE(smile_max,0) AS smile_max,
                      COALESCE(pure_max,0) AS pure_max,
                      COALESCE(cool_max,0) AS cool_max,
                      COALESCE(is_material,0) AS is_material,
                      COALESCE(effect_type,0) AS effect_type,
                      COALESCE(default_max_level,1) AS default_max_level,
                      COALESCE(max_level,COALESCE(default_max_level,1)) AS max_level,
                      COALESCE(accessory_asset_id,accessory_id) AS accessory_asset_id,
                      COALESCE(trigger_type,0) AS trigger_type,
                      COALESCE(trigger_effect_type,0) AS trigger_effect_type,
                      open_date
                 FROM accessory_m"""
            + where
            + " ORDER BY accessory_id ASC",
        )
    )


async def accessory_rows(
    context: idol.BasicSchoolIdolContext, *, materials: bool | None = None
) -> list[dict[str, Any]]:
    marker = -1 if materials is None else int(bool(materials))
    return list(await _accessory_rows_by_key(context, (context.profile.value, marker)))


@common.context_cacheable("profile_accessory_special_target")
async def _special_target_by_key(
    context: idol.BasicSchoolIdolContext, key: tuple[str, int], /
) -> int | None:
    del context
    profile, accessory_id = key
    rows = _query(
        profile,
        "SELECT unit_id FROM accessory_special_m WHERE accessory_id=:id LIMIT 1",
        {"id": int(accessory_id)},
    )
    return int(rows[0]["unit_id"]) if rows else None


async def special_target(
    context: idol.BasicSchoolIdolContext, accessory_id: int
) -> int | None:
    return await _special_target_by_key(context, (context.profile.value, int(accessory_id)))


@common.context_cacheable("profile_special_accessory_for_unit")
async def _special_accessory_by_unit_key(
    context: idol.BasicSchoolIdolContext, key: tuple[str, int], /
) -> int | None:
    del context
    profile, unit_id = key
    rows = _query(
        profile,
        "SELECT accessory_id FROM accessory_special_m WHERE unit_id=:id LIMIT 1",
        {"id": int(unit_id)},
    )
    return int(rows[0]["accessory_id"]) if rows else None


async def special_accessory_for_unit(
    context: idol.BasicSchoolIdolContext, unit_id: int
) -> int | None:
    return await _special_accessory_by_unit_key(context, (context.profile.value, int(unit_id)))


def counts(profile: str) -> dict[str, int]:
    normalized = _normalize_profile(profile)
    result: dict[str, int] = {}
    for table in (
        "accessory_m",
        "accessory_special_m",
        "accessory_level_m",
        "accessory_lottery_list_m",
    ):
        result[table] = int(_query(normalized, f"SELECT COUNT(*) AS amount FROM {table}")[0]["amount"])
    return result
