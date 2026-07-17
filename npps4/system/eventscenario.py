from __future__ import annotations

import sqlalchemy

from .. import idol
from ..db import main
from . import cn_content_master


async def valid(context: idol.BasicSchoolIdolContext, event_scenario_id: int) -> bool:
    return cn_content_master.event_by_id(event_scenario_id) is not None


async def get(context: idol.BasicSchoolIdolContext, user: main.User, event_scenario_id: int):
    q = sqlalchemy.select(main.EventScenarioUnlock).where(
        main.EventScenarioUnlock.user_id == user.id,
        main.EventScenarioUnlock.event_scenario_id == event_scenario_id,
    )
    return (await context.db.main.execute(q)).scalar()


async def get_all(context: idol.BasicSchoolIdolContext, user: main.User):
    q = sqlalchemy.select(main.EventScenarioUnlock).where(main.EventScenarioUnlock.user_id == user.id)
    return list((await context.db.main.execute(q)).scalars())


async def unlock(
    context: idol.BasicSchoolIdolContext,
    user: main.User,
    event_scenario_id: int,
    *,
    is_new: bool = True,
    completed: bool = False,
    flush: bool = True,
):
    if not await valid(context, event_scenario_id):
        return False
    row = await get(context, user, event_scenario_id)
    if row is None:
        context.db.main.add(
            main.EventScenarioUnlock(
                user_id=user.id,
                event_scenario_id=event_scenario_id,
                completed=completed,
                is_new=is_new and not completed,
            )
        )
        if flush:
            await context.db.main.flush()
        return True

    changed = False
    if completed and not row.completed:
        row.completed = True
        changed = True
    # A completed archive chapter is no longer a newly-unlocked notification.
    # Conversely, never re-mark an existing completed row as new.
    desired_is_new = is_new and not row.completed
    if row.is_new != desired_is_new and (completed or not row.completed):
        row.is_new = desired_is_new
        changed = True
    if changed and flush:
        await context.db.main.flush()
    return changed


async def is_unlocked(context: idol.BasicSchoolIdolContext, user: main.User, event_scenario_id: int) -> bool:
    return await get(context, user, event_scenario_id) is not None


async def is_completed(context: idol.BasicSchoolIdolContext, user: main.User, event_scenario_id: int) -> bool:
    row = await get(context, user, event_scenario_id)
    return bool(row and row.completed)


async def mark_seen(context: idol.BasicSchoolIdolContext, user: main.User, event_scenario_id: int) -> bool:
    row = await get(context, user, event_scenario_id)
    if row is None or not row.is_new:
        return False
    row.is_new = False
    await context.db.main.flush()
    return True


async def complete(context: idol.BasicSchoolIdolContext, user: main.User, event_scenario_id: int) -> bool:
    row = await get(context, user, event_scenario_id)
    if row is None or row.completed:
        return False
    row.completed = True
    row.is_new = False
    await context.db.main.flush()
    return True
