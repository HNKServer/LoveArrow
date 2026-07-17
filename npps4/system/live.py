import binascii
import collections.abc
import gzip
import hashlib
import json

import sqlalchemy
import pydantic

from . import common
from . import item
from . import live_model
from .. import const
from .. import db
from .. import idol
from .. import util
from ..config import config
from ..db import main
from ..db import live

from typing import Any, Literal, cast, overload


async def unlock_normal_live(context: idol.BasicSchoolIdolContext, user: main.User, live_track_id: int):
    q = sqlalchemy.select(main.NormalLiveUnlock).where(
        main.NormalLiveUnlock.user_id == user.id, main.NormalLiveUnlock.live_track_id == live_track_id
    )
    result = await context.db.main.execute(q)
    if result.scalar() is None:
        context.db.main.add(main.NormalLiveUnlock(user_id=user.id, live_track_id=live_track_id))
        await context.db.main.flush()
        return True
    return False


async def init(context: idol.BasicSchoolIdolContext, user: main.User):
    await unlock_normal_live(context, user, 1)  # Bokura no LIVE Kimi to no LIFE

    # Unlock the rest of the live shows.
    unlocked: set[int] = set()
    q = sqlalchemy.select(live.NormalLive).where(live.NormalLive.default_unlocked_flag == 1)
    result = await context.db.live.execute(q)

    for normallive in result.scalars():
        setting_data = await context.db.live.get(live.LiveSetting, normallive.live_setting_id)
        assert setting_data is not None
        if setting_data.live_track_id not in unlocked:
            if await unlock_normal_live(context, user, setting_data.live_track_id):
                unlocked.add(setting_data.live_track_id)

    await context.db.main.flush()


@overload
async def get_live_clear_data(
    context: idol.BasicSchoolIdolContext, /, user: main.User, live_difficulty_id: int, ensure: Literal[False] = False
) -> main.LiveClear | None: ...
@overload
async def get_live_clear_data(
    context: idol.BasicSchoolIdolContext, /, user: main.User, live_difficulty_id: int, ensure: Literal[True]
) -> main.LiveClear: ...


async def get_live_clear_data(
    context: idol.BasicSchoolIdolContext, /, user: main.User, live_difficulty_id: int, ensure: bool = False
):
    q = sqlalchemy.select(main.LiveClear).where(
        main.LiveClear.user_id == user.id, main.LiveClear.live_difficulty_id == live_difficulty_id
    )
    result = await context.db.main.execute(q)
    live_clear = result.scalar()

    if ensure and live_clear is None:
        live_setting_info = await get_live_setting_from_difficulty_id(context, live_difficulty_id)
        if live_setting_info is None:
            raise ValueError("invalid live_difficulty_id")

        live_clear = main.LiveClear(
            user_id=user.id, live_difficulty_id=live_difficulty_id, difficulty=live_setting_info.difficulty
        )
        context.db.main.add(live_clear)
        await context.db.main.flush()

    return live_clear


async def get_all_live_clear_data(
    context: idol.BasicSchoolIdolContext, user: main.User, /
) -> collections.abc.Iterable[main.LiveClear]:
    q = sqlalchemy.select(main.LiveClear).where(main.LiveClear.user_id == user.id)
    result = await context.db.main.execute(q)
    return result.scalars()


async def live_status_from_live_clear(
    context: idol.BasicSchoolIdolContext,
    live_difficulty_id: int,
    /,
    live_clear: main.LiveClear | None,
    *,
    missing_status: int = 1,
):
    if live_clear is None:
        return live_model.LiveStatus(
            live_difficulty_id=live_difficulty_id,
            status=missing_status,
            hi_score=0,
            hi_combo_count=0,
            clear_cnt=0,
            achieved_goal_id_list=[],
        )
    else:
        return live_model.LiveStatus(
            live_difficulty_id=live_difficulty_id,
            status=1 + (live_clear.clear_cnt > 0),
            hi_score=live_clear.hi_score,
            hi_combo_count=live_clear.hi_combo_cnt,
            clear_cnt=live_clear.clear_cnt,
            achieved_goal_id_list=await get_achieved_goal_id_list(context, live_clear),
        )


