import pydantic

from .. import const
from .. import idol
from .. import util
from ..system import common

from typing import Any


class NoticeMarquee(pydantic.BaseModel):
    # https://github.com/DarkEnergyProcessor/NPPS/blob/v3.1.x/modules/notice/noticeMarquee.php
    marquee_id: int
    text: str
    text_color: int
    display_place: int
    start_date: str
    end_date: str


class NoticeMarqueeResponse(pydantic.BaseModel):
    item_count: int
    marquee_list: list[NoticeMarquee]


class NoticeFriendVarietyRequest(pydantic.BaseModel):
    filter_id: int
    readed: bool
    page: int


class NoticeFriendVariety(pydantic.BaseModel):
    notice_id: int
    new_flag: bool
    reference_table: int
    filter_id: const.NOTICE_FILTER_ID
    notice_template_id: int
    message: str
    readed: bool
    insert_date: str
    affector: Any | None  # This is FriendSearchResponse


class NoticeFriendVarietyResponse(common.TimestampMixin):
    item_count: int
    notice_list: list[NoticeFriendVariety]


@idol.register("notice", "noticeMarquee")
async def notice_noticemarquee(context: idol.SchoolIdolUserParams) -> NoticeMarqueeResponse:
    # TODO
    util.stub("notice", "noticeMarquee", context.raw_request_data)
    return NoticeMarqueeResponse(item_count=0, marquee_list=[])


@idol.register("notice", "noticeFriendVariety")
async def notice_noticefriendvariety(
    context: idol.SchoolIdolUserParams, request: NoticeFriendVarietyRequest
) -> NoticeFriendVarietyResponse:
    # TODO
    util.stub("notice", "noticeFriendVariety", request)
    return NoticeFriendVarietyResponse(item_count=0, notice_list=[])

# CN/legacy SIF greeting notices.  These are real state-backed handlers backed by
# system.greet.UserGreet, not optional no-op stubs.  They intentionally reuse
# NPPS4's User/Unit state so CN and global clients share the same social layer.
from ..system import greet as greet_system
from ..system import unit as unit_system
from ..system import user as user_system
from ..db import main as main_db


class GreetingNoticeRequest(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="allow")

    next_id: int = 0
    is_previous: bool = False


class GreetingUserData(pydantic.BaseModel):
    user_id: int
    name: str
    level: int


class GreetingAccessoryInfo(pydantic.BaseModel):
    accessory_owning_user_id: int = 0
    accessory_id: int = 0
    exp: int = 0
    next_exp: int = 0
    level: int = 0
    max_level: int = 0
    rank_up_count: int = 0
    favorite_flag: bool = False


class GreetingCenterUnitInfo(pydantic.BaseModel):
    unit_owning_user_id: int = 0
    unit_id: int = 0
    exp: int = 0
    next_exp: int = 0
    level: int = 0
    level_limit_id: int = 0
    max_level: int = 0
    rank: int = 0
    max_rank: int = 0
    love: int = 0
    max_love: int = 0
    unit_skill_level: int = 0
    max_hp: int = 0
    favorite_flag: bool = False
    display_rank: int = 0
    unit_skill_exp: int = 0
    unit_removable_skill_capacity: int = 0
    attribute: int = 0
    smile: int = 0
    cute: int = 0
    cool: int = 0
    is_love_max: bool = False
    is_level_max: bool = False
    is_rank_max: bool = False
    is_signed: bool = False
    is_skill_level_max: bool = False
    setting_award_id: int = 0
    removable_skill_ids: list[int] = pydantic.Field(default_factory=list)
    accessory_info: GreetingAccessoryInfo | None = None


class GreetingPeer(pydantic.BaseModel):
    user_data: GreetingUserData
    center_unit_info: GreetingCenterUnitInfo
    setting_award_id: int


class FriendGreetingNotice(pydantic.BaseModel):
    notice_id: int
    new_flag: bool
    reference_table: int = 6
    message: str
    list_message: str
    readed: bool
    insert_date: str
    affector: GreetingPeer
    reply_flag: bool


class UserGreetingNotice(pydantic.BaseModel):
    notice_id: int
    reference_table: int = 6
    message: str
    list_message: str
    insert_date: str
    receiver: GreetingPeer
    reply_flag: bool
    readed: bool


class FriendGreetingResponse(common.TimestampMixin):
    next_id: int = 0
    notice_list: list[FriendGreetingNotice]


