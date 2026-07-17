import enum
import json

import pydantic

from .. import const
from .. import idol
from .. import util
from ..db import main
from ..system import achievement
from ..system import album
from ..system import ad_model
from ..system import advanced
from ..system import class_system as class_system_module
from ..system import common
from ..system import exchange
from ..system import item
from ..system import item_model
from ..system import museum
from ..system import reward
from ..system import unit
from ..system import unit_model
from ..system import user

from typing import Any


class IncentiveItem(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="allow")

    incentive_id: int
    incentive_item_id: int
    add_type: const.ADD_TYPE
    amount: int
    item_category_id: int
    incentive_message: str
    insert_date: str
    remaining_time: str
    item_option: str | None = None  # FIXME: What is this?

    @staticmethod
    async def from_incentive(context: idol.BasicSchoolIdolContext, i: main.Incentive, /):
        obj = IncentiveItem(
            incentive_id=i.id,
            incentive_item_id=i.item_id,
            add_type=const.ADD_TYPE(i.add_type),
            amount=i.amount,
            item_category_id=0,
            incentive_message=i.get_message(context.lang),
            insert_date=util.timestamp_to_datetime(i.insert_date),
            remaining_time="Forever" if i.expire_date == 0 else util.timestamp_to_datetime(i.expire_date),
        )
        # Add extra fields
        if obj.add_type == const.ADD_TYPE.UNIT:
            extra_data = unit_model.UnitExtraData.EMPTY
            if i.extra_data is not None:
                try:
                    extra_data = unit_model.UnitExtraData.model_validate(json.dumps(i.extra_data))
                except ValueError:
                    pass
            unit_item = await unit.create_unit_item(context, i.item_id, i.amount, extra_data)
            unit.populate_unit_item_to_other(unit_item, obj)
        return obj


class RewardOrder(enum.IntFlag):
    ORDER_ASCENDING = enum.auto()
    BY_EXPIRE_DATE = enum.auto()


class RewardListResponse(pydantic.BaseModel):
    item_count: int
    limit: int = 20
    order: RewardOrder
    items: list[pydantic.SerializeAsAny[IncentiveItem]]
    ad_info: ad_model.AdInfo


class RewardListRequest(reward.FilterConfig):
    order: RewardOrder
    offset: int = 0


class RewardOpenRequest(pydantic.BaseModel):
    incentive_id: int


class RewardSellUnitRequest(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="allow")

    incentive_id: int | None = None
    incentive_ids: list[int] = pydantic.Field(default_factory=list)
    incentive_id_list: list[int] = pydantic.Field(default_factory=list)
    unit_owning_user_id: list[int] = pydantic.Field(default_factory=list)
    unit_support_list: list[unit_model.SupporterInfoResponse] = pydantic.Field(default_factory=list)

    @pydantic.model_validator(mode="before")
    @classmethod
    def normalize_legacy_fields(cls, data):
        if not isinstance(data, dict):
            return data
        result = dict(data)
        # CN/legacy clients and tools may use either singular or list-shaped
        # names.  Normalize them without rejecting unknown request wrapper
        # fields such as module/action/timeStamp.
        if "incentive_ids" not in result and "incentive_id_list" in result:
            result["incentive_ids"] = result["incentive_id_list"]
        if "incentive_id" in result and "incentive_ids" not in result:
            result["incentive_ids"] = [result["incentive_id"]]
        if "unit_owning_user_ids" in result and "unit_owning_user_id" not in result:
            result["unit_owning_user_id"] = result["unit_owning_user_ids"]
        return result


class RewardSellUnitDetail(pydantic.BaseModel):
    unit_owning_user_id: int
    unit_id: int
    is_signed: bool
    amount: int
    price: int


class RewardSellUnitResponse(common.TimestampMixin, user.UserDiffMixin):
    total: int
    detail: list[RewardSellUnitDetail]
    reward_box_flag: bool
    get_exchange_point_list: list[exchange.ExchangePointInfo]
    unit_removable_skill: unit_model.RemovableSkillOwningInfo
    present_cnt: int