async def get_normal_live_clear_status(context: idol.BasicSchoolIdolContext, user: main.User):
    q = sqlalchemy.select(main.NormalLiveUnlock.live_track_id).where(main.NormalLiveUnlock.user_id == user.id)
    result = await context.db.main.execute(q)
    live_status_result: list[live_model.LiveStatus] = []

    for live_track_id in result.scalars():
        live_setting_ids = await get_live_setting_ids_from_track_id(context, live_track_id)

        q = sqlalchemy.select(live.NormalLive.live_difficulty_id).where(
            live.NormalLive.live_setting_id.in_(live_setting_ids)
        )
        result = await context.db.live.execute(q)

        for live_difficulty_id in result.scalars():
            q = sqlalchemy.select(main.LiveClear).where(
                main.LiveClear.user_id == user.id, main.LiveClear.live_difficulty_id == live_difficulty_id
            )
            result = await context.db.main.execute(q)
            live_status_result.append(await live_status_from_live_clear(context, live_difficulty_id, result.scalar()))

    return live_status_result


async def get_normal_live_clear_status_of_track(
    context: idol.BasicSchoolIdolContext, user: main.User, live_track_id: int
):
    live_status_result: list[live_model.LiveStatus] = []
    live_setting_ids = await get_live_setting_ids_from_track_id(context, live_track_id)

    q = sqlalchemy.select(live.NormalLive.live_difficulty_id).where(
        live.NormalLive.live_setting_id.in_(live_setting_ids)
    )
    result = await context.db.live.execute(q)
    live_difficulty_ids = list(result.scalars())

    for live_difficulty_id in live_difficulty_ids:
        live_clear = await get_live_clear_data(context, user, live_difficulty_id)
        live_status_result.append(await live_status_from_live_clear(context, live_difficulty_id, live_clear))

    return live_status_result


@common.context_cacheable("live_info")
async def get_live_info_table(context: idol.BasicSchoolIdolContext, live_difficulty_id: int, /):
    live_info = await context.db.live.get(live.SpecialLive, live_difficulty_id)
    if live_info is None:
        live_info = await context.db.live.get(live.NormalLive, live_difficulty_id)
    return live_info


@common.context_cacheable("live_setting")
async def get_live_setting(context: idol.BasicSchoolIdolContext, live_setting_id: int, /):
    return await db.get_decrypted_row(context.db.live, live.LiveSetting, live_setting_id)


@common.context_cacheable("live_capital_value")
async def get_live_lp(context: idol.BasicSchoolIdolContext, live_difficulty_id: int, /):
    live_info = await get_live_info_table(context, live_difficulty_id)
    if live_info is None:
        return None

    return live_info.capital_value


@common.context_cacheable("live_setting_from_difficulty")
async def get_live_setting_from_difficulty_id(context: idol.BasicSchoolIdolContext, live_difficulty_id: int, /):
    live_info = await get_live_info_table(context, live_difficulty_id)
    if live_info is None:
        return None

    return await get_live_setting(context, live_info.live_setting_id)


async def get_live_info(context: idol.BasicSchoolIdolContext, live_difficulty_id: int, live_setting: live.LiveSetting):
    beatmap_protocol = config.get_beatmap_provider_protocol()
    beatmap_data = await beatmap_protocol.get_beatmap_data(live_setting.notes_setting_asset, context)
    if beatmap_data is None:
        return None

    # TODO: Randomize
    return live_model.LiveInfoWithNotes(
        live_difficulty_id=live_difficulty_id,
        ac_flag=live_setting.ac_flag,
        swing_flag=live_setting.swing_flag,
        notes_list=[
            live_model.LiveNote(
                timing_sec=l.timing_sec,
                notes_attribute=l.notes_attribute,
                notes_level=l.notes_level,
                effect=l.effect,
                effect_value=l.effect_value,
                position=l.position,
                speed=l.speed,
                vanish=l.vanish,
            )
            for l in beatmap_data
        ],
    )


