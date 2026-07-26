from __future__ import annotations

import collections

import pydantic

from .. import idol
from .. import util
from ..system import class_system as class_system_module
from ..system import content_master
from ..system import common
from ..system import eventscenario
from ..system import museum
from ..system import reward
from ..system import user


class EventScenarioChapterList(pydantic.BaseModel):
    event_scenario_id: int
    amount: int
    status: int
    chapter: int
    chapter_asset: str | None = None
    item_id: int
    cost_type: int
    is_reward: bool
    open_flash_flag: int


class EventScenarioInfo(pydantic.BaseModel):
    event_id: int
    open_date: str
    chapter_list: list[EventScenarioChapterList]
    event_scenario_btn_asset: str


class EventScenarioStatusResponse(pydantic.BaseModel):
    event_scenario_list: list[EventScenarioInfo]


class EventScenarioRequest(pydantic.BaseModel):
    event_scenario_id: int


class EventScenarioOpenResponse(pydantic.BaseModel):
    event_scenario_id: int
    status: int


class EventScenarioStartupInfo(pydantic.BaseModel):
    event_id: int
    progress: int
    status: int
    event_scenario_id: int


class EventScenarioStartupResponse(pydantic.BaseModel):
    event_scenario_list: EventScenarioStartupInfo
    scenario_adjustment: int = 50


class EventScenarioRewardRequest(EventScenarioRequest):
    is_skipped: bool = False


class ClearEventScenario(EventScenarioRequest):
    status: int


class EventScenarioRewardResponse(user.UserDiffMixin, common.TimestampMixin):
    clear_event_scenario: ClearEventScenario
    next_level_info: list[user.NextLevelInfo]
    base_reward_info: common.BaseRewardInfo
    item_reward_info: list[common.AnyItem]
    class_system: class_system_module.ClassSystemData = pydantic.Field(
        default_factory=class_system_module.ClassSystemData
    )
    new_achievement_cnt: int = 0
    museum_info: museum.MuseumInfoData
    present_cnt: int


def _event_banner_id(context: idol.BasicSchoolIdolContext, event_id: int) -> int:
    """Return the real banner asset number used by the final clients.

    The response field is not always derived directly from ``event_id``.
    honoka-chan proves the CN-only ``10001 -> 38`` compatibility row, while
    LLSIF@Home's final GL archive proves that post-merge event IDs 221..228
    reuse banner assets 215..222.  Returning the raw event ID for those rows
    makes GL request files which never existed and leaves blank thumbnails.
    """
    del context  # mapping is shared by both final CN and GL catalogues
    if event_id == 10001:
        return 38
    if 221 <= event_id <= 228:
        return event_id - 6
    return event_id


def _event_banner_asset(context: idol.BasicSchoolIdolContext, event_id: int) -> str:
    asset_id = _event_banner_id(context, event_id)
    return f"assets/image/ui/eventscenario/{asset_id}_se_ba_t.png"


@idol.register("eventscenario", "status", exclude_none=True)
async def eventscenario_status(context: idol.SchoolIdolUserParams) -> EventScenarioStatusResponse:
    current_user = await user.get_current(context)
    unlock_rows = await eventscenario.get_all(context, current_user)
    unlock_by_id = {row.event_scenario_id: row for row in unlock_rows}

    grouped: dict[int, list[content_master.EventScenarioMaster]] = collections.defaultdict(list)
    for master in content_master.event_scenarios(context.profile):
        if master.event_scenario_id in unlock_by_id:
            grouped[master.event_id].append(master)

    result: list[EventScenarioInfo] = []
    # The original client presents history events newest-first.
    for event_id in sorted(grouped, reverse=True):
        masters = sorted(grouped[event_id], key=lambda row: (row.chapter, row.event_scenario_id), reverse=True)
        chapter_list: list[EventScenarioChapterList] = []
        for master in masters:
            state = unlock_by_id[master.event_scenario_id]
            chapter_list.append(
                EventScenarioChapterList(
                    event_scenario_id=master.event_scenario_id,
                    amount=master.amount,
                    status=2 if state.completed else 1,
                    chapter=master.chapter,
                    chapter_asset=master.chapter_asset,
                    item_id=master.item_id,
                    cost_type=master.cost_type,
                    # Historical event-point and story-item rewards no longer
                    # have an active scheduler.  Completed archive rows are
                    # replayable content, not a new reward source.
                    is_reward=False,
                    open_flash_flag=1 if state.is_new else 0,
                )
            )

        open_date = masters[0].open_date.replace("/", "-")
        result.append(
            EventScenarioInfo(
                event_id=event_id,
                open_date=open_date,
                chapter_list=chapter_list,
                event_scenario_btn_asset=_event_banner_asset(context, event_id),
            )
        )

    return EventScenarioStatusResponse(event_scenario_list=result)