class RewardIncentiveItem(item_model.Item, RewardOpenRequest):
    model_config = pydantic.ConfigDict(extra="allow")


class RewardOpenResponse(achievement.AchievementMixin, user.UserDiffMixin, unit_model.SupporterListInfoResponse):
    opened_num: int
    success: list[pydantic.SerializeAsAny[RewardIncentiveItem]]
    class_system: class_system_module.ClassSystemData = pydantic.Field(
        default_factory=class_system_module.ClassSystemData
    )  # TODO
    present_cnt: int


class RewardOpenAllResponse(achievement.AchievementMixin, common.TimestampMixin, user.UserDiffMixin):
    reward_num: int
    opened_num: int
    total_num: int
    order: int
    upper_limit: bool
    reward_item_list: list[pydantic.SerializeAsAny[RewardIncentiveItem]]
    class_system: class_system_module.ClassSystemData = pydantic.Field(
        default_factory=class_system_module.ClassSystemData
    )  # TODO
    new_achievement_cnt: int
    museum_info: museum.MuseumInfoData
    present_cnt: int


class RewardHistoryRequest(reward.FilterConfig):
    incentive_history_id: Any | None = None


class RewardHistoryResponse(pydantic.BaseModel):
    item_count: int
    limit: int = 20
    history: list[IncentiveItem]
    ad_info: ad_model.AdInfo


@idol.register("reward", "rewardList")
async def reward_rewardlist(context: idol.SchoolIdolUserParams, request: RewardListRequest) -> RewardListResponse:
    current_user = await user.get_current(context)
    incentive = await reward.get_presentbox(
        context,
        current_user,
        request,
        request.offset,
        20,
        RewardOrder.ORDER_ASCENDING in request.order,
        RewardOrder.BY_EXPIRE_DATE in request.order,
    )
    incentive_total_count = await reward.count_presentbox(context, current_user, request)

    return RewardListResponse(
        item_count=incentive_total_count,
        order=request.order,
        items=[await IncentiveItem.from_incentive(context, i) for i in incentive],
        ad_info=ad_model.AdInfo(),
    )


async def _sell_presentbox_unit_incentive(
    context: idol.SchoolIdolUserParams,
    current_user: main.User,
    incentive_id: int,
) -> tuple[RewardSellUnitDetail, dict[int, int], int]:
    incentive = await reward.get_incentive(context, current_user, incentive_id)
    if incentive is None:
        raise idol.error.by_code(idol.error.ERROR_CODE_INCENTIVE_NONE)
    if const.ADD_TYPE(incentive.add_type) != const.ADD_TYPE.UNIT:
        raise idol.error.by_code(idol.error.ERROR_CODE_NO_UNIT_IS_SELLABLE)

    item_data = await reward.resolve_incentive(context, current_user, incentive)
    if not isinstance(item_data, unit_model.UnitSupportItem):
        raise idol.error.by_code(idol.error.ERROR_CODE_NO_UNIT_IS_SELLABLE)

    unit_info = await unit.get_unit_info(context, item_data.unit_id)
    if unit_info is None:
        raise idol.error.by_code(idol.error.ERROR_CODE_UNIT_NOT_EXIST)

    # Present-box members are not active owned units yet, so compute a sale price
    # from their serialized unit state rather than creating then deleting a unit.
    if isinstance(item_data, unit_model.UnitItem):
        levelup_pattern = await unit.get_unit_level_up_pattern(context, unit_info.unit_level_up_pattern_id)
        stats = unit.calculate_unit_stats(unit_info, levelup_pattern, item_data.exp)
        amount = 1
        is_signed = item_data.is_signed
    else:
        levelup_pattern = await unit.get_unit_level_up_pattern(context, unit_info.unit_level_up_pattern_id)
        stats = unit.calculate_unit_stats(unit_info, levelup_pattern, 0)
        amount = max(item_data.amount, 1)
        is_signed = False

    total_price = stats.sale_price * amount
    exchange_points: dict[int, int] = {}
    if await exchange.should_give_sticker(context, item_data.unit_id):
        exchange_point_id = await unit.get_exchange_point_id_by_unit_id(context, item_data.unit_id)
        if exchange_point_id > 0:
            exchange_points[exchange_point_id] = amount

    await reward.remove_incentive(context, incentive)
    return (
        RewardSellUnitDetail(
            unit_owning_user_id=0,
            unit_id=item_data.unit_id,
            is_signed=is_signed,
            amount=amount,
            price=total_price,
        ),
        exchange_points,
        total_price,
    )