async def get_live_info_without_notes(
    context: idol.BasicSchoolIdolContext, live_difficulty_id: int, live_setting: live.LiveSetting
):
    return live_model.LiveInfo(
        live_difficulty_id=live_difficulty_id,
        ac_flag=live_setting.ac_flag,
        swing_flag=live_setting.swing_flag,
    )


@common.context_cacheable("live_goal_reward")
async def get_goal_list_by_live_difficulty_id(context: idol.BasicSchoolIdolContext, live_difficulty_id: int, /):
    q = sqlalchemy.select(live.LiveGoalReward).where(live.LiveGoalReward.live_difficulty_id == live_difficulty_id)
    result = await context.db.live.execute(q)
    return list(result.scalars())


MAX_INT = 2147483647


def make_rank_range(live_info: live.CommonLive, live_setting: live.LiveSetting):
    return {
        # Note: The ranges are in reverse order
        const.LIVE_GOAL_TYPE.SCORE: [
            range(live_setting.s_rank_score, MAX_INT),
            range(live_setting.a_rank_score, live_setting.s_rank_score),
            range(live_setting.b_rank_score, live_setting.a_rank_score),
            range(live_setting.c_rank_score, live_setting.b_rank_score),
        ],
        const.LIVE_GOAL_TYPE.COMBO: [
            range(live_setting.s_rank_combo, MAX_INT),
            range(live_setting.a_rank_combo, live_setting.s_rank_combo),
            range(live_setting.b_rank_combo, live_setting.a_rank_combo),
            range(live_setting.c_rank_combo, live_setting.b_rank_combo),
        ],
        const.LIVE_GOAL_TYPE.CLEAR: [
            range(live_info.s_rank_complete, MAX_INT),
            range(live_info.a_rank_complete, live_info.s_rank_complete),
            range(live_info.b_rank_complete, live_info.a_rank_complete),
            range(live_info.c_rank_complete, live_info.b_rank_complete),
        ],
    }


def get_index_of_range(
    value: int, seq: collections.abc.Iterable[collections.abc.Sequence[int]], start: int = 0, default: int = -1
):
    for i, r in enumerate(seq, start):
        if value in r:
            return i

    return default


LIVE_GOAL_TYPES = (const.LIVE_GOAL_TYPE.SCORE, const.LIVE_GOAL_TYPE.COMBO, const.LIVE_GOAL_TYPE.CLEAR)


def get_live_ranks(live_info: live.CommonLive, live_setting: live.LiveSetting, score: int, combo: int, clears: int):
    rank_ranges = make_rank_range(live_info, live_setting)
    score_rank = get_index_of_range(score, rank_ranges[const.LIVE_GOAL_TYPE.SCORE], 1, 5)
    combo_rank = get_index_of_range(combo, rank_ranges[const.LIVE_GOAL_TYPE.COMBO], 1, 5)
    clear_rank = get_index_of_range(clears, rank_ranges[const.LIVE_GOAL_TYPE.CLEAR], 1, 5)
    return score_rank, combo_rank, clear_rank


async def get_achieved_goal_id_list(context: idol.BasicSchoolIdolContext, clear_info: main.LiveClear):
    live_info = await get_live_info_table(context, clear_info.live_difficulty_id)
    result: list[int] = []
    if live_info is not None:
        live_setting = await get_live_setting(context, live_info.live_setting_id)
        if live_setting is not None:
            # Sort out the goal rewards
            goal_list = await get_goal_list_by_live_difficulty_id(context, clear_info.live_difficulty_id)
            goal_list_by_type = dict(
                (
                    i,
                    sorted(
                        filter(lambda g: g.live_goal_type == i, goal_list),
                        key=lambda g: g.rank,
                    ),
                )
                for i in const.LIVE_GOAL_TYPE
            )
            score_rank, combo_rank, clear_rank = get_live_ranks(
                live_info, live_setting, clear_info.hi_score, clear_info.hi_combo_cnt, clear_info.clear_cnt
            )
            result.extend(
                g.live_goal_reward_id for g in goal_list_by_type[const.LIVE_GOAL_TYPE.SCORE] if score_rank <= g.rank
            )
            result.extend(
                g.live_goal_reward_id for g in goal_list_by_type[const.LIVE_GOAL_TYPE.COMBO] if combo_rank <= g.rank
            )
            result.extend(
                g.live_goal_reward_id for g in goal_list_by_type[const.LIVE_GOAL_TYPE.CLEAR] if clear_rank <= g.rank
            )

    return result


