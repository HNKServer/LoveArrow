"""One-time CN account repair using NPPS4's real content systems.

The final CN client contains release achievements which were used by the live
service to make time-limited songs and stories available.  Earlier CN master
conversion copied only six achievement columns, so those achievements were
never opened or completed.  v4.41 overlays the exact client master and this
module synchronizes existing accounts once, then lets NPPS4's own achievement
checker and reward processor perform the unlocks.

Normal progression is deliberately preserved: main-story chains, rank gates,
bond stories, and live-clear achievements are not force-completed.  The only
date override is for achievement_type=29 release/login achievements whose
rewards are valid songs or main stories in the CN 9.7.1 master.  Event and
multi-unit stories have no surviving event scheduler in NPPS4, so their actual
per-user rows are granted as completed/replayable content.
"""

from __future__ import annotations

import dataclasses

import sqlalchemy

from .. import const
from .. import data
from .. import idol
from .. import util
from ..config import config
from ..db import achievement as achievement_db
from ..db import live as live_db
from ..db import main
from ..db import scenario as scenario_db
from . import achievement
from . import cn_content_master
from . import eventscenario
from . import multiunit

GRANT_KEY = "cn_post_service_content"
GRANT_VERSION = 1


@dataclasses.dataclass(kw_only=True)
class PostServiceSyncResult:
    added_active_achievements: int = 0
    added_release_achievements: int = 0
    event_scenarios_granted: int = 0
    multi_unit_scenarios_granted: int = 0
    applied: bool = False


async def _get_grant(context: idol.BasicSchoolIdolContext, user: main.User):
    q = sqlalchemy.select(main.ContentAccessGrant).where(
        main.ContentAccessGrant.user_id == user.id,
        main.ContentAccessGrant.grant_key == GRANT_KEY,
    )
    return (await context.db.main.execute(q)).scalar()


async def _valid_release_achievement_ids(context: idol.BasicSchoolIdolContext) -> set[int]:
    """Return type-29 achievement IDs that unlock content present in CN master."""

    live_ids = set((await context.db.live.execute(sqlalchemy.select(live_db.LiveTrack.live_track_id))).scalars())
    scenario_ids = set(
        (await context.db.scenario.execute(sqlalchemy.select(scenario_db.Scenario.scenario_id))).scalars()
    )
    server_data = data.get()

    q = sqlalchemy.select(achievement_db.Achievement.achievement_id).where(
        achievement_db.Achievement.achievement_type == 29,
        achievement_db.Achievement.default_open_flag == 1,
    )
    candidate_ids = set((await context.db.achievement.execute(q)).scalars())
    result: set[int] = set()

    for achievement_id in candidate_ids:
        rewards = server_data.achievement_reward.get(achievement_id, [])
        content_rewards = [
            item for item in rewards if item.add_type in (const.ADD_TYPE.LIVE, const.ADD_TYPE.SCENARIO)
        ]
        if not content_rewards:
            continue
        # Never enqueue a release achievement containing a content ID absent
        # from this exact CN client master; that would create an unusable reward
        # or a present-box entry which can never be claimed.
        if all(
            (item.add_type == const.ADD_TYPE.LIVE and item.item_id in live_ids)
            or (item.add_type == const.ADD_TYPE.SCENARIO and item.item_id in scenario_ids)
            for item in content_rewards
        ):
            result.add(int(achievement_id))
    return result


async def _add_missing_achievement(
    context: idol.BasicSchoolIdolContext,
    user: main.User,
    info: achievement_db.Achievement,
    *,
    now: int,
) -> bool:
    if await achievement.has_achievement(context, user, info.achievement_id):
        return False
    row = await achievement.add_achievement(context, user, info, now, flush=False)
    if info.end_date is not None:
        row.end_date = util.datetime_to_timestamp(info.end_date)
    return True


async def _sync_achievement_rows(
    context: idol.BasicSchoolIdolContext,
    user: main.User,
    *,
    now: int,
) -> tuple[int, int]:
    """Restore active defaults plus post-service release achievements."""

    release_ids = await _valid_release_achievement_ids(context)
    q = sqlalchemy.select(achievement_db.Achievement).where(
        sqlalchemy.or_(
            achievement_db.Achievement.default_open_flag == 1,
            achievement_db.Achievement.achievement_id.in_(release_ids),
        )
    )
    rows = list((await context.db.achievement.execute(q)).scalars())
    active_added = 0
    release_added = 0

    for info in rows:
        start = util.datetime_to_timestamp(info.start_date)
        end = util.datetime_to_timestamp(info.end_date) if info.end_date is not None else 0
        active_now = now >= start and (end == 0 or now < end)
        release_override = info.achievement_id in release_ids
        if not active_now and not release_override:
            continue
        if await _add_missing_achievement(context, user, info, now=now):
            if release_override and not active_now:
                release_added += 1
            else:
                active_added += 1

    await context.db.main.flush()
    return active_added, release_added


async def sync_once(
    context: idol.BasicSchoolIdolContext,
    user: main.User,
    *,
    login_days: int,
) -> PostServiceSyncResult:
    """Apply v4.41's idempotent post-service content migration.

    The returned achievement context must be merged into the normal login-bonus
    response and processed by the ordinary achievement reward pipeline.
    """

    # Kept in the call contract because this migration is triggered from the
    # login-bonus path.  The actual login-day comparison remains exclusively in
    # NPPS4's ordinary AchievementUpdateLoginBonus checker below.
    _ = login_days

    result = PostServiceSyncResult()
    if not config.is_cn_compat() or user.tutorial_state != -1:
        return result

    grant = await _get_grant(context, user)
    if grant is not None and grant.grant_version >= GRANT_VERSION:
        return result

    now = util.time()
    active_added, release_added = await _sync_achievement_rows(context, user, now=now)
    result.added_active_achievements = active_added
    result.added_release_achievements = release_added

    # The caller runs NPPS4's normal login checker exactly once after this
    # synchronization.  Keeping the trigger in lbonus/execute avoids counting a
    # real daily login twice when the migration and today's reward happen in the
    # same request.

    # The event scheduler and event-point progression no longer exist.  Store
    # real completed rows so all archived chapters are visible and replayable,
    # without pretending the user has an active event or handing out historical
    # ranking rewards.
    for info in cn_content_master.event_scenarios():
        if await eventscenario.unlock(
            context, user, info.event_scenario_id, is_new=False, completed=True, flush=False
        ):
            result.event_scenarios_granted += 1

    for info in cn_content_master.multi_unit_scenarios():
        if await multiunit.unlock(
            context, user, info.multi_unit_scenario_id, is_new=False, completed=True, flush=False
        ):
            result.multi_unit_scenarios_granted += 1

    if grant is None:
        grant = main.ContentAccessGrant(
            user_id=user.id,
            grant_key=GRANT_KEY,
            grant_version=GRANT_VERSION,
        )
        context.db.main.add(grant)
    else:
        grant.grant_version = GRANT_VERSION
        grant.update_date = now

    await context.db.main.flush()
    result.applied = True
    util.log(
        "CN post-service content sync",
        f"user_id={user.id}",
        f"active_achievements={active_added}",
        f"release_achievements={release_added}",
        f"event_scenarios={result.event_scenarios_granted}",
        f"multi_unit_scenarios={result.multi_unit_scenarios_granted}",
        severity=util.logging.WARNING,
    )
    return result