@idol.register("reward", "sellUnit", batchable=False)
async def reward_sell_unit(context: idol.SchoolIdolUserParams, request: RewardSellUnitRequest) -> RewardSellUnitResponse:
    """Sell members directly from the present box or delegate normal unit sale.

    CN/legacy clients expose reward/sellUnit around the present-box flow.  When
    an incentive id is provided, sell UNIT incentives without first opening them.
    When the request carries active unit ids/support units instead, reuse the
    same semantics as unit/sale while returning a reward-compatible response.
    """

    current_user = await user.get_current(context)
    before_user = await user.get_user_info(context, current_user)
    total = 0
    detail: list[RewardSellUnitDetail] = []
    exchange_point_totals: dict[int, int] = {}

    incentive_ids = list(dict.fromkeys(request.incentive_ids + request.incentive_id_list))
    if request.incentive_id is not None and request.incentive_id not in incentive_ids:
        incentive_ids.insert(0, request.incentive_id)

    if incentive_ids:
        for incentive_id in incentive_ids:
            sell_detail, exchange_points, price = await _sell_presentbox_unit_incentive(
                context, current_user, incentive_id
            )
            detail.append(sell_detail)
            total += price
            for exchange_point_id, amount in exchange_points.items():
                exchange_point_totals[exchange_point_id] = exchange_point_totals.get(exchange_point_id, 0) + amount
    elif request.unit_owning_user_id or request.unit_support_list:
        # Some clients/tools may route regular sale-shaped requests here.  Do the
        # real sale locally instead of pretending there are no sellable units.
        for unit_owning_user_id in request.unit_owning_user_id:
            unit_data = await unit.get_unit(context, unit_owning_user_id)
            unit.validate_unit(current_user, unit_data)
            _, unit_stats = await unit.get_unit_data_full_info(context, unit_data)
            detail.append(
                RewardSellUnitDetail(
                    unit_owning_user_id=unit_owning_user_id,
                    unit_id=unit_data.unit_id,
                    is_signed=unit_data.is_signed,
                    amount=1,
                    price=unit_stats.sale_price,
                )
            )
            total += unit_stats.sale_price
            if await exchange.should_give_sticker(context, unit_data.unit_id):
                exchange_point_id = await unit.get_exchange_point_id_by_unit_id(context, unit_data.unit_id)
                if exchange_point_id > 0:
                    exchange_point_totals[exchange_point_id] = exchange_point_totals.get(exchange_point_id, 0) + 1
            await unit.remove_unit(context, current_user, unit_data)

        for supp_unit in request.unit_support_list:
            if supp_unit.amount <= 0:
                continue
            unit_info = await unit.get_unit_info(context, supp_unit.unit_id)
            if unit_info is None:
                raise idol.error.by_code(idol.error.ERROR_CODE_UNIT_NOT_EXIST)
            if not await unit.sub_supporter_unit(context, current_user, supp_unit.unit_id, supp_unit.amount):
                raise idol.error.by_code(idol.error.ERROR_CODE_UNIT_NOT_EXIST)
            levelup_pattern = await unit.get_unit_level_up_pattern(context, unit_info.unit_level_up_pattern_id)
            stats = unit.calculate_unit_stats(unit_info, levelup_pattern, 0)
            price = stats.sale_price * supp_unit.amount
            detail.append(
                RewardSellUnitDetail(
                    unit_owning_user_id=0,
                    unit_id=supp_unit.unit_id,
                    is_signed=False,
                    amount=supp_unit.amount,
                    price=price,
                )
            )
            total += price
    else:
        raise idol.error.by_code(idol.error.ERROR_CODE_NO_UNIT_IS_SELLABLE)

    if not detail:
        raise idol.error.by_code(idol.error.ERROR_CODE_NO_UNIT_IS_SELLABLE)

    get_exchange_point_list: list[exchange.ExchangePointInfo] = []
    for exchange_point_id, amount in exchange_point_totals.items():
        await exchange.add_exchange_point(context, current_user, exchange_point_id, amount)
        get_exchange_point_list.append(exchange.ExchangePointInfo(rarity=exchange_point_id, exchange_point=amount))

    reward_box_flag = not bool(await advanced.add_item(context, current_user, item.game_coin(total)))

    return RewardSellUnitResponse(
        before_user_info=before_user,
        after_user_info=await user.get_user_info(context, current_user),
        total=total,
        detail=detail,
        reward_box_flag=reward_box_flag,
        get_exchange_point_list=get_exchange_point_list,
        unit_removable_skill=await unit.get_removable_skill_info_request(context, current_user),
        present_cnt=await reward.count_presentbox(context, current_user),
    )