async def get_goal_rewards(context: idol.BasicSchoolIdolContext, goal_ids: list[int]):
    q = sqlalchemy.select(live.LiveGoalReward).where(live.LiveGoalReward.live_goal_reward_id.in_(goal_ids))
    result = await context.db.live.execute(q)
    return [
        item.item_model.Item(
            add_type=const.ADD_TYPE(k.add_type),
            item_id=k.item_id,
            amount=k.amount,
            item_category_id=k.item_category_id or 0,
            reward_box_flag=False,
        )
        for k in result.scalars()
    ]


@common.context_cacheable("live_setting_ids_from_track")
async def get_live_setting_ids_from_track_id(context: idol.BasicSchoolIdolContext, live_track_id: int, /):
    q = sqlalchemy.select(live.LiveSetting.live_setting_id).where(live.LiveSetting.live_track_id == live_track_id)
    result = await context.db.live.execute(q)
    return list(result.scalars())


async def has_normal_live_unlock(context: idol.BasicSchoolIdolContext, user: main.User, live_track_id: int):
    q = sqlalchemy.select(main.NormalLiveUnlock).where(
        main.NormalLiveUnlock.user_id == user.id, main.NormalLiveUnlock.live_track_id == live_track_id
    )
    result = await context.db.main.execute(q)
    return result.scalar() is not None


async def get_all_normal_live_unlock(
    context: idol.BasicSchoolIdolContext, user: main.User, /
) -> collections.abc.Iterable[int]:
    q = sqlalchemy.select(main.NormalLiveUnlock.live_track_id).where(main.NormalLiveUnlock.user_id == user.id)
    result = await context.db.main.execute(q)
    return result.scalars()


async def get_live_in_progress(context: idol.BasicSchoolIdolContext, user: main.User):
    q = sqlalchemy.select(main.LiveInProgress).where(main.LiveInProgress.user_id == user.id)
    result = await context.db.main.execute(q)
    return result.scalar()


async def clean_live_in_progress(context: idol.BasicSchoolIdolContext, user: main.User):
    q = sqlalchemy.delete(main.LiveInProgress).where(main.LiveInProgress.user_id == user.id)
    result = cast(sqlalchemy.CursorResult, await context.db.main.execute(q))
    return result.rowcount > 0


async def register_live_in_progress(
    context: idol.BasicSchoolIdolContext,
    user: main.User,
    party_user: main.User,
    lp_factor: int,
    unit_deck_id: int,
    deck_data_bytes: bytes,
):
    live_in_progress = await get_live_in_progress(context, user)
    if live_in_progress is None:
        wip = main.LiveInProgress(
            user_id=user.id,
            party_user_id=party_user.id,
            lp_factor=lp_factor,
            unit_deck_id=unit_deck_id,
            deck_data=deck_data_bytes,
        )
        context.db.main.add(wip)
    else:
        live_in_progress.party_user_id = party_user.id
        live_in_progress.lp_factor = lp_factor
        live_in_progress.unit_deck_id = unit_deck_id
        live_in_progress.deck_data = deck_data_bytes
    await context.db.main.flush()


async def get_live_track_info(context: idol.BasicSchoolIdolContext, live_track_id: int, /):
    live_track = await db.get_decrypted_row(context.db.live, live.LiveTrack, live_track_id)
    if live_track is None:
        raise ValueError(f"track info of live_track_id {live_track_id} not found")

    return live_track