@idol.register("eventscenario", "open", batchable=False)
async def eventscenario_open(
    context: idol.SchoolIdolUserParams, request: EventScenarioRequest
) -> EventScenarioOpenResponse:
    current_user = await user.get_current(context)
    master = content_master.event_by_id(context.profile, request.event_scenario_id)
    if master is None or not await eventscenario.is_unlocked(context, current_user, request.event_scenario_id):
        raise idol.error.IdolError(detail="event scenario is not available", http_code=403)

    await eventscenario.mark_seen(context, current_user, request.event_scenario_id)
    state = await eventscenario.get(context, current_user, request.event_scenario_id)
    assert state is not None
    return EventScenarioOpenResponse(
        event_scenario_id=request.event_scenario_id,
        status=2 if state.completed else 1,
    )


@idol.register("eventscenario", "startup", batchable=False)
async def eventscenario_startup(
    context: idol.SchoolIdolUserParams, request: EventScenarioRequest
) -> EventScenarioStartupResponse:
    current_user = await user.get_current(context)
    master = content_master.event_by_id(context.profile, request.event_scenario_id)
    state = await eventscenario.get(context, current_user, request.event_scenario_id)
    if master is None or state is None:
        raise idol.error.IdolError(detail="event scenario is not available", http_code=403)

    await eventscenario.mark_seen(context, current_user, request.event_scenario_id)
    return EventScenarioStartupResponse(
        event_scenario_list=EventScenarioStartupInfo(
            event_id=master.event_id,
            progress=master.chapter,
            status=2 if state.completed else 1,
            event_scenario_id=master.event_scenario_id,
        )
    )


@idol.register("eventscenario", "reward", batchable=False)
async def eventscenario_reward(
    context: idol.SchoolIdolUserParams, request: EventScenarioRewardRequest
) -> EventScenarioRewardResponse:
    current_user = await user.get_current(context)
    master = content_master.event_by_id(context.profile, request.event_scenario_id)
    state = await eventscenario.get(context, current_user, request.event_scenario_id)
    if master is None or state is None:
        raise idol.error.IdolError(detail="event scenario is not available", http_code=403)

    before = await user.get_user_info(context, current_user)
    # A post-service archive chapter may already be completed.  Replaying it
    # must still produce the normal result response but never pay the old event
    # reward again.
    if not state.completed:
        await eventscenario.complete(context, current_user, request.event_scenario_id)
    else:
        await eventscenario.mark_seen(context, current_user, request.event_scenario_id)

    return EventScenarioRewardResponse(
        clear_event_scenario=ClearEventScenario(
            event_scenario_id=request.event_scenario_id,
            status=2,
        ),
        before_user_info=before,
        after_user_info=await user.get_user_info(context, current_user),
        next_level_info=await user.add_exp(context, current_user, 0),
        base_reward_info=common.BaseRewardInfo(game_coin=0, game_coin_reward_box_flag=False),
        item_reward_info=[],
        museum_info=await museum.get_museum_info_data(context, current_user),
        present_cnt=await reward.count_presentbox(context, current_user),
    )