class UserGreetingHistoryResponse(common.TimestampMixin):
    item_count: int
    has_next: bool
    notice_list: list[UserGreetingNotice]


async def _greeting_center_unit_info(context: idol.BasicSchoolIdolContext, target: main_db.User) -> GreetingCenterUnitInfo:
    base = GreetingCenterUnitInfo(setting_award_id=target.active_award)
    if target.center_unit_owning_user_id == 0:
        return base
    unit_data = await unit_system.get_unit(context, target.center_unit_owning_user_id)
    unit_info = await unit_system.get_unit_info(context, unit_data.unit_id)
    if unit_info is None:
        return base
    full, stats = await unit_system.get_unit_data_full_info(context, unit_data)
    return GreetingCenterUnitInfo(
        unit_owning_user_id=full.unit_owning_user_id,
        unit_id=full.unit_id,
        exp=full.exp,
        next_exp=full.next_exp,
        level=full.level,
        level_limit_id=full.level_limit_id,
        max_level=full.max_level,
        rank=full.rank,
        max_rank=full.max_rank,
        love=full.love,
        max_love=full.max_love,
        unit_skill_level=full.unit_skill_level,
        max_hp=full.max_hp,
        favorite_flag=full.favorite_flag,
        display_rank=full.display_rank,
        unit_skill_exp=full.unit_skill_exp,
        unit_removable_skill_capacity=full.unit_removable_skill_capacity,
        attribute=unit_info.attribute_id,
        smile=stats.smile,
        cute=stats.pure,
        cool=stats.cool,
        is_love_max=full.is_love_max,
        is_level_max=full.is_level_max,
        is_rank_max=full.is_rank_max,
        is_signed=full.is_signed,
        is_skill_level_max=full.is_skill_level_max,
        setting_award_id=target.active_award,
        removable_skill_ids=await unit_system.get_unit_removable_skills(context, unit_data),
        accessory_info=None,
    )


async def _greeting_peer(context: idol.BasicSchoolIdolContext, user_id: int) -> GreetingPeer:
    target = await user_system.get(context, user_id)
    if target is None:
        raise idol.error.by_code(idol.error.ERROR_CODE_FRIEND_USER_NOT_EXISTS)
    display_user_id = int(target.invite_code) if target.invite_code.isdigit() else target.id
    return GreetingPeer(
        user_data=GreetingUserData(user_id=display_user_id, name=target.name, level=target.level),
        center_unit_info=await _greeting_center_unit_info(context, target),
        setting_award_id=target.active_award,
    )


@idol.register("notice", "noticeFriendGreeting")
async def notice_friend_greeting(
    context: idol.SchoolIdolUserParams, request: GreetingNoticeRequest
) -> FriendGreetingResponse:
    current_user = await user_system.get_current(context)
    rows = await greet_system.list_received(context, current_user, next_id=request.next_id)
    notice_list = [
        FriendGreetingNotice(
            notice_id=row.id,
            new_flag=not row.readed,
            message=row.message,
            list_message=row.message,
            readed=row.readed,
            insert_date=greet_system.format_elapsed(row.insert_date),
            affector=await _greeting_peer(context, row.affector_id),
            reply_flag=row.reply,
        )
        for row in rows
    ]
    next_id = rows[-1].id if len(rows) >= greet_system.GREETING_PAGE_SIZE else 0
    await greet_system.mark_received_read(context, current_user)
    return FriendGreetingResponse(next_id=next_id, notice_list=notice_list)


@idol.register("notice", "noticeUserGreetingHistory")
async def notice_user_greeting_history(
    context: idol.SchoolIdolUserParams, request: GreetingNoticeRequest
) -> UserGreetingHistoryResponse:
    current_user = await user_system.get_current(context)
    total = await greet_system.count_sent(context, current_user)
    offset = max(request.next_id, 0)
    rows = await greet_system.list_sent(context, current_user, offset=offset)
    notice_list = [
        UserGreetingNotice(
            notice_id=row.id,
            message=row.message,
            list_message=row.message,
            insert_date=greet_system.format_elapsed(row.insert_date),
            receiver=await _greeting_peer(context, row.receiver_id),
            reply_flag=row.reply,
            readed=row.readed,
        )
        for row in rows
    ]
    return UserGreetingHistoryResponse(
        item_count=total,
        has_next=offset + len(rows) < total,
        notice_list=notice_list,
    )