def _special_live_rotation_timezone():
    """Timezone for date-bound live rotations.

    This intentionally performs a timezone conversion rather than adding a fixed
    number of hours to the current local clock.  With the default CN setting it
    asks: "what date is it right now in Asia/Shanghai?".  It will not double
    add eight hours when the host OS is already set to China/Hong Kong time.
    "system"/"local" is allowed for deployments that intentionally want the
    host timezone to define the game day.
    """

    import datetime as _datetime

    name = config.get_daily_rotation_timezone_name()
    if name == "local":
        return _datetime.datetime.now().astimezone().tzinfo or _datetime.timezone.utc

    try:
        import zoneinfo

        return zoneinfo.ZoneInfo(name)
    except Exception:
        # Keep the server usable on minimal Python builds without tzdata.  The
        # configured defaults do not use DST, so fixed offsets are safe here.
        if name in {"Asia/Shanghai", "Asia/Hong_Kong", "Asia/Singapore", "Etc/GMT-8"}:
            return _datetime.timezone(_datetime.timedelta(hours=8), name)
        if name in {"Asia/Tokyo", "Etc/GMT-9"}:
            return _datetime.timezone(_datetime.timedelta(hours=9), name)
        raise


def _special_live_rotation_local_datetime(ts: int | None = None):
    import datetime as _datetime

    tz = _special_live_rotation_timezone()
    if ts is None:
        ts = util.time()
    return _datetime.datetime.fromtimestamp(ts, _datetime.timezone.utc).astimezone(tz)


def _special_live_rotation_day(ts: int | None = None) -> int:
    import datetime as _datetime

    local_date = _special_live_rotation_local_datetime(ts).date()
    return (local_date - _datetime.date(1970, 1, 1)).days


def _special_live_rotation_day_start_timestamp(day: int) -> int:
    import datetime as _datetime

    tz = _special_live_rotation_timezone()
    local_date = _datetime.date(1970, 1, 1) + _datetime.timedelta(days=day)
    local_midnight = _datetime.datetime.combine(local_date, _datetime.time.min, tzinfo=tz)
    return int(local_midnight.timestamp())


def get_special_live_rotation_sunday_based_weekday(ts: int | None = None) -> int:
    """Return Sunday=0..Saturday=6 in the configured rotation timezone."""

    now = _special_live_rotation_local_datetime(ts)
    return (now.weekday() + 1) % 7


def format_special_live_rotation_timestamp(ts: int) -> str:
    return _special_live_rotation_local_datetime(ts).strftime("%Y-%m-%d %H:%M:%S")


def _parse_rotation_base_timestamp(value: str) -> int:
    # master data in the wild may use either '-' or '/' separators.  Interpret
    # the naive master-data timestamp in the configured game rotation timezone.
    import datetime as _datetime

    value = value.strip()
    tz = _special_live_rotation_timezone()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M"):
        try:
            dt = _datetime.datetime.strptime(value, fmt)
            return int(dt.replace(tzinfo=tz).timestamp())
        except ValueError:
            continue
    # Fall back to the original helper for any unexpected legacy format; it is
    # JST-biased but better than crashing during startup.
    return util.datetime_to_timestamp(value)


async def get_special_live_rotation_time_modulo(context: idol.BasicSchoolIdolContext, /):
    q = sqlalchemy.select(live.SpecialLiveRotation).order_by(
        live.SpecialLiveRotation.rotation_group_id, live.SpecialLiveRotation.base_date
    )
    result = await context.db.live.execute(q)
    rotation_group_time: dict[int, list[tuple[int, int]]] = {}

    for row in result.scalars():
        group = rotation_group_time.setdefault(row.rotation_group_id, [])
        unix_timestamp = _parse_rotation_base_timestamp(row.base_date)
        group.append((row.live_difficulty_id, _special_live_rotation_day(unix_timestamp)))

    return rotation_group_time


async def get_special_live_rotation_difficulty_id(context: idol.BasicSchoolIdolContext, /):
    rotation_group_time = await get_special_live_rotation_time_modulo(context)
    result: dict[int, int] = {}
    current_day = _special_live_rotation_day()

    for group_id, live_list in rotation_group_time.items():
        if not live_list:
            continue
        current_day_modulo = current_day % len(live_list)

        for live_difficulty_id, day_time in live_list:
            if day_time % len(live_list) == current_day_modulo:
                result[group_id] = live_difficulty_id
                break

    return result


