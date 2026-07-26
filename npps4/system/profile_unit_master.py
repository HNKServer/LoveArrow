"""Exact profile-specific immutable unit master access.

The mutable account database is shared between CN and GL, but the final clients
ship different unit catalogues and different level-limit growth curves.  This
module reads the supplied final clients' decrypted unit masters directly.  It
is used only as a receiver-profile fallback when the configured split master is
missing a row, and for deterministic cross-profile score normalization.

Only request-local NPPS4 context caches are used.  No player inventory or whole
catalogue is retained per user/session.
"""
from __future__ import annotations

from contextlib import closing
import importlib.resources as resources
from pathlib import Path
import sqlite3
from types import SimpleNamespace
from typing import Any, Iterable

from . import common
from .. import client_profile
from .. import idol

_ALLOWED_PROFILES = frozenset({"cn", "gl"})


def _normalize_profile(value: client_profile.ClientProfile | str) -> str:
    profile = getattr(value, "value", value)
    normalized = str(profile).lower()
    if normalized not in _ALLOWED_PROFILES:
        raise ValueError(f"unsupported client profile: {value}")
    return normalized


def database_path(profile: client_profile.ClientProfile | str) -> str:
    normalized = _normalize_profile(profile)
    filename = "cn_unit_master.db" if normalized == "cn" else "gl_client_master.db"
    ref = resources.files("npps4.assets").joinpath(filename)
    path = Path(str(ref))
    if not path.is_file():
        raise RuntimeError(f"Bundled {normalized.upper()} unit master is unavailable: {filename}")
    return str(path)


