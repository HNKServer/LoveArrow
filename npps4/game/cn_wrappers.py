"""CN compatibility wrappers that reuse NPPS4 gameplay systems.

Only put handlers here when the CN client uses an action name/shape that is not
registered by upstream NPPS4, but the underlying gameplay state already exists
in NPPS4.  These wrappers should translate request/response shape and then call
NPPS4's own system layer.  Do not put no-op stubs or honoka-style shortcuts here;
those belong in cn_optional_stubs.py and must remain opt-in.
"""

import secrets

import pydantic
import sqlalchemy

from . import live as game_live
from .. import idol
from .. import util
from ..db import live as live_db
from ..system import achievement as achievement_system
from ..system import advanced
from ..system import live as live_system
from ..system import user as user_system

from typing import Any


class PagingAccomplishedListRequest(pydantic.BaseModel):
    # honoka-chan request fields.  Keep extra allowed because CN clients include
    # module/action/mgd/timeStamp/commandNum wrapper fields in request_data.
    model_config = pydantic.ConfigDict(extra="allow")

    filter_category_id: int
    from_count: int = 0


class PagingAccomplishedListResponse(pydantic.RootModel[list[achievement_system.AchievementData]]):
    pass


@idol.register("achievement", "pagingAccomplishedList")
async def achievement_paging_accomplished_list(
    context: idol.SchoolIdolUserParams, request: PagingAccomplishedListRequest
) -> PagingAccomplishedListResponse:
    """Return a CN-style paged accomplished achievement list using NPPS4 achievement state."""

    current_user = await user_system.get_current(context)
    accomplished = await achievement_system.get_accomplished_achievements_by_filter_id(
        context, current_user, request.filter_category_id
    )
    rewards = [await achievement_system.get_achievement_rewards(context, ach) for ach in accomplished]
    rewards = await advanced.fixup_achievement_reward(context, current_user, rewards)
    ach_list = await achievement_system.to_game_representation(context, accomplished, rewards)

    start = min(max(request.from_count, 0), len(ach_list))
    end = min(start + 10, len(ach_list))
    return PagingAccomplishedListResponse.model_validate(ach_list[start:end])


class RLiveLotRequest(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="allow")

    member_category: int = 0
    difficulty: int
    attribute: int


class RLiveLiveInfo(pydantic.BaseModel):
    live_difficulty_id: int
    is_random: bool = True
    ac_flag: int
    swing_flag: int


class RLiveLotResponse(pydantic.BaseModel):
    live_info: RLiveLiveInfo
    has_slide_notes: int
    party_list: list[advanced.PartyInfo]
    training_energy: int
    training_energy_max: int
    token: str


class RLiveTokenRequest(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="allow")

    token: str


class RLivePlayRequest(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="allow")

    party_user_id: int
    is_training: bool = False
    unit_deck_id: int
    token: str
    lp_factor: int = 1


class RLiveRewardRequest(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="allow")

    token: str
    live_difficulty_id: int = 0
    is_training: bool = False
    perfect_cnt: int
    great_cnt: int
    good_cnt: int
    bad_cnt: int
    miss_cnt: int
    remain_hp: int
    max_combo: int
    score_smile: int
    score_cute: int
    score_cool: int
    love_cnt: int
    precise_score_log: dict[str, Any]
    event_point: int = 0
    event_id: Any = None


# In-memory token map is intentionally small-scope.  It avoids adding a DB
# migration while still lets rlive/* reuse NPPS4's real live/play and live/reward
# paths.  Losing the map on restart simply invalidates in-progress random lives.
_RLIVE_SESSIONS: dict[tuple[int, str], int] = {}


def _current_random_live_attribute() -> int:
    # CN random-live rotation uses the same configured game-day timezone as
    # special-live rotation.  This is a timezone conversion, not a manual +8h
    # addition to the server's local clock.
    sunday_based = live_system.get_special_live_rotation_sunday_based_weekday()
    return sunday_based % 3 + 1


async def _list_random_live_candidates(
    context: idol.BasicSchoolIdolContext, difficulty: int, attribute: int, member_category: int
) -> list[tuple[int, int, int]]:
    """Return (live_difficulty_id, ac_flag, swing_flag) candidates."""

    conditions = [
        live_db.LiveSetting.difficulty == difficulty,
        live_db.LiveSetting.attribute_icon_id == attribute,
    ]
    if member_category > 0:
        conditions.append(live_db.LiveTrack.member_category == member_category)

    q_normal = (
        sqlalchemy.select(
            live_db.NormalLive.live_difficulty_id,
            live_db.LiveSetting.ac_flag,
            live_db.LiveSetting.swing_flag,
        )
        .join(live_db.LiveSetting, live_db.NormalLive.live_setting_id == live_db.LiveSetting.live_setting_id)
        .join(live_db.LiveTrack, live_db.LiveSetting.live_track_id == live_db.LiveTrack.live_track_id)
        .where(*conditions)
    )
    q_special = (
        sqlalchemy.select(
            live_db.SpecialLive.live_difficulty_id,
            live_db.LiveSetting.ac_flag,
            live_db.LiveSetting.swing_flag,
        )
        .join(live_db.LiveSetting, live_db.SpecialLive.live_setting_id == live_db.LiveSetting.live_setting_id)
        .join(live_db.LiveTrack, live_db.LiveSetting.live_track_id == live_db.LiveTrack.live_track_id)
        .where(*conditions)
    )

    candidates: list[tuple[int, int, int]] = []
    for q in (q_normal.order_by(live_db.NormalLive.live_difficulty_id), q_special.order_by(live_db.SpecialLive.live_difficulty_id)):
        result = await context.db.live.execute(q)
        for row in result.all():
            # Validate beatmap availability so rlive/lot does not hand the client
            # a token that later fails at live/play.
            live_setting = await live_system.get_live_setting_from_difficulty_id(context, row.live_difficulty_id)
            if live_setting is None:
                continue
            if await live_system.get_live_info(context, row.live_difficulty_id, live_setting) is None:
                continue
            candidates.append((row.live_difficulty_id, row.ac_flag, row.swing_flag))

    return candidates