async def get_current_and_next_special_live_rotation_schedules(context: idol.BasicSchoolIdolContext, /):
    """Return the active and next rotation window for each special-live group.

    honoka-chan uses the same master table but exposes both the current and next
    song in live/schedule.  This is not a honoka-only shortcut: it is a faithful
    interpretation of special_live_rotation_m, so it is safe to keep as a real
    NPPS4 wrapper over existing master data.
    """

    q = sqlalchemy.select(live.SpecialLiveRotation).order_by(
        live.SpecialLiveRotation.rotation_group_id, live.SpecialLiveRotation.base_date
    )
    result = await context.db.live.execute(q)

    grouped: dict[int, list[tuple[int, int]]] = {}
    for row in result.scalars():
        base_ts = _parse_rotation_base_timestamp(row.base_date)
        grouped.setdefault(row.rotation_group_id, []).append(
            (row.live_difficulty_id, _special_live_rotation_day(base_ts))
        )

    current_day = _special_live_rotation_day()
    schedules: list[tuple[int, int, int]] = []
    for group_id in sorted(grouped):
        live_list = grouped[group_id]
        if not live_list:
            continue

        current_index = -1
        current_day_modulo = current_day % len(live_list)
        for index, (_, base_day) in enumerate(live_list):
            if base_day % len(live_list) == current_day_modulo:
                current_index = index
                break
        if current_index < 0:
            continue

        # Daily rotations have period_days=1.  Some data sets encode longer
        # periods; preserve that instead of hardcoding a one-day span.
        period_days = 1
        if len(live_list) >= 2:
            diff = live_list[1][1] - live_list[0][1]
            if diff > 0:
                period_days = diff

        current_live_id, current_base_day = live_list[current_index]
        offset_days = (current_day - current_base_day) % period_days
        current_start_day = current_day - offset_days
        current_start_ts = _special_live_rotation_day_start_timestamp(current_start_day)
        current_end_ts = _special_live_rotation_day_start_timestamp(current_start_day + period_days) - 1
        schedules.append((current_live_id, current_start_ts, current_end_ts))

        if len(live_list) > 1:
            next_live_id, _ = live_list[(current_index + 1) % len(live_list)]
            next_start_day = current_start_day + period_days
            next_start_ts = _special_live_rotation_day_start_timestamp(next_start_day)
            next_end_ts = _special_live_rotation_day_start_timestamp(next_start_day + period_days) - 1
            schedules.append((next_live_id, next_start_ts, next_end_ts))

    return schedules


async def get_special_live_status(context: idol.BasicSchoolIdolContext, /, user: main.User):
    result: list[live_model.LiveStatus] = []

    if config.is_cn_compat():
        # CN/honoka behavior exposes both current and next daily-rotation songs
        # in status.  Do this only under CN profile so the normal NPPS4 schedule
        # remains unchanged for JP/Global clients.
        live_difficulty_ids = [
            live_difficulty_id
            for live_difficulty_id, _, _ in await get_current_and_next_special_live_rotation_schedules(context)
        ]
    else:
        live_difficulty_ids = list((await get_special_live_rotation_difficulty_id(context)).values())

    for live_difficulty_id in live_difficulty_ids:
        live_clear = await get_live_clear_data(context, user, live_difficulty_id)
        result.append(await live_status_from_live_clear(context, live_difficulty_id, live_clear))

    return result