@idol.register("reward", "open")
async def reward_open(context: idol.SchoolIdolUserParams, request: RewardOpenRequest) -> RewardOpenResponse:
    # https://github.com/Salaron/alay/blob/master/src/modules/api/reward/open.ts
    current_user = await user.get_current(context)
    incentive = await reward.get_incentive(context, current_user, request.incentive_id)
    if incentive is None:
        raise idol.error.by_code(idol.error.ERROR_CODE_INCENTIVE_NONE)

    before_user = await user.get_user_info(context, current_user)
    item_data = await reward.resolve_incentive(context, current_user, incentive)
    add_result = await advanced.add_item(context, current_user, item_data)
    supp_units = await unit.get_all_supporter_unit(context, current_user)
    success = bool(add_result)

    album_trigger = []
    achievement_update = []
    if success:
        await reward.remove_incentive(context, incentive)
        if item_data.add_type == const.ADD_TYPE.UNIT and len(album_trigger) == 0:
            album_trigger.append(achievement.AchievementUpdateNewUnit())
            album_trigger.append(achievement.AchievementUpdateUnitRankUp(unit_ids=[]))

        achievement_update.append(
            achievement.AchievementUpdateItemCollect(
                add_type=item_data.add_type, item_id=item_data.item_id, amount=item_data.amount
            )
        )
    else:
        raise idol.error.by_code(idol.error.ERROR_CODE_LIMIT_OVER)

    achievement_list = await achievement.check(context, current_user, *album_trigger, *achievement_update)

    # Give achievement rewards
    accomplished_rewards = [
        await achievement.get_achievement_rewards(context, ach) for ach in achievement_list.accomplished
    ]
    unaccomplished_rewards = [await achievement.get_achievement_rewards(context, ach) for ach in achievement_list.new]
    accomplished_rewards = await advanced.fixup_achievement_reward(context, current_user, accomplished_rewards)
    unaccomplished_rewards = await advanced.fixup_achievement_reward(context, current_user, unaccomplished_rewards)
    await achievement.process_achievement_reward(
        context, current_user, achievement_list.accomplished, accomplished_rewards
    )

    return RewardOpenResponse(
        unit_support_list=[unit_model.SupporterInfoResponse(unit_id=supp[0], amount=supp[1]) for supp in supp_units],
        before_user_info=before_user,
        after_user_info=await user.get_user_info(context, current_user),
        accomplished_achievement_list=await achievement.to_game_representation(
            context, achievement_list.accomplished, accomplished_rewards
        ),
        unaccomplished_achievement_cnt=await achievement.get_achievement_count(context, current_user, False),
        added_achievement_list=await achievement.to_game_representation(
            context, achievement_list.new, unaccomplished_rewards
        ),
        new_achievement_cnt=len(achievement_list.new),
        opened_num=success,
        success=(
            [RewardIncentiveItem.model_validate({"incentive_id": request.incentive_id} | item_data.model_dump())]
            if success
            else []
        ),
        present_cnt=await reward.count_presentbox(context, current_user),
    )