async def _get_rlive_live_difficulty_id(context: idol.SchoolIdolUserParams, token: str) -> int:
    current_user = await user_system.get_current(context)
    if not token:
        raise idol.error.IdolError(detail="random live token is required", http_code=403)
    live_difficulty_id = _RLIVE_SESSIONS.get((current_user.id, token))
    if live_difficulty_id is None:
        raise idol.error.IdolError(detail="random live session not found", http_code=403)
    return live_difficulty_id


async def _delete_rlive_session(context: idol.SchoolIdolUserParams, token: str) -> None:
    current_user = await user_system.get_current(context)
    _RLIVE_SESSIONS.pop((current_user.id, token), None)


@idol.register("rlive", "lot", batchable=False)
async def rlive_lot(context: idol.SchoolIdolUserParams, request: RLiveLotRequest) -> RLiveLotResponse:
    if request.difficulty < 1 or request.difficulty > 4:
        raise idol.error.IdolError(detail="invalid random live difficulty", http_code=403)
    if request.attribute < 1 or request.attribute > 3:
        raise idol.error.IdolError(detail="invalid random live attribute", http_code=403)
    if request.attribute != _current_random_live_attribute():
        raise idol.error.IdolError(detail="attribute does not match current random live rotation", http_code=403)

    candidates = await _list_random_live_candidates(
        context, request.difficulty, request.attribute, request.member_category
    )
    if not candidates:
        raise idol.error.IdolError(detail="no random live candidates available", http_code=403)

    live_difficulty_id, ac_flag, swing_flag = secrets.choice(candidates)
    token = secrets.token_urlsafe(48)
    current_user = await user_system.get_current(context)
    _RLIVE_SESSIONS[(current_user.id, token)] = live_difficulty_id

    party_data = await game_live.live_partylist(
        context,
        game_live.LivePartyListRequest(live_difficulty_id=live_difficulty_id, is_training=False, lp_factor=1),
    )
    return RLiveLotResponse(
        live_info=RLiveLiveInfo(live_difficulty_id=live_difficulty_id, ac_flag=ac_flag, swing_flag=swing_flag),
        has_slide_notes=swing_flag,
        party_list=party_data.party_list,
        training_energy=party_data.training_energy,
        training_energy_max=party_data.training_energy_max,
        token=token,
    )


@idol.register("rlive", "play", batchable=False)
async def rlive_play(context: idol.SchoolIdolUserParams, request: RLivePlayRequest) -> game_live.LivePlayResponse:
    live_difficulty_id = await _get_rlive_live_difficulty_id(context, request.token)
    return await game_live.live_play(
        context,
        game_live.LivePlayRequest(
            party_user_id=request.party_user_id,
            is_training=request.is_training,
            unit_deck_id=request.unit_deck_id,
            live_difficulty_id=live_difficulty_id,
            lp_factor=request.lp_factor,
        ),
    )


@idol.register("rlive", "reward", batchable=False)
async def rlive_reward(context: idol.SchoolIdolUserParams, request: RLiveRewardRequest) -> game_live.LiveRewardResponse:
    live_difficulty_id = await _get_rlive_live_difficulty_id(context, request.token)
    if request.live_difficulty_id not in (0, live_difficulty_id):
        raise idol.error.IdolError(detail="random live difficulty mismatch", http_code=403)
    try:
        return await game_live.live_reward(
            context,
            game_live.LiveRewardRequest(
                live_difficulty_id=live_difficulty_id,
                is_training=request.is_training,
                perfect_cnt=request.perfect_cnt,
                great_cnt=request.great_cnt,
                good_cnt=request.good_cnt,
                bad_cnt=request.bad_cnt,
                miss_cnt=request.miss_cnt,
                remain_hp=request.remain_hp,
                max_combo=request.max_combo,
                score_smile=request.score_smile,
                score_cute=request.score_cute,
                score_cool=request.score_cool,
                love_cnt=request.love_cnt,
                precise_score_log=request.precise_score_log,
                event_point=request.event_point,
                event_id=request.event_id if isinstance(request.event_id, int) else None,
            ),
        )
    finally:
        await _delete_rlive_session(context, request.token)


@idol.register("rlive", "gameover", batchable=False)
async def rlive_gameover(context: idol.SchoolIdolUserParams, request: RLiveTokenRequest) -> None:
    try:
        await game_live.live_gameover(context)
    finally:
        await _delete_rlive_session(context, request.token)


@idol.register("rlive", "continue", batchable=False)
async def rlive_continue(context: idol.SchoolIdolUserParams, request: RLiveTokenRequest) -> game_live.LiveContinueResponse:
    await _get_rlive_live_difficulty_id(context, request.token)
    return await game_live.live_continue(context, game_live.LiveContinueRequest())