@common.context_cacheable("live_training_from_track_id")
async def get_training_live_difficulty_id_from_live_track_id(
    context: idol.BasicSchoolIdolContext, live_track_id: int, /
):
    q = sqlalchemy.select(live.LiveSetting.live_setting_id).where(
        live.LiveSetting.live_track_id == live_track_id,
        live.LiveSetting.difficulty > 5,
        live.LiveSetting.ac_flag == 0,
    )
    result = await context.db.live.execute(q)
    live_setting_ids = list(result.scalars())

    q = sqlalchemy.select(live.SpecialLive.live_difficulty_id).where(
        live.SpecialLive.live_setting_id.in_(live_setting_ids), live.SpecialLive.exclude_clear_count_flag == 0
    )
    result = await context.db.live.execute(q)
    live_difficulty_ids = set(result.scalars())

    # Make sure it's not in special_live_rotation_m
    q = sqlalchemy.select(live.SpecialLiveRotation.live_difficulty_id).where(
        live.SpecialLiveRotation.live_difficulty_id.in_(live_difficulty_ids)
    )
    result = await context.db.live.execute(q)
    return sorted(live_difficulty_ids - set(result.scalars()))


async def get_training_live_clear_status_of_track(
    context: idol.BasicSchoolIdolContext, user: main.User, live_track_id: int
):
    live_difficulty_ids = await get_training_live_difficulty_id_from_live_track_id(context, live_track_id)
    live_status_result: list[live_model.LiveStatus] = []

    for live_difficulty_id in live_difficulty_ids:
        live_clear = await get_live_clear_data(context, user, live_difficulty_id)
        live_status_result.append(await live_status_from_live_clear(context, live_difficulty_id, live_clear))

    return live_status_result


async def get_training_live_status(context: idol.BasicSchoolIdolContext, /, user: main.User):
    live_status_result: list[live_model.LiveStatus] = []

    # Get normal live unlock
    q = sqlalchemy.select(main.NormalLiveUnlock.live_track_id).where(main.NormalLiveUnlock.user_id == user.id)
    result = await context.db.main.execute(q)

    for live_track_id in result.scalars():
        live_status_result.extend(await get_training_live_clear_status_of_track(context, user, live_track_id))

    return live_status_result


class NotesListRoot(pydantic.RootModel):
    root: list[live_model.LiveNote]


async def record_notes_list(context: idol.BasicSchoolIdolContext, notes_list: list[live_model.LiveNote], /):
    notes_list_json = NotesListRoot(notes_list).model_dump_json().encode("utf-8")
    sha256 = hashlib.sha256(notes_list_json, usedforsecurity=False).digest()
    crc32 = binascii.crc32(notes_list_json)

    if config.store_backup_of_notes_list():
        q = sqlalchemy.select(main.NotesListBackup).where(
            main.NotesListBackup.crc32 == crc32, main.NotesListBackup.sha256 == sha256
        )
        result = await context.db.main.execute(q)
        backup_notes = result.scalar()

        if backup_notes is None:
            backup_notes = main.NotesListBackup(crc32=crc32, sha256=sha256, notes_list=gzip.compress(notes_list_json))
            context.db.main.add(backup_notes)
            await context.db.main.flush()

    return crc32, sha256


async def record_precise_score(
    context: idol.BasicSchoolIdolContext,
    /,
    user: main.User,
    live_difficulty_id: int,
    use_skill: bool,
    notes_list: list[live_model.LiveNote],
    precise_log_data: dict[str, Any],
):
    # use_skill = bool(precise_log_data.get("is_skill_on", True))
    q = sqlalchemy.select(main.LiveReplay).where(
        main.LiveReplay.user_id == user.id,
        main.LiveReplay.live_difficulty_id == live_difficulty_id,
        main.LiveReplay.use_skill == use_skill,
    )
    result = await context.db.main.execute(q)
    replay = result.scalar()

    if replay is None:
        replay = main.LiveReplay(
            user_id=user.id,
            live_difficulty_id=live_difficulty_id,
            use_skill=use_skill,
            timestamp=0,
            notes_crc32=0,
            notes_sha256=b"",
            precise_log=b"",
        )
        context.db.main.add(replay)

    replay.timestamp = util.time()
    replay.notes_crc32, replay.notes_sha256 = await record_notes_list(context, notes_list)
    replay.precise_log = gzip.compress(json.dumps(precise_log_data).encode("utf-8"))
    await context.db.main.flush()


