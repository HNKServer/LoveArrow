import pydantic

from . import models
from .. import const
from .. import idol
from .. import util
from ..db import main
from ..system import common
from ..system import friend
from ..system import profile_projection
from ..system import unit
from ..system import unit_model
from ..system import user


class FriendListRequest(pydantic.BaseModel):
    type: int
    sort: int = 0
    page: int = 0


class FriendListFriendUserData(models.UserData):
    comment: str
    elapsed_time_from_login: str
    elapsed_time_from_applied: str


class FriendListFriend(pydantic.BaseModel):
    is_new: bool = False
    user_data: FriendListFriendUserData
    center_unit_info: common.CenterUnitInfo | None = None
    setting_award_id: int


class FriendListResponse(common.TimestampMixin):
    item_count: int
    friend_list: list[FriendListFriend]
    new_friend_list: list


class FriendSearchRequest(pydantic.BaseModel):
    invite_code: str


class FriendSearchUserInfo(pydantic.BaseModel):
    user_id: int
    name: str
    level: int
    cost_max: int
    unit_max: int
    energy_max: int
    friend_max: int
    unit_cnt: int
    elapsed_time_from_login: str
    comment: str


class FriendSearchUnitInfo(unit_model.UnitInfoData):
    attribute: int
    smile: int
    cute: int
    cool: int
    setting_award_id: int
    removable_skill_ids: list[int]


class FriendSearchResponse(common.TimestampMixin):
    user_info: FriendSearchUserInfo
    center_unit_info: FriendSearchUnitInfo
    setting_award_id: int
    is_alliance: bool
    friend_status: const.FRIEND_STATUS


class FriendUserIDRequest(pydantic.BaseModel):
    user_id: int


class FriendResponseRequest(pydantic.BaseModel):
    user_id: int
    status: int


class FriendFlagResponse(pydantic.BaseModel):
    is_friend: bool = False


class EmptyListResponse(pydantic.RootModel[list]):
    root: list = pydantic.Field(default_factory=list)


def _list_type_to_status(list_type: int) -> const.FRIEND_STATUS:
    if list_type == 0:
        return const.FRIEND_STATUS.FRIEND
    if list_type == 1:
        return const.FRIEND_STATUS.PENDING
    if list_type == 2:
        return const.FRIEND_STATUS.APPROVAL_WAIT
    raise idol.error.by_code(idol.error.ERROR_CODE_GAME_LOGIC_ERROR)


def _elapsed(ts: int) -> str:
    if ts <= 0:
        return "Unknown"
    delta = max(util.time() - ts, 0)
    if delta < 60:
        return "Just now"
    if delta < 3600:
        return f"{delta // 60} min ago"
    if delta < 86400:
        return f"{delta // 3600} hr ago"
    return f"{delta // 86400} days ago"


async def _resolve_display_user(context: idol.BasicSchoolIdolContext, display_user_id: int) -> main.User:
    # Canonical social payloads use the internal account id.  Retain invite-code
    # lookup as an input compatibility path for older responses and bookmarks.
    target = await user.get(context, display_user_id)
    if target is None:
        try:
            target = await user.find_by_invite_code(context, int(display_user_id))
        except (TypeError, ValueError):
            target = None
    if target is None:
        raise idol.error.by_code(idol.error.ERROR_CODE_FRIEND_USER_NOT_EXISTS)
    return target


async def _center_unit_info(context: idol.BasicSchoolIdolContext, target_user: main.User) -> common.CenterUnitInfo | None:
    projected = await profile_projection.navigation_unit(context, target_user)
    if projected is None:
        return None
    unit_data, _unit_info, unit_data_full_info, unit_stats = projected
    removable_skills = await profile_projection.filter_removable_skills(
        context, await unit.get_unit_removable_skills(context, unit_data)
    )
    display_costume = await profile_projection.social_costume(
        context, target_user, projected
    )
    return common.CenterUnitInfo(
        unit_id=unit_data_full_info.unit_id,
        level=unit_data_full_info.level,
        love=unit_data_full_info.love,
        rank=unit_data_full_info.rank,
        display_rank=unit_data_full_info.display_rank,
        smile=unit_stats.smile,
        cute=unit_stats.pure,
        cool=unit_stats.cool,
        is_love_max=unit_data_full_info.is_love_max,
        is_rank_max=unit_data_full_info.is_rank_max,
        is_level_max=unit_data_full_info.is_level_max,
        unit_skill_exp=unit_data_full_info.unit_skill_exp,
        removable_skill_ids=removable_skills,
        unit_removable_skill_capacity=unit_data_full_info.unit_removable_skill_capacity,
        costume=display_costume,
    )

async def _friend_list_item(
    context: idol.BasicSchoolIdolContext, link: main.FriendLink
) -> FriendListFriend | None:
    target = await user.get(context, link.friend_user_id)
    if target is None:
        # Orphaned link: hide the unsafe row without mutating the friend graph.
        return None
    center = await _center_unit_info(context, target)
    if center is None:
        # A user with no card representable in this client profile must not be
        # serialized as center_unit_info=null; the KLab UI assumes a table.
        return None
    return FriendListFriend(
        is_new=link.is_new,
        user_data=FriendListFriendUserData(
            user_id=target.id,
            name=target.name,
            level=target.level,
            elapsed_time_from_login=_elapsed(target.update_date),
            elapsed_time_from_applied=_elapsed(max(link.update_date, link.insert_date)),
            comment=target.bio,
        ),
        center_unit_info=center,
        setting_award_id=await profile_projection.award_id(context, target.active_award),
    )


