import sqlalchemy

from .. import const
from .. import idol
from ..db import main
from ..system import user as user_system


PAGE_SIZE = 20


def _status_int(status: const.FRIEND_STATUS | int) -> int:
    return int(status)


async def get_link(
    context: idol.BasicSchoolIdolContext, /, user_id: int, friend_user_id: int
) -> main.FriendLink | None:
    q = (
        sqlalchemy.select(main.FriendLink)
        .where(main.FriendLink.user_id == user_id, main.FriendLink.friend_user_id == friend_user_id)
        .limit(1)
    )
    result = await context.db.main.execute(q)
    return result.scalar()


async def ensure_link(
    context: idol.BasicSchoolIdolContext,
    /,
    user_id: int,
    friend_user_id: int,
    status: const.FRIEND_STATUS | int,
    *,
    is_new: bool = False,
) -> main.FriendLink:
    now = __import__("time").time()
    link = await get_link(context, user_id, friend_user_id)
    if link is None:
        link = main.FriendLink(
            user_id=user_id,
            friend_user_id=friend_user_id,
            status=_status_int(status),
            is_new=is_new,
        )
        context.db.main.add(link)
    else:
        link.status = _status_int(status)
        link.is_new = is_new
        link.update_date = int(now)
    return link


async def delete_link(context: idol.BasicSchoolIdolContext, /, user_id: int, friend_user_id: int) -> None:
    link = await get_link(context, user_id, friend_user_id)
    if link is not None:
        await context.db.main.delete(link)


async def delete_mutual(context: idol.BasicSchoolIdolContext, /, user_id: int, friend_user_id: int) -> None:
    await delete_link(context, user_id, friend_user_id)
    await delete_link(context, friend_user_id, user_id)


async def make_mutual_friends(
    context: idol.BasicSchoolIdolContext, /, user_a: int, user_b: int, *, is_new_a: bool = True, is_new_b: bool = True
) -> None:
    await ensure_link(context, user_a, user_b, const.FRIEND_STATUS.FRIEND, is_new=is_new_a)
    await ensure_link(context, user_b, user_a, const.FRIEND_STATUS.FRIEND, is_new=is_new_b)


async def get_friend_status(context: idol.BasicSchoolIdolContext, /, current_user: main.User, target_user: main.User):
    if current_user.id == target_user.id:
        return const.FRIEND_STATUS.FRIEND
    link = await get_link(context, current_user.id, target_user.id)
    if link is None:
        return const.FRIEND_STATUS.OTHER
    try:
        return const.FRIEND_STATUS(link.status)
    except ValueError:
        return const.FRIEND_STATUS.OTHER


async def count_by_status(
    context: idol.BasicSchoolIdolContext, /, user: main.User, status: const.FRIEND_STATUS | int
) -> int:
    q = (
        sqlalchemy.select(sqlalchemy.func.count())
        .select_from(main.FriendLink)
        .where(main.FriendLink.user_id == user.id, main.FriendLink.status == _status_int(status))
    )
    result = await context.db.main.execute(q)
    return result.scalar() or 0


async def list_links(
    context: idol.BasicSchoolIdolContext,
    /,
    user: main.User,
    status: const.FRIEND_STATUS | int,
    *,
    sort: int = 0,
    page: int = 0,
    limit: int = PAGE_SIZE,
) -> list[main.FriendLink]:
    q = sqlalchemy.select(main.FriendLink).where(
        main.FriendLink.user_id == user.id,
        main.FriendLink.status == _status_int(status),
    )
    if sort in (1, 2):
        q = q.join(main.User, main.FriendLink.friend_user_id == main.User.id).order_by(
            main.User.level.asc() if sort == 1 else main.User.level.desc()
        )
    elif sort in (9, 10):
        q = q.join(main.User, main.FriendLink.friend_user_id == main.User.id).order_by(
            main.User.update_date.asc() if sort == 9 else main.User.update_date.desc()
        )
    elif sort in (11, 12):
        q = q.order_by(main.FriendLink.insert_date.asc() if sort == 11 else main.FriendLink.insert_date.desc())
    else:
        q = q.order_by(main.FriendLink.insert_date.desc())
    q = q.offset(max(page, 0) * limit).limit(limit)
    result = await context.db.main.execute(q)
    return list(result.scalars())