async def pull_precise_score_with_beatmap(
    context: idol.BasicSchoolIdolContext, /, user: main.User, live_difficulty_id: int, use_skill: bool
):
    q = sqlalchemy.select(main.LiveReplay).where(
        main.LiveReplay.user_id == user.id,
        main.LiveReplay.live_difficulty_id == live_difficulty_id,
        main.LiveReplay.use_skill == use_skill,
    )
    result = await context.db.main.execute(q)
    replay = result.scalar()
    if replay is None:
        return None

    # Get notes cache
    q = sqlalchemy.select(main.NotesListBackup.notes_list).where(
        main.NotesListBackup.crc32 == replay.notes_crc32, main.NotesListBackup.sha256 == replay.notes_sha256
    )
    result = await context.db.main.execute(q)
    notes_list_bytes = result.scalar()
    notes_list = None
    if notes_list_bytes is not None:
        notes_list = NotesListRoot.model_validate_json(gzip.decompress(notes_list_bytes)).root

    if notes_list is None:
        # Try look at current beatmap
        live_setting = await get_live_setting_from_difficulty_id(context, live_difficulty_id)
        if live_setting is None:
            return None

        beatmap_protocol = config.get_beatmap_provider_protocol()
        beatmap_data = await beatmap_protocol.get_beatmap_data(live_setting.notes_setting_asset, context)
        if beatmap_data is None:
            return None

        notes_list_unprocessed = [
            live_model.LiveNote(
                timing_sec=l.timing_sec,
                notes_attribute=l.notes_attribute,
                notes_level=l.notes_level,
                effect=l.effect,
                effect_value=l.effect_value,
                position=l.position,
                speed=l.speed,
                vanish=l.vanish,
            )
            for l in beatmap_data
        ]
        notes_list_bytes = NotesListRoot(notes_list_unprocessed).model_dump_json().encode("utf-8")
        sha256_of_notes = hashlib.sha256(notes_list_bytes, usedforsecurity=False).digest()

        if replay.notes_sha256 == sha256_of_notes:
            notes_list = notes_list_unprocessed

    if notes_list is None:
        return None

    return json.loads(gzip.decompress(replay.precise_log)), notes_list, replay.timestamp


async def get_cleared_live_count(context: idol.BasicSchoolIdolContext, /, user: main.User) -> dict[int, int]:
    q = sqlalchemy.select(main.LiveClear.difficulty, sqlalchemy.func.count(main.LiveClear.live_difficulty_id)).group_by(
        main.LiveClear.difficulty
    )
    result = await context.db.main.execute(q)
    return {r[0]: r[1] for r in result}


@common.context_cacheable("adjacent_live_difficulty_id")
async def get_enh_live_difficulty_ids(context: idol.BasicSchoolIdolContext, /, live_difficulty_id: int):
    output: dict[int, int] = {}

    live_info_base = await get_live_info_table(context, live_difficulty_id)
    if live_info_base is None:
        raise ValueError(f"invalid live_difficulty_id {live_difficulty_id}")

    live_setting = await get_live_setting(context, live_info_base.live_setting_id)
    if live_setting is None:
        raise ValueError(f"invalid live_setting_id {live_info_base.live_setting_id}")

    q = sqlalchemy.select(live.LiveSetting).where(
        live.LiveSetting.live_track_id == live_setting.live_track_id, live.LiveSetting.difficulty <= 3
    )
    live_settings = (await context.db.live.execute(q)).scalars().all()
    live_setting_map = {l.live_setting_id: l for l in live_settings}

    live_info_type = type(live_info_base)
    q = sqlalchemy.select(live_info_type).where(
        live_info_type.live_setting_id.in_([l.live_setting_id for l in live_settings])
    )
    live_infos = (await context.db.live.execute(q)).scalars().all()

    for live_info in live_infos:
        output[live_setting_map[live_info.live_setting_id].difficulty] = live_info.live_difficulty_id
        # Also set cache for the retrieved live difficulty ids
        context.set_cache("adjacent_live_difficulty_id", live_info.live_difficulty_id, output)

    return output