@idol.register("friend", "list")
async def friend_list(context: idol.SchoolIdolUserParams, request: FriendListRequest) -> FriendListResponse:
    current_user = await user.get_current(context)
    status = _list_type_to_status(request.type)
    total = await friend.count_by_status(context, current_user, status)
    links = await friend.list_links(context, current_user, status, sort=request.sort, page=request.page)
    items: list[FriendListFriend] = []
    for link in links:
        item = await _friend_list_item(context, link)
        if item is not None:
            items.append(item)
    await friend.mark_seen(context, links)
    return FriendListResponse(item_count=total, friend_list=items, new_friend_list=[])


@idol.register("friend", "search")
async def friend_search(context: idol.SchoolIdolUserParams, request: FriendSearchRequest) -> FriendSearchResponse:
    current_user = await user.get_current(context)

    try:
        invite_code_int = int(request.invite_code)
    except ValueError:
        raise idol.error.by_code(idol.error.ERROR_CODE_FRIEND_USER_NOT_EXISTS) from None

    target_user = await user.find_by_invite_code(context, invite_code_int)

    if target_user is None:
        raise idol.error.by_code(idol.error.ERROR_CODE_FRIEND_USER_NOT_EXISTS)

    projected = await profile_projection.navigation_unit(context, target_user)
    if projected is None:
        # The account exists, but its center card is region-exclusive.  Do not
        # serialize an invalid master ID into the receiving client.
        raise idol.error.by_code(idol.error.ERROR_CODE_FRIEND_USER_NOT_EXISTS)
    unit_data, unit_info, unit_data_full_info, unit_stats = projected
    setting_award_id = await profile_projection.award_id(context, target_user.active_award)
    removable_skill_ids = await profile_projection.filter_removable_skills(
        context, await unit.get_unit_removable_skills(context, unit_data)
    )
    display_costume = await profile_projection.social_costume(
        context, target_user, projected
    )

    return FriendSearchResponse(
        user_info=FriendSearchUserInfo(
            user_id=target_user.id,
            name=target_user.name,
            level=target_user.level,
            cost_max=((target_user.energy_max + target_user.over_max_energy) // 25)
            * 25,  # TODO get from game variables
            unit_max=target_user.unit_max,
            energy_max=target_user.energy_max,
            friend_max=target_user.friend_max,
            unit_cnt=await unit.count_units(context, target_user, True),
            elapsed_time_from_login=_elapsed(target_user.update_date),
            comment=target_user.bio,
        ),
        center_unit_info=FriendSearchUnitInfo(
            unit_owning_user_id=unit_data_full_info.unit_owning_user_id,
            unit_id=unit_data_full_info.unit_id,
            unit_rarity_id=unit_data_full_info.unit_rarity_id,
            exp=unit_data_full_info.exp,
            next_exp=unit_data_full_info.next_exp,
            level=unit_data_full_info.level,
            level_limit_id=unit_data_full_info.level_limit_id,
            max_level=unit_data_full_info.max_level,
            rank=unit_data_full_info.rank,
            max_rank=unit_data_full_info.max_rank,
            love=unit_data_full_info.love,
            max_love=unit_data_full_info.max_love,
            unit_skill_level=unit_data_full_info.unit_skill_level,
            max_hp=unit_data_full_info.max_hp,
            favorite_flag=unit_data_full_info.favorite_flag,
            display_rank=unit_data_full_info.display_rank,
            unit_skill_exp=unit_data_full_info.unit_skill_exp,
            unit_removable_skill_capacity=unit_data_full_info.unit_removable_skill_capacity,
            is_removable_skill_capacity_max=unit_data_full_info.is_removable_skill_capacity_max,
            is_love_max=unit_data_full_info.is_love_max,
            is_level_max=unit_data_full_info.is_level_max,
            is_rank_max=unit_data_full_info.is_rank_max,
            is_signed=unit_data_full_info.is_signed,
            is_skill_level_max=unit_data_full_info.is_skill_level_max,
            attribute=unit_info.attribute_id,
            smile=unit_stats.smile,
            cute=unit_stats.pure,
            cool=unit_stats.cool,
            setting_award_id=setting_award_id,
            removable_skill_ids=removable_skill_ids,
            costume=display_costume,
        ),
        setting_award_id=setting_award_id,
        is_alliance=False,
        friend_status=await friend.get_friend_status(context, current_user, target_user),
    )


@idol.register("friend", "request", batchable=False)
async def friend_request(context: idol.SchoolIdolUserParams, request: FriendUserIDRequest) -> FriendFlagResponse:
    current_user = await user.get_current(context)
    target = await _resolve_display_user(context, request.user_id)
    is_friend = await friend.request_friend(context, current_user, target)
    return FriendFlagResponse(is_friend=is_friend)


@idol.register("friend", "response", batchable=False)
async def friend_response(context: idol.SchoolIdolUserParams, request: FriendResponseRequest) -> EmptyListResponse:
    current_user = await user.get_current(context)
    target = await _resolve_display_user(context, request.user_id)
    await friend.respond_friend(context, current_user, target, request.status)
    return EmptyListResponse.model_validate([])


@idol.register("friend", "expel", batchable=False)
async def friend_expel(context: idol.SchoolIdolUserParams, request: FriendUserIDRequest) -> EmptyListResponse:
    current_user = await user.get_current(context)
    target = await _resolve_display_user(context, request.user_id)
    await friend.expel_friend(context, current_user, target)
    return EmptyListResponse.model_validate([])


@idol.register("friend", "requestCancel", batchable=False)
async def friend_request_cancel(context: idol.SchoolIdolUserParams, request: FriendUserIDRequest) -> FriendFlagResponse:
    current_user = await user.get_current(context)
    target = await _resolve_display_user(context, request.user_id)
    is_friend = await friend.cancel_request(context, current_user, target)
    return FriendFlagResponse(is_friend=is_friend)
