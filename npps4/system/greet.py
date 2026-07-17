import sqlalchemy

from .. import idol
from .. import util
from ..db import main
from ..system import user as user_system

GREETING_PAGE_SIZE = 20
MAX_GREETING_RUNE_LENGTH = 200


async def resolve_user(context: idol.BasicSchoolIdolContext, /, display_user_id: int) -> main.User:
    if display_user_id <= 0:
        raise idol.error.by_code(idol.error.ERROR_CODE_FRIEND_USER_NOT_EXISTS)
    target = await user_system.get(context, display_user_id)
    if target is None:
        try:
            target = await user_system.find_by_invite_code(context, int(display_user_id))
        except (TypeError, ValueError):
            target = None
    if target is None:
        raise idol.error.by_code(idol.error.ERROR_CODE_FRIEND_USER_NOT_EXISTS)
    return target


def normalize_message(message: str) -> str:
    message = message.strip()
    if not message or len(message) > MAX_GREETING_RUNE_LENGTH:
        raise idol.error.by_code(idol.error.ERROR_CODE_GREET_INVALID_CHARACTOR)
    return message


async def create_greeting(
    context: idol.BasicSchoolIdolContext,
    /,
    affector: main.User,
    receiver: main.User,
    message: str,
    replied_notice_id: int = 0,
) -> main.UserGreet:
    if affector.id == receiver.id:
        raise idol.error.by_code(idol.error.ERROR_CODE_FRIEND_USER_NOT_EXISTS)
    reply = False
    if replied_notice_id > 0:
        original = await get_greeting(context, replied_notice_id)
        if original is None or original.receiver_id != affector.id:
            raise idol.error.by_code(idol.error.ERROR_CODE_GAME_LOGIC_ERROR)
        reply = True
    row = main.UserGreet(
        affector_id=affector.id,
        receiver_id=receiver.id,
        message=normalize_message(message),
        reply=reply,
        readed=False,
        deleted_from_affector=False,
        deleted_from_receiver=False,
    )
    context.db.main.add(row)
    return row


async def get_greeting(context: idol.BasicSchoolIdolContext, /, notice_id: int) -> main.UserGreet | None:
    result = await context.db.main.execute(
        sqlalchemy.select(main.UserGreet).where(main.UserGreet.id == notice_id).limit(1)
    )
    return result.scalar()


async def delete_greeting(
    context: idol.BasicSchoolIdolContext, /, current_user: main.User, notice_id: int, is_send_mail: bool
) -> None:
    row = await get_greeting(context, notice_id)
    if row is None:
        raise idol.error.by_code(idol.error.ERROR_CODE_GAME_LOGIC_ERROR)
    if is_send_mail and row.affector_id == current_user.id:
        row.deleted_from_affector = True
        return
    if not is_send_mail and row.receiver_id == current_user.id:
        row.deleted_from_receiver = True
        return
    raise idol.error.by_code(idol.error.ERROR_CODE_GAME_LOGIC_ERROR)


async def list_received(
    context: idol.BasicSchoolIdolContext, /, user: main.User, *, next_id: int = 0, limit: int = GREETING_PAGE_SIZE
) -> list[main.UserGreet]:
    q = sqlalchemy.select(main.UserGreet).where(
        main.UserGreet.receiver_id == user.id,
        main.UserGreet.deleted_from_receiver.is_(False),
    )
    if next_id > 0:
        q = q.where(main.UserGreet.id < next_id)
    q = q.order_by(main.UserGreet.id.desc()).limit(limit)
    result = await context.db.main.execute(q)
    return list(result.scalars())


async def count_sent(context: idol.BasicSchoolIdolContext, /, user: main.User) -> int:
    result = await context.db.main.execute(
        sqlalchemy.select(sqlalchemy.func.count())
        .select_from(main.UserGreet)
        .where(main.UserGreet.affector_id == user.id, main.UserGreet.deleted_from_affector.is_(False))
    )
    return result.scalar() or 0


async def list_sent(
    context: idol.BasicSchoolIdolContext, /, user: main.User, *, offset: int = 0, limit: int = GREETING_PAGE_SIZE
) -> list[main.UserGreet]:
    q = (
        sqlalchemy.select(main.UserGreet)
        .where(main.UserGreet.affector_id == user.id, main.UserGreet.deleted_from_affector.is_(False))
        .order_by(main.UserGreet.id.desc())
        .offset(max(offset, 0))
        .limit(limit)
    )
    result = await context.db.main.execute(q)
    return list(result.scalars())


async def count_unread_received(context: idol.BasicSchoolIdolContext, /, user: main.User) -> int:
    result = await context.db.main.execute(
        sqlalchemy.select(sqlalchemy.func.count())
        .select_from(main.UserGreet)
        .where(
            main.UserGreet.receiver_id == user.id,
            main.UserGreet.deleted_from_receiver.is_(False),
            main.UserGreet.readed.is_(False),
        )
    )
    return result.scalar() or 0


async def mark_received_read(context: idol.BasicSchoolIdolContext, /, user: main.User) -> None:
    await context.db.main.execute(
        sqlalchemy.update(main.UserGreet)
        .where(
            main.UserGreet.receiver_id == user.id,
            main.UserGreet.deleted_from_receiver.is_(False),
            main.UserGreet.readed.is_(False),
        )
        .values(readed=True)
    )


def format_elapsed(ts: int) -> str:
    if ts <= 0:
        return "刚刚"
    delta = max(util.time() - ts, 0)
    if delta < 60:
        return "刚刚"
    if delta < 3600:
        return f"{delta // 60}分钟前"
    if delta < 86400:
        return f"{delta // 3600}小时前"
    return f"{delta // 86400}天前"
