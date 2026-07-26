import asyncio

import sqlalchemy

from .. import idol
from .. import util
from ..db import main

QUERY_PER_PAGE = 20


async def get_live_ranking(context: idol.BasicSchoolIdolContext, live_difficulty_id: int, page: int):
    q = (
        sqlalchemy.select(sqlalchemy.func.count())
        .select_from(main.LiveClear)
        .where(main.LiveClear.live_difficulty_id == live_difficulty_id, main.LiveClear.clear_cnt > 0)
    )
    result = await context.db.main.execute(q)
    total_cnt = result.scalar() or 0
    player_scores: list[tuple[int, int]] = []

    if total_cnt > 0:
        q = (
            sqlalchemy.select(main.LiveClear)
            .where(main.LiveClear.live_difficulty_id == live_difficulty_id, main.LiveClear.clear_cnt > 0)
            .order_by(main.LiveClear.hi_score.desc(), main.LiveClear.user_id.asc())
            .limit(QUERY_PER_PAGE)
            .offset(page * QUERY_PER_PAGE)
        )
        result = await context.db.main.execute(q)
        for row in result.scalars():
            player_scores.append((row.user_id, row.hi_score))

    return total_cnt, player_scores


_currently_cleaning = False


async def try_cleanup_daily_rankings(current_day_index: int):
    global _currently_cleaning
    if not _currently_cleaning:
        _currently_cleaning = True
        await asyncio.sleep(5)
        async with idol.BasicSchoolIdolContext() as context:
            two_days_ago = current_day_index - 2
            q = sqlalchemy.delete(main.PlayerRanking).where(main.PlayerRanking.day <= two_days_ago)
            await context.db.main.execute(q)
        _currently_cleaning = False


async def increment_daily_score(context: idol.BasicSchoolIdolContext, user: main.User, inc_score: int):
    current_day_index = util.get_days_since_unix()

    if context.support_background_task():
        context.add_task(try_cleanup_daily_rankings, current_day_index)

    q = sqlalchemy.select(main.PlayerRanking).where(
        main.PlayerRanking.user_id == user.id, main.PlayerRanking.day == current_day_index
    )
    player_score = (await context.db.main.execute(q)).scalar()

    if player_score is None:
        player_score = main.PlayerRanking(user_id=user.id, day=current_day_index, score=0)
        context.db.main.add(player_score)

    player_score.score = player_score.score + inc_score
    await context.db.main.flush()


async def get_daily_ranking(context: idol.BasicSchoolIdolContext, page: int, yesterday: bool):
    """Pagination is hardcoded to 20 entries per page."""

    day_index = util.get_days_since_unix() - yesterday

    # Count
    q = (
        sqlalchemy.select(sqlalchemy.func.count())
        .select_from(main.PlayerRanking)
        .where(main.PlayerRanking.day == day_index)
    )
    total_rankings = (await context.db.main.execute(q)).scalar() or 0

    q = (
        sqlalchemy.select(main.PlayerRanking)
        .where(main.PlayerRanking.day == day_index)
        .order_by(main.PlayerRanking.score.desc(), main.PlayerRanking.user_id)
        .offset(page * 20)
        .limit(20)
    )
    result = await context.db.main.execute(q)

    return result.scalars().all(), total_rankings


async def get_live_rank(
    context: idol.BasicSchoolIdolContext, live_difficulty_id: int, user_id: int
) -> int:
    q = sqlalchemy.select(main.LiveClear).where(
        main.LiveClear.live_difficulty_id == live_difficulty_id,
        main.LiveClear.user_id == user_id,
        main.LiveClear.clear_cnt > 0,
    )
    row = (await context.db.main.execute(q)).scalar_one_or_none()
    if row is None:
        return 0
    ahead_q = sqlalchemy.select(sqlalchemy.func.count()).select_from(main.LiveClear).where(
        main.LiveClear.live_difficulty_id == live_difficulty_id,
        main.LiveClear.clear_cnt > 0,
        sqlalchemy.or_(
            main.LiveClear.hi_score > row.hi_score,
            sqlalchemy.and_(main.LiveClear.hi_score == row.hi_score, main.LiveClear.user_id < user_id),
        ),
    )
    return int((await context.db.main.execute(ahead_q)).scalar() or 0) + 1


async def get_daily_rank(
    context: idol.BasicSchoolIdolContext, user_id: int, yesterday: bool
) -> int:
    day_index = util.get_days_since_unix() - int(bool(yesterday))
    q = sqlalchemy.select(main.PlayerRanking).where(
        main.PlayerRanking.user_id == user_id,
        main.PlayerRanking.day == day_index,
    )
    row = (await context.db.main.execute(q)).scalar_one_or_none()
    if row is None:
        return 0
    ahead_q = sqlalchemy.select(sqlalchemy.func.count()).select_from(main.PlayerRanking).where(
        main.PlayerRanking.day == day_index,
        sqlalchemy.or_(
            main.PlayerRanking.score > row.score,
            sqlalchemy.and_(main.PlayerRanking.score == row.score, main.PlayerRanking.user_id < user_id),
        ),
    )
    return int((await context.db.main.execute(ahead_q)).scalar() or 0) + 1
