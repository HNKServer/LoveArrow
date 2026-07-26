import hashlib
import itertools

import sqlalchemy

from .. import idol
from .. import util
from ..db import main
from . import user as user_system

VALID_CHARACTERS = "".join(map(chr, itertools.chain(range(ord("A"), ord("Z") + 1), range(ord("0"), ord("9") + 1))))


def _a_sha1(t):
    return hashlib.sha1(t.encode("utf-8")).hexdigest().upper()


def generate_passcode_sha1(transfer_id: str, transfer_code: str):
    return _a_sha1(_a_sha1(transfer_id) + transfer_code)


def generate_transfer_code():
    return "".join(util.SYSRAND.choices(VALID_CHARACTERS, k=12))


def has_passcode_issued(user: main.User):
    return user.transfer_sha1 is not None


async def find_user_by_passcode(context: idol.BasicSchoolIdolContext, /, sha1_code: str):
    q = sqlalchemy.select(main.User).where(main.User.transfer_sha1 == sha1_code)
    result = await context.db.main.execute(q)
    return result.scalar()


async def swap_credentials(
    context: idol.BasicSchoolIdolContext,
    source_user: main.User,
    target_user: main.User,
):
    """Move only the current profile's client identity to ``target_user``.

    The account progress/friend graph is shared, but a CN transfer must not
    erase the target user's GL credentials (and vice versa).
    """
    if source_user.id == target_user.id:
        return
    source_identity = await user_system.get_identity(context, source_user)
    if source_identity is None:
        raise ValueError(f"source user has no {context.profile.value} identity")
    target_identity = await user_system.get_identity(context, target_user)
    if target_identity is not None and target_identity.id != source_identity.id:
        await context.db.main.delete(target_identity)
        await context.db.main.flush()
    source_identity.user_id = target_user.id

    # Update the legacy mirror only where it represents the moved identity.
    if source_user.key == source_identity.login_key:
        source_user.key = None
        source_user.passwd = None
    target_user.key = source_identity.login_key
    target_user.passwd = source_identity.passwd
    await context.db.main.flush()