@idol.register("reward", "openAll")
async def reward_openall(context: idol.SchoolIdolUserParams, request: RewardListRequest) -> RewardOpenAllResponse:
    current_user = await user.get_current(context)
    before_user = await user.get_user_info(context, current_user)
    total_presentbox = await reward.count_presentbox(context, current_user, request)
    incentives = await reward.get_presentbox(
        context,
        current_user,
        request,
        0,
        1000,
        RewardOrder.ORDER_ASCENDING in request.order,
        RewardOrder.BY_EXPIRE_DATE in request.order,
    )
    reward_count = len(incentives)
    reward_item_list: list[RewardIncentiveItem] = []
    need_check_unit_ach = False
    achievement_update = []

    for incentive in incentives:
        item_data = await reward.resolve_incentive(context, current_user, incentive)
        add_result = await advanced.add_item(context, current_user, item_data)
        success = bool(add_result)

        if success:
            reward_item_list.append(
                RewardIncentiveItem.model_validate(item_data.model_dump() | {"incentive_id": incentive.id})
            )
            await reward.remove_incentive(context, incentive)
            if item_data.add_type == const.ADD_TYPE.UNIT:
                need_check_unit_ach = True

            achievement_update.append(
                achievement.AchievementUpdateItemCollect(
                    add_type=item_data.add_type, item_id=item_data.item_id, amount=item_data.amount
                )
            )

    if need_check_unit_ach:
        achievement_update.append(achievement.AchievementUpdateNewUnit())
        achievement_update.append(achievement.AchievementUpdateUnitRankUp(unit_ids=[]))

    achievement_list = await achievement.check(context, current_user, *achievement_update)

    # Give achievement rewards
    accomplished_rewards = [
        await achievement.get_achievement_rewards(context, ach) for ach in achievement_list.accomplished
    ]
    unaccomplished_rewards = [await achievement.get_achievement_rewards(context, ach) for ach in achievement_list.new]
    accomplished_rewards = await advanced.fixup_achievement_reward(context, current_user, accomplished_rewards)
    unaccomplished_rewards = await advanced.fixup_achievement_reward(context, current_user, unaccomplished_rewards)
    await achievement.process_achievement_reward(
        context, current_user, achievement_list.accomplished, accomplished_rewards
    )

    opened = len(reward_item_list)

    return RewardOpenAllResponse(
        accomplished_achievement_list=await achievement.to_game_representation(
            context, achievement_list.accomplished, accomplished_rewards
        ),
        unaccomplished_achievement_cnt=await achievement.get_achievement_count(context, current_user, False),
        added_achievement_list=await achievement.to_game_representation(
            context, achievement_list.new, unaccomplished_rewards
        ),
        new_achievement_cnt=len(achievement_list.new),
        reward_num=total_presentbox,
        opened_num=opened,
        total_num=reward_count,
        order=request.order,
        upper_limit=False,
        reward_item_list=reward_item_list,
        before_user_info=before_user,
        after_user_info=await user.get_user_info(context, current_user),
        museum_info=await museum.get_museum_info_data(context, current_user),
        present_cnt=await reward.count_presentbox(context, current_user),
    )


@idol.register("reward", "rewardHistory")
async def reward_rewardhistory(
    context: idol.SchoolIdolUserParams, request: RewardHistoryRequest
) -> RewardHistoryResponse:
    # TODO
    util.stub("reward", "rewardHistory", request)
    return RewardHistoryResponse(item_count=0, history=[], ad_info=ad_model.AdInfo())