async def request_friend(context: idol.BasicSchoolIdolContext, /, current_user: main.User, target_user: main.User) -> bool:
    if current_user.id == target_user.id:
        raise idol.error.by_code(idol.error.ERROR_CODE_FRIEND_USER_NOT_EXISTS)
    status = await get_friend_status(context, current_user, target_user)
    if status == const.FRIEND_STATUS.FRIEND:
        return True
    if status == const.FRIEND_STATUS.PENDING:
        raise idol.error.by_code(idol.error.ERROR_CODE_FRIEND_ALREADY_REQUESTING_TO_SPECIFIED_USER)

    reverse = await get_link(context, target_user.id, current_user.id)
    if reverse is not None and reverse.status == int(const.FRIEND_STATUS.PENDING):
        await make_mutual_friends(context, current_user.id, target_user.id, is_new_a=True, is_new_b=True)
        return True

    # Basic capacity checks.  They are deliberately conservative and shared by
    # CN and global clients because all users live in the same NPPS4 database.
    if await count_by_status(context, current_user, const.FRIEND_STATUS.FRIEND) >= current_user.friend_max:
        raise idol.error.by_code(idol.error.ERROR_CODE_FRIEND_COUNT_OVER_LIMIT)
    if await count_by_status(context, target_user, const.FRIEND_STATUS.FRIEND) >= target_user.friend_max:
        raise idol.error.by_code(idol.error.ERROR_CODE_FRIEND_COUNT_OVER_LIMIT_OF_APPLICANT)

    await ensure_link(context, current_user.id, target_user.id, const.FRIEND_STATUS.PENDING, is_new=False)
    await ensure_link(context, target_user.id, current_user.id, const.FRIEND_STATUS.APPROVAL_WAIT, is_new=True)
    return False


async def respond_friend(
    context: idol.BasicSchoolIdolContext, /, current_user: main.User, target_user: main.User, status: int
) -> None:
    current_link = await get_link(context, current_user.id, target_user.id)
    reverse_link = await get_link(context, target_user.id, current_user.id)
    if current_link is None or current_link.status != int(const.FRIEND_STATUS.APPROVAL_WAIT):
        raise idol.error.by_code(idol.error.ERROR_CODE_FRIEND_NOT_REQUESTED_FROM_SPECIFIED_USER)
    if status == 0:
        await delete_mutual(context, current_user.id, target_user.id)
        return
    if status == 2:
        if await count_by_status(context, current_user, const.FRIEND_STATUS.FRIEND) >= current_user.friend_max:
            raise idol.error.by_code(idol.error.ERROR_CODE_FRIEND_COUNT_OVER_LIMIT)
        if await count_by_status(context, target_user, const.FRIEND_STATUS.FRIEND) >= target_user.friend_max:
            raise idol.error.by_code(idol.error.ERROR_CODE_FRIEND_COUNT_OVER_LIMIT_OF_APPLICANT)
        await make_mutual_friends(context, current_user.id, target_user.id, is_new_a=True, is_new_b=True)
        return
    raise idol.error.by_code(idol.error.ERROR_CODE_GAME_LOGIC_ERROR)


async def cancel_request(context: idol.BasicSchoolIdolContext, /, current_user: main.User, target_user: main.User) -> bool:
    current_link = await get_link(context, current_user.id, target_user.id)
    if current_link is None or current_link.status != int(const.FRIEND_STATUS.PENDING):
        raise idol.error.by_code(idol.error.ERROR_CODE_FRIEND_NOT_REQUESTING_TO_SPECIFIED_USER)
    await delete_mutual(context, current_user.id, target_user.id)
    return (await get_friend_status(context, current_user, target_user)) == const.FRIEND_STATUS.FRIEND


async def expel_friend(context: idol.BasicSchoolIdolContext, /, current_user: main.User, target_user: main.User) -> None:
    status = await get_friend_status(context, current_user, target_user)
    if status != const.FRIEND_STATUS.FRIEND:
        raise idol.error.by_code(idol.error.ERROR_CODE_FRIEND_SPECIFIED_USER_IS_NOT_A_FRIEND)
    await delete_mutual(context, current_user.id, target_user.id)


async def mark_seen(context: idol.BasicSchoolIdolContext, /, links: list[main.FriendLink]) -> None:
    for link in links:
        if link.is_new:
            link.is_new = False
