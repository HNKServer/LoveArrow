from __future__ import annotations

import collections

import pydantic

from .. import idol
from .. import util
from ..system import class_system as class_system_module
from ..system import cn_content_master
from ..system import common
from ..system import multiunit
from ..system import museum
from ..system import reward
from ..system import user


class MultiUnitScenarioChapterList(pydantic.BaseModel):
    multi_unit_scenario_id: int
    status: int
    chapter: int
    chapter_asset: str | None = None


class MultiUnitScenarioInfo(pydantic.BaseModel):
    multi_unit_id: int
    status: int
    open_date: str
    chapter_list: list[MultiUnitScenarioChapterList]
    multi_unit_scenario_btn_asset: str
    multi_unit_scenario_se_btn_asset: str | None = None


class MultiUnitScenarioResponse(pydantic.BaseModel):
    multi_unit_scenario_status_list: list[MultiUnitScenarioInfo]
    unlocked_multi_unit_scenario_ids: list[int] = pydantic.Field(default_factory=list)


class MultiUnitScenarioRequest(pydantic.BaseModel):
    multi_unit_scenario_id: int


class MultiUnitScenarioStartupResponse(MultiUnitScenarioRequest):
    scenario_adjustment: int = 50
    server_timestamp: int = pydantic.Field(default_factory=util.time)


class MultiUnitScenarioRewardRequest(MultiUnitScenarioRequest):
    is_skipped: bool = False


class ClearMultiUnitScenario(MultiUnitScenarioRequest):
    status: int = 2


class MultiUnitScenarioRewardResponse(user.UserDiffMixin, common.TimestampMixin):
    clear_multi_unit_scenario: ClearMultiUnitScenario
    next_level_info: list[user.NextLevelInfo]
    base_reward_info: common.BaseRewardInfo
    item_reward_info: list[common.AnyItem]
    class_system: class_system_module.ClassSystemData = pydantic.Field(
        default_factory=class_system_module.ClassSystemData
    )
    new_achievement_cnt: int = 0
    museum_info: museum.MuseumInfoData
    present_cnt: int


def _se_asset(path: str) -> str | None:
    if not path:
        return None
    if path.endswith(".png"):
        return f"{path[:-4]}se.png"
    return f"{path}se"


@idol.register("multiunit", "multiunitscenarioStatus")
async def multiunit_multiunitscenariostatus(context: idol.SchoolIdolUserParams) -> MultiUnitScenarioResponse:
    current_user = await user.get_current(context)
    unlock_rows = await multiunit.get_all(context, current_user)
    unlock_by_id = {row.multi_unit_scenario_id: row for row in unlock_rows}

    grouped: dict[int, list[cn_content_master.MultiUnitScenarioMaster]] = collections.defaultdict(list)
    for master in cn_content_master.multi_unit_scenarios():
        if master.multi_unit_scenario_id in unlock_by_id:
            grouped[master.multi_unit_id].append(master)

    result: list[MultiUnitScenarioInfo] = []
    unlocked_ids: list[int] = []
    for multi_unit_id in sorted(grouped):
        masters = sorted(grouped[multi_unit_id], key=lambda row: (row.chapter, row.multi_unit_scenario_id))
        chapters: list[MultiUnitScenarioChapterList] = []
        all_completed = True
        for master in masters:
            state = unlock_by_id[master.multi_unit_scenario_id]
            status = 2 if state.completed else 1
            all_completed = all_completed and state.completed
            if state.is_new:
                unlocked_ids.append(master.multi_unit_scenario_id)
            chapters.append(
                MultiUnitScenarioChapterList(
                    multi_unit_scenario_id=master.multi_unit_scenario_id,
                    status=status,
                    chapter=master.chapter,
                    chapter_asset=master.chapter_asset,
                )
            )

        first = masters[0]
        button_asset = context.get_text(first.button_asset, first.button_asset_en) or first.button_asset
        result.append(
            MultiUnitScenarioInfo(
                multi_unit_id=multi_unit_id,
                status=2 if all_completed else 1,
                open_date=first.open_date.replace("/", "-"),
                chapter_list=chapters,
                multi_unit_scenario_btn_asset=button_asset,
                multi_unit_scenario_se_btn_asset=_se_asset(button_asset),
            )
        )

    return MultiUnitScenarioResponse(
        multi_unit_scenario_status_list=result,
        unlocked_multi_unit_scenario_ids=sorted(set(unlocked_ids)),
    )


@idol.register("multiunit", "scenarioStartup", batchable=False)
async def multiunit_scenario_startup(
    context: idol.SchoolIdolUserParams, request: MultiUnitScenarioRequest
) -> MultiUnitScenarioStartupResponse:
    current_user = await user.get_current(context)
    master = cn_content_master.multi_by_id(request.multi_unit_scenario_id)
    state = await multiunit.get(context, current_user, request.multi_unit_scenario_id)
    if master is None or state is None:
        raise idol.error.IdolError(detail="multi-unit scenario is not available", http_code=403)
    await multiunit.mark_seen(context, current_user, request.multi_unit_scenario_id)
    return MultiUnitScenarioStartupResponse(multi_unit_scenario_id=request.multi_unit_scenario_id)


@idol.register("multiunit", "scenarioReward", batchable=False)
async def multiunit_scenario_reward(
    context: idol.SchoolIdolUserParams, request: MultiUnitScenarioRewardRequest
) -> MultiUnitScenarioRewardResponse:
    current_user = await user.get_current(context)
    master = cn_content_master.multi_by_id(request.multi_unit_scenario_id)
    state = await multiunit.get(context, current_user, request.multi_unit_scenario_id)
    if master is None or state is None:
        raise idol.error.IdolError(detail="multi-unit scenario is not available", http_code=403)

    before = await user.get_user_info(context, current_user)
    if not state.completed:
        await multiunit.complete(context, current_user, request.multi_unit_scenario_id)
    else:
        await multiunit.mark_seen(context, current_user, request.multi_unit_scenario_id)

    return MultiUnitScenarioRewardResponse(
        clear_multi_unit_scenario=ClearMultiUnitScenario(
            multi_unit_scenario_id=request.multi_unit_scenario_id,
        ),
        before_user_info=before,
        after_user_info=await user.get_user_info(context, current_user),
        next_level_info=await user.add_exp(context, current_user, 0),
        base_reward_info=common.BaseRewardInfo(game_coin=0, game_coin_reward_box_flag=False),
        item_reward_info=[],
        museum_info=await museum.get_museum_info_data(context, current_user),
        present_cnt=await reward.count_presentbox(context, current_user),
    )
