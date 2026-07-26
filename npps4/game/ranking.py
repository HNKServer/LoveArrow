import pydantic

from . import models
from .. import idol
from ..system import common
from ..system import profile_projection
from ..system import ranking
from ..system import reward
from ..system import unit
from ..system import user


class PageableMixin(pydantic.BaseModel):
    page: int = 0


class RankingLiveRequest(PageableMixin):
    live_difficulty_id: int


class RankingPlayerRequest(PageableMixin):
    id: int = 0  # if nonzero, get current player position
    term: int  # Always 1
    daily_index: int  # 1 = today, 2 = yesterday


class RankingUserData(pydantic.BaseModel):
    user_id: int
    name: str
    level: int


class RankingData(pydantic.BaseModel):
    rank: int
    score: int
    user_data: models.UserData
    center_unit_info: common.CenterUnitInfo
    setting_award_id: int


class RankingResponse(common.TimestampMixin, PageableMixin):
    rank: int = 0
    items: list[RankingData]
    total_cnt: int
    present_cnt: int




async def _ranking_data(
    context: idol.BasicSchoolIdolContext,
    target_user,
    *,
    rank: int,
    score: int,
) -> RankingData | None:
    projected = await profile_projection.center_unit(context, target_user)
    if projected is None:
        return None
    unit_data, _unit_info, unit_full_data, unit_stats = projected
    removable_skills = await profile_projection.filter_removable_skills(
        context, await unit.get_unit_removable_skills(context, unit_data)
    )
    display_costume = await profile_projection.social_costume(
        context, target_user, projected
    )
    return RankingData(
        rank=rank,
        score=score,
        user_data=models.UserData(user_id=target_user.id, name=target_user.name, level=target_user.level),
        center_unit_info=common.CenterUnitInfo(
            unit_id=unit_data.unit_id,
            level=unit_full_data.level,
            rank=unit_data.rank,
            love=unit_data.love,
            display_rank=unit_data.display_rank,
            unit_skill_exp=unit_data.skill_exp,
            unit_removable_skill_capacity=unit_data.unit_removable_skill_capacity,
            smile=unit_stats.smile,
            cute=unit_stats.pure,
            cool=unit_stats.cool,
            is_love_max=unit_full_data.is_love_max,
            is_level_max=unit_full_data.is_level_max,
            is_rank_max=unit_full_data.is_rank_max,
            removable_skill_ids=removable_skills,
            costume=display_costume,
        ),
        setting_award_id=await profile_projection.award_id(context, target_user.active_award),
    )

@idol.register("ranking", "live", xmc_verify=idol.XMCVerifyMode.NONE)
async def ranking_live(context: idol.SchoolIdolUserParams, request: RankingLiveRequest) -> RankingResponse:
    current_user = await user.get_current(context)
    page = max(int(request.page), 0)
    total_cnt, player_scores = await ranking.get_live_ranking(context, request.live_difficulty_id, page)

    rank_player_scores: list[RankingData] = []
    page_offset = page * 20
    for i, (user_id, score) in enumerate(player_scores, page_offset + 1):
        target_user = await user.get(context, user_id)
        if target_user is None:
            continue
        projected = await _ranking_data(context, target_user, rank=i, score=score)
        if projected is not None:
            rank_player_scores.append(projected)

    return RankingResponse(
        page=page,
        rank=await ranking.get_live_rank(context, request.live_difficulty_id, current_user.id),
        items=rank_player_scores,
        total_cnt=total_cnt,
        present_cnt=await reward.count_presentbox(context, current_user),
    )


@idol.register("ranking", "player", xmc_verify=idol.XMCVerifyMode.NONE)
async def ranking_player(context: idol.SchoolIdolUserParams, request: RankingPlayerRequest) -> RankingResponse:
    current_user = await user.get_current(context)

    page = max(int(request.page), 0)
    # honoka-chan does not implement /ranking/player. Its generic router fallback
    # returns a signed HTTP-200 game error (status_code=600, error_code=1), which
    # the clients render as the single safe "contact support" dialog instead of
    # retrying an HTTP transport failure five times. Keep real daily rankings when
    # data exists, but use the same safe fallback while this server has no rows.
    if int(request.term) != 1 or int(request.daily_index) not in (1, 2):
        raise idol.error.by_code(idol.error.ERROR_CODE_LIB_ERROR)

    yesterday = int(request.daily_index) == 2
    # id > 0 requests the current player's position; it is not a user primary key.
    rankings, total_count = await ranking.get_daily_ranking(context, page, yesterday)
    if total_count <= 0:
        raise idol.error.by_code(idol.error.ERROR_CODE_LIB_ERROR)

    items: list[RankingData] = []
    current_rank = await ranking.get_daily_rank(context, current_user.id, yesterday)

    for i, rank in enumerate(rankings, page * 20 + 1):
        target_user = await user.get(context, rank.user_id)
        if target_user is None:
            continue

        projected = await _ranking_data(context, target_user, rank=i, score=rank.score)
        if projected is not None:
            items.append(projected)

    return RankingResponse(
        page=page,
        rank=current_rank,
        items=items,
        total_cnt=total_count,
        present_cnt=await reward.count_presentbox(context, current_user),
    )
