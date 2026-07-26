import pydantic

from .. import idol
from .. import util
from ..system import advanced
from ..system import album
from ..system import live
from ..system import museum
from ..system import profile
from ..system import profile_projection
from ..system import unit
from ..system import friend
from ..system import user


class ProfileLiveCount(pydantic.BaseModel):
    difficulty: int
    clear_cnt: int


class ProfileCardRanking(pydantic.BaseModel):
    unit_id: int
    total_love: int
    rank: int
    sign_flag: bool


class ProfileRequest(pydantic.BaseModel):
    user_id: int


class ProfileUserInfo(pydantic.BaseModel):
    user_id: int
    name: str
    level: int
    cost_max: int = 100  # TODO
    unit_max: int
    energy_max: int
    friend_max: int
    unit_cnt: int
    invite_code: str
    elapsed_time_from_login: str = "unknown"  # TODO
    introduction: str


class ProfileInfoResponse(pydantic.BaseModel):
    user_info: ProfileUserInfo
    center_unit_info: profile.ProfileUnitInfo
    navi_unit_info: profile.ProfileUnitInfo
    is_alliance: bool
    friend_status: int = 0
    setting_award_id: int
    setting_background_id: int


class ProfileRegisterRequest(pydantic.BaseModel):
    introduction: str


class ProfileLiveCountResponse(pydantic.RootModel[list[ProfileLiveCount]]):
    pass


class ProfileCardRankingResponse(pydantic.RootModel[list[ProfileCardRanking]]):
    pass


async def _resolve_profile_user(
    context: idol.BasicSchoolIdolContext, user_id: int
):
    """Resolve a profile reference without mixing account ids and invite codes.

    Friend and greeting payloads now emit the internal account id.  The invite-code
    fallback keeps old cached/list payloads usable and makes the profile endpoints
    tolerant of either historical identifier domain.
    """
    target_user = await user.get(context, user_id)
    if target_user is None:
        target_user = await user.find_by_invite_code(context, user_id)
    if target_user is None:
        raise idol.error.by_code(idol.error.ERROR_CODE_USER_NOT_EXIST)
    return target_user


@idol.register("profile", "liveCnt")
async def profile_livecount(context: idol.SchoolIdolUserParams, request: ProfileRequest) -> ProfileLiveCountResponse:
    target_user = await _resolve_profile_user(context, request.user_id)

    cleared = await live.get_cleared_live_count(context, target_user)
    return ProfileLiveCountResponse(
        [ProfileLiveCount(difficulty=i, clear_cnt=cleared.get(i, 0)) for i in (1, 2, 3, 4, 6)]
    )


@idol.register("profile", "cardRanking")
async def profile_cardranking(
    context: idol.SchoolIdolUserParams, request: ProfileRequest
) -> ProfileCardRankingResponse:
    target_user = await _resolve_profile_user(context, request.user_id)

    entries: list[ProfileCardRanking] = []
    for album_info in await album.all_ranking(context, target_user):
        if not await profile_projection.unit_supported(context, album_info.unit_id):
            continue
        entries.append(
            ProfileCardRanking(
                unit_id=album_info.unit_id,
                total_love=album_info.favorite_point,
                rank=album_info.rank_max_flag + 1,
                sign_flag=album_info.sign_flag,
            )
        )
    return ProfileCardRankingResponse(entries)


@idol.register("profile", "profileInfo")
async def profile_profileinfo(context: idol.SchoolIdolUserParams, request: ProfileRequest) -> ProfileInfoResponse:
    current_user = await user.get_current(context)
    target_user = await _resolve_profile_user(context, request.user_id)

    center_projection = await profile_projection.main_deck_center_unit(
        context, target_user
    )
    partner_projection = await profile_projection.navigation_unit(
        context, target_user
    )
    if center_projection is None or partner_projection is None:
        raise idol.error.by_code(idol.error.ERROR_CODE_USER_NOT_EXIST)

    center_unit = center_projection[0]
    partner_unit = partner_projection[0]
    unit_count = 0
    for owned in await unit.get_all_units(context, target_user):
        if await profile_projection.unit_supported(context, owned.unit_id):
            unit_count += 1
    museum_data = await museum.get_museum_info_data(context, target_user)
    center_costume = await profile_projection.social_costume(
        context, target_user, center_projection
    )
    partner_costume = await profile_projection.social_costume(
        context, target_user, partner_projection
    )

    return ProfileInfoResponse(
        user_info=ProfileUserInfo(
            user_id=target_user.id,
            name=target_user.name,
            level=target_user.level,
            unit_max=target_user.unit_max,
            energy_max=target_user.energy_max,
            friend_max=target_user.friend_max,
            unit_cnt=unit_count,
            invite_code=target_user.invite_code,
            introduction=target_user.bio,
        ),
        center_unit_info=await profile.to_profile_unit_info(
            context,
            center_unit,
            museum_data.parameter,
            display_costume=center_costume,
        ),
        navi_unit_info=await profile.to_profile_unit_info(
            context,
            partner_unit,
            museum_data.parameter,
            display_costume=partner_costume,
        ),
        is_alliance=False,
        friend_status=int(await friend.get_friend_status(context, current_user, target_user)),
        setting_award_id=await profile_projection.award_id(context, target_user.active_award),
        setting_background_id=await profile_projection.background_id(context, target_user.active_background),
    )


@idol.register("profile", "profileRegister")
async def profile_profileregister(context: idol.SchoolIdolUserParams, request: ProfileRegisterRequest) -> None:
    await advanced.test_name(context, request.introduction)
    current_user = await user.get_current(context)
    current_user.bio = request.introduction