def _query(
    profile: client_profile.ClientProfile | str,
    sql: str,
    params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    path = database_path(profile)
    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        return [dict(row) for row in db.execute(sql, params or {}).fetchall()]


def _namespace(row: dict[str, Any] | None) -> SimpleNamespace | None:
    return None if row is None else SimpleNamespace(**row)


def _namespaces(rows: Iterable[dict[str, Any]]) -> list[SimpleNamespace]:
    return [SimpleNamespace(**row) for row in rows]


@common.context_cacheable("profile_unit_master_unit")
async def _unit_by_key(
    context: idol.BasicSchoolIdolContext, key: tuple[str, int], /
) -> SimpleNamespace | None:
    del context
    profile, unit_id = key
    rows = _query(profile, "SELECT * FROM unit_m WHERE unit_id=:id LIMIT 1", {"id": int(unit_id)})
    return _namespace(rows[0] if rows else None)


async def unit_by_id(context: idol.BasicSchoolIdolContext, unit_id: int) -> SimpleNamespace | None:
    return await _unit_by_key(context, (context.profile.value, int(unit_id)))


@common.context_cacheable("profile_unit_master_rarity")
async def _rarity_by_key(
    context: idol.BasicSchoolIdolContext, key: tuple[str, int], /
) -> SimpleNamespace | None:
    del context
    profile, rarity = key
    rows = _query(profile, "SELECT * FROM unit_rarity_m WHERE rarity=:id LIMIT 1", {"id": int(rarity)})
    return _namespace(rows[0] if rows else None)


async def rarity_by_id(context: idol.BasicSchoolIdolContext, rarity: int) -> SimpleNamespace | None:
    return await _rarity_by_key(context, (context.profile.value, int(rarity)))


@common.context_cacheable("profile_unit_master_level_up")
async def _level_up_by_key(
    context: idol.BasicSchoolIdolContext, key: tuple[str, int], /
) -> tuple[SimpleNamespace, ...]:
    del context
    profile, pattern_id = key
    return tuple(
        _namespaces(
            _query(
                profile,
                "SELECT * FROM unit_level_up_pattern_m "
                "WHERE unit_level_up_pattern_id=:id ORDER BY unit_level",
                {"id": int(pattern_id)},
            )
        )
    )


async def level_up_rows(context: idol.BasicSchoolIdolContext, pattern_id: int) -> list[SimpleNamespace]:
    return list(await _level_up_by_key(context, (context.profile.value, int(pattern_id))))


@common.context_cacheable("profile_unit_master_level_limit")
async def _level_limit_by_key(
    context: idol.BasicSchoolIdolContext, key: tuple[str, int], /
) -> tuple[SimpleNamespace, ...]:
    del context
    profile, level_limit_id = key
    return tuple(
        _namespaces(
            _query(
                profile,
                "SELECT * FROM unit_level_limit_pattern_m "
                "WHERE unit_level_limit_id=:id ORDER BY unit_level",
                {"id": int(level_limit_id)},
            )
        )
    )


async def level_limit_rows(
    context: idol.BasicSchoolIdolContext,
    level_limit_id: int,
    *,
    profile: client_profile.ClientProfile | str | None = None,
) -> list[SimpleNamespace]:
    resolved = context.profile.value if profile is None else _normalize_profile(profile)
    return list(await _level_limit_by_key(context, (resolved, int(level_limit_id))))


@common.context_cacheable("profile_unit_master_skill")
async def _skill_by_key(
    context: idol.BasicSchoolIdolContext, key: tuple[str, int], /
) -> SimpleNamespace | None:
    del context
    profile, skill_id = key
    rows = _query(profile, "SELECT * FROM unit_skill_m WHERE unit_skill_id=:id LIMIT 1", {"id": int(skill_id)})
    return _namespace(rows[0] if rows else None)


async def skill_by_id(context: idol.BasicSchoolIdolContext, skill_id: int) -> SimpleNamespace | None:
    return await _skill_by_key(context, (context.profile.value, int(skill_id)))


@common.context_cacheable("profile_unit_master_skill_level_up")
async def _skill_level_up_by_key(
    context: idol.BasicSchoolIdolContext, key: tuple[str, int], /
) -> tuple[SimpleNamespace, ...]:
    del context
    profile, pattern_id = key
    return tuple(
        _namespaces(
            _query(
                profile,
                "SELECT * FROM unit_skill_level_up_pattern_m "
                "WHERE unit_skill_level_up_pattern_id=:id ORDER BY skill_level",
                {"id": int(pattern_id)},
            )
        )
    )


async def skill_level_up_rows(
    context: idol.BasicSchoolIdolContext, pattern_id: int
) -> list[SimpleNamespace]:
    return list(await _skill_level_up_by_key(context, (context.profile.value, int(pattern_id))))


@common.context_cacheable("profile_unit_master_leader")
async def _leader_by_key(
    context: idol.BasicSchoolIdolContext, key: tuple[str, int], /
) -> SimpleNamespace | None:
    del context
    profile, leader_id = key
    rows = _query(
        profile,
        "SELECT * FROM unit_leader_skill_m WHERE unit_leader_skill_id=:id LIMIT 1",
        {"id": int(leader_id)},
    )
    return _namespace(rows[0] if rows else None)


async def leader_by_id(context: idol.BasicSchoolIdolContext, leader_id: int) -> SimpleNamespace | None:
    return await _leader_by_key(context, (context.profile.value, int(leader_id)))


@common.context_cacheable("profile_unit_master_extra_leader")
async def _extra_leader_by_key(
    context: idol.BasicSchoolIdolContext, key: tuple[str, int], /
) -> SimpleNamespace | None:
    del context
    profile, leader_id = key
    rows = _query(
        profile,
        "SELECT * FROM unit_leader_skill_extra_m WHERE unit_leader_skill_id=:id LIMIT 1",
        {"id": int(leader_id)},
    )
    return _namespace(rows[0] if rows else None)


async def extra_leader_by_id(
    context: idol.BasicSchoolIdolContext, leader_id: int
) -> SimpleNamespace | None:
    return await _extra_leader_by_key(context, (context.profile.value, int(leader_id)))


@common.context_cacheable("profile_unit_master_type_tag")
async def _type_has_tag_key(
    context: idol.BasicSchoolIdolContext, key: tuple[str, int, int], /
) -> bool:
    del context
    profile, unit_type_id, member_tag_id = key
    return bool(
        _query(
            profile,
            "SELECT 1 FROM unit_type_member_tag_m "
            "WHERE unit_type_id=:unit_type_id AND member_tag_id=:member_tag_id LIMIT 1",
            {"unit_type_id": int(unit_type_id), "member_tag_id": int(member_tag_id)},
        )
    )


async def unit_type_has_tag(
    context: idol.BasicSchoolIdolContext, unit_type_id: int, member_tag_id: int
) -> bool:
    return await _type_has_tag_key(
        context, (context.profile.value, int(unit_type_id), int(member_tag_id))
    )


@common.context_cacheable("profile_unit_master_all_units")
async def _all_units_by_profile(
    context: idol.BasicSchoolIdolContext, profile: str, /
) -> tuple[SimpleNamespace, ...]:
    del context
    return tuple(
        _namespaces(
            _query(
                profile,
                "SELECT unit_id, rarity, rank_max, unit_level_up_pattern_id, "
                "default_unit_skill_id, max_removable_skill_capacity, disable_rank_up "
                "FROM unit_m ORDER BY unit_id",
            )
        )
    )


async def unit_rows(context: idol.BasicSchoolIdolContext) -> list[SimpleNamespace]:
    return list(await _all_units_by_profile(context, context.profile.value))



@common.context_cacheable("profile_unit_master_sign_exists")
async def _sign_exists_key(
    context: idol.BasicSchoolIdolContext, key: tuple[str, int], /
) -> bool:
    del context
    profile, unit_id = key
    return bool(
        _query(profile, "SELECT 1 FROM unit_sign_asset_m WHERE unit_id=:id LIMIT 1", {"id": int(unit_id)})
    )


async def sign_exists(context: idol.BasicSchoolIdolContext, unit_id: int) -> bool:
    return await _sign_exists_key(context, (context.profile.value, int(unit_id)))

def raw_rows(
    profile: client_profile.ClientProfile | str,
    sql: str,
    params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Small validator/build helper; runtime callers should use cached typed functions."""
    return _query(profile, sql, params)


def counts(profile: client_profile.ClientProfile | str) -> dict[str, int]:
    normalized = _normalize_profile(profile)
    return {
        table: int(_query(normalized, f"SELECT COUNT(*) AS amount FROM {table}")[0]["amount"])
        for table in (
            "unit_m",
            "unit_rarity_m",
            "unit_level_up_pattern_m",
            "unit_level_limit_pattern_m",
            "unit_skill_m",
            "unit_leader_skill_m",
        )
    }
