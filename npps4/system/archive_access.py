"""Versioned, opt-in archive access for preserved SIF1 content.

This module deliberately separates *access/catalog state* from inventory and
completion state:

* main/side stories are made visible but stay uncompleted;
* Live tracks receive ordinary ``NormalLiveUnlock`` rows;
* card catalog access creates ``Album`` rows only and does not grant thousands
  of physical card inventory objects;
``archive`` means that no route was found in the preserved upstream NPPS4
source plus its bundled server_data.json.  It is not a claim about every route
which may once have existed on KLab's live-service backend.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field

import sqlalchemy

from .. import idol
from .. import util
from ..config import config
from ..db import main
from ..db import live as live_db
from ..db import scenario as scenario_db
from ..db import subscenario as subscenario_db
from ..db import unit as unit_db


@dataclass(kw_only=True)
class ArchiveAccessComponentResult:
    component: str
    policy: str
    requested: int = 0
    valid: int = 0
    inserted: int = 0
    updated: int = 0
    applied: bool = False


@dataclass(kw_only=True)
class ArchiveAccessSyncResult:
    components: list[ArchiveAccessComponentResult] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return any(c.inserted or c.updated for c in self.components)


def _absolute(path: str) -> str:
    if not path:
        return ""
    if os.path.isabs(path):
        return os.path.abspath(path)
    return os.path.abspath(os.path.join(config.ROOT_DIR, path))


def _manifest_path() -> str:
    configured = str(config.CONFIG_DATA.download.cn_archive.archive_access_manifest or "").strip()
    if configured:
        return _absolute(configured)
    return ""


def _load_manifest() -> tuple[dict | None, str]:
    path = _manifest_path()
    if not path or not os.path.isfile(path):
        return None, ""
    try:
        raw = open(path, "rb").read()
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            raise TypeError("manifest root is not an object")
        return value, hashlib.sha256(raw).hexdigest()[:16]
    except Exception as exc:
        util.log(
            "CN archive access",
            f"Cannot read manifest {path}: {type(exc).__name__}: {exc}",
            severity=util.logging.WARNING,
        )
        return None, ""


def _policy(value: str, component: str) -> str:
    policy = str(value or "normal").strip().lower()
    allowed = {"normal", "archive", "all"}
    if component == "album":
        allowed.add("complete")
    if policy not in allowed:
        util.log(
            "CN archive access",
            f"Unknown {component} policy {policy!r}; using normal",
            severity=util.logging.WARNING,
        )
        return "normal"
    return policy


def _int_set(values) -> set[int]:
    result: set[int] = set()
    if not isinstance(values, list):
        return result
    for value in values:
        try:
            result.add(int(value))
        except (TypeError, ValueError):
            pass
    return result


def _ids_for(manifest: dict, component: str, policy: str) -> set[int]:
    section = manifest.get(component)
    if not isinstance(section, dict):
        return set()
    if policy == "archive":
        key = "statically_unobtainable_unit_ids" if component == "album" else "statically_unreachable_ids"
    elif policy in {"all", "complete"}:
        key = "all_unit_ids" if component == "album" else "all_ids"
    else:
        return set()
    return _int_set(section.get(key))


async def _already_applied(
    context: idol.BasicSchoolIdolContext,
    user: main.User,
    component: str,
    policy: str,
    digest: str,
) -> bool:
    key = f"cn_archive_access:{component}:{policy}:{digest or 'unknown'}"
    q = sqlalchemy.select(main.ContentAccessGrant).where(
        main.ContentAccessGrant.user_id == user.id,
        main.ContentAccessGrant.grant_key == key,
    )
    return (await context.db.main.execute(q)).scalar() is not None


async def _mark_applied(
    context: idol.BasicSchoolIdolContext,
    user: main.User,
    component: str,
    policy: str,
    digest: str,
) -> None:
    context.db.main.add(
        main.ContentAccessGrant(
            user_id=user.id,
            grant_key=f"cn_archive_access:{component}:{policy}:{digest or 'unknown'}",
            grant_version=1,
        )
    )


async def _sync_main_scenario(context, user, requested: set[int], policy: str, digest: str):
    result = ArchiveAccessComponentResult(component="main_scenario", policy=policy, requested=len(requested))
    if not requested or await _already_applied(context, user, result.component, policy, digest):
        return result
    valid = set((await context.db.scenario.execute(
        sqlalchemy.select(scenario_db.Scenario.scenario_id).where(scenario_db.Scenario.scenario_id.in_(requested))
    )).scalars())
    result.valid = len(valid)
    existing = set((await context.db.main.execute(
        sqlalchemy.select(main.Scenario.scenario_id).where(main.Scenario.user_id == user.id, main.Scenario.scenario_id.in_(valid))
    )).scalars())
    for item_id in sorted(valid - existing):
        # Visible/readable, but not silently completed. Reading still exercises
        # NPPS4's ordinary scenario reward and achievement path.
        context.db.main.add(main.Scenario(user_id=user.id, scenario_id=item_id, completed=False))
        result.inserted += 1
    await _mark_applied(context, user, result.component, policy, digest)
    await context.db.main.flush()
    result.applied = True
    return result


async def _sync_side_story(context, user, requested: set[int], policy: str, digest: str):
    result = ArchiveAccessComponentResult(component="side_story", policy=policy, requested=len(requested))
    if not requested or await _already_applied(context, user, result.component, policy, digest):
        return result
    valid = set((await context.db.subscenario.execute(
        sqlalchemy.select(subscenario_db.SubScenario.subscenario_id).where(
            subscenario_db.SubScenario.subscenario_id.in_(requested)
        )
    )).scalars())
    result.valid = len(valid)
    existing = set((await context.db.main.execute(
        sqlalchemy.select(main.SubScenario.subscenario_id).where(
            main.SubScenario.user_id == user.id, main.SubScenario.subscenario_id.in_(valid)
        )
    )).scalars())
    for item_id in sorted(valid - existing):
        context.db.main.add(main.SubScenario(user_id=user.id, subscenario_id=item_id, completed=False))
        result.inserted += 1
    await _mark_applied(context, user, result.component, policy, digest)
    await context.db.main.flush()
    result.applied = True
    return result


async def _sync_live(context, user, requested: set[int], policy: str, digest: str):
    result = ArchiveAccessComponentResult(component="live", policy=policy, requested=len(requested))
    if not requested or await _already_applied(context, user, result.component, policy, digest):
        return result
    valid = set((await context.db.live.execute(
        sqlalchemy.select(live_db.LiveTrack.live_track_id).where(live_db.LiveTrack.live_track_id.in_(requested))
    )).scalars())
    result.valid = len(valid)
    existing = set((await context.db.main.execute(
        sqlalchemy.select(main.NormalLiveUnlock.live_track_id).where(
            main.NormalLiveUnlock.user_id == user.id, main.NormalLiveUnlock.live_track_id.in_(valid)
        )
    )).scalars())
    for item_id in sorted(valid - existing):
        context.db.main.add(main.NormalLiveUnlock(user_id=user.id, live_track_id=item_id))
        result.inserted += 1
    await _mark_applied(context, user, result.component, policy, digest)
    await context.db.main.flush()
    result.applied = True
    return result


async def _sync_album(context, user, requested: set[int], policy: str, digest: str):
    result = ArchiveAccessComponentResult(component="album", policy=policy, requested=len(requested))
    if not requested or await _already_applied(context, user, result.component, policy, digest):
        return result
    valid = set((await context.db.unit.execute(
        sqlalchemy.select(unit_db.Unit.unit_id).where(unit_db.Unit.unit_id.in_(requested))
    )).scalars())
    result.valid = len(valid)
    existing_rows = list((await context.db.main.execute(
        sqlalchemy.select(main.Album).where(main.Album.user_id == user.id, main.Album.unit_id.in_(valid))
    )).scalars())
    existing = {row.unit_id: row for row in existing_rows}
    complete = policy == "complete"
    for item_id in sorted(valid):
        row = existing.get(item_id)
        if row is None:
            row = main.Album(
                user_id=user.id,
                unit_id=item_id,
                rank_max_flag=complete,
                love_max_flag=complete,
                rank_level_max_flag=complete,
                highest_love_per_unit=0,
                favorite_point=0,
                sign_flag=False,
            )
            context.db.main.add(row)
            result.inserted += 1
        elif complete:
            before = (row.rank_max_flag, row.love_max_flag, row.rank_level_max_flag)
            row.rank_max_flag = True
            row.love_max_flag = True
            row.rank_level_max_flag = True
            if before != (True, True, True):
                result.updated += 1
    await _mark_applied(context, user, result.component, policy, digest)
    await context.db.main.flush()
    result.applied = True
    return result


async def sync_once(context: idol.BasicSchoolIdolContext, user: main.User) -> ArchiveAccessSyncResult:
    """Apply configured access policies once after tutorial completion."""
    result = ArchiveAccessSyncResult()
    if not config.is_cn_compat() or user.tutorial_state != -1:
        return result
    manifest, digest = _load_manifest()
    if manifest is None:
        return result

    cfg = config.CONFIG_DATA.download.cn_archive
    policies = {
        "main_scenario": _policy(cfg.main_scenario_unlock_policy, "main_scenario"),
        "side_story": _policy(cfg.subscenario_unlock_policy, "side_story"),
        "live": _policy(cfg.live_unlock_policy, "live"),
        "album": _policy(cfg.album_catalog_unlock_policy, "album"),
    }
    for component, policy in policies.items():
        if policy == "normal":
            continue
        ids = _ids_for(manifest, component, policy)
        if component == "main_scenario":
            item = await _sync_main_scenario(context, user, ids, policy, digest)
        elif component == "side_story":
            item = await _sync_side_story(context, user, ids, policy, digest)
        elif component == "live":
            item = await _sync_live(context, user, ids, policy, digest)
        else:
            item = await _sync_album(context, user, ids, policy, digest)
        result.components.append(item)
        if item.applied:
            util.log(
                "CN archive access sync",
                f"user_id={user.id}",
                f"component={item.component}",
                f"policy={item.policy}",
                f"requested={item.requested}",
                f"valid={item.valid}",
                f"inserted={item.inserted}",
                f"updated={item.updated}",
                severity=util.logging.WARNING,
            )
    return result
