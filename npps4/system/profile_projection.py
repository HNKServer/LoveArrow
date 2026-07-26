"""Safe projection of shared user state into the receiving client profile.

The mutable account/friend graph is shared between CN and GL, but immutable
master catalogues are not identical.  Every public cross-user response must
verify IDs against the receiver's active master before serializing them.  This
module deliberately never invents a replacement for region-exclusive content:
common IDs are preserved and unsupported IDs are omitted or reduced to zero.
"""
from __future__ import annotations

import sqlalchemy

from .. import idol
from ..db import item as item_db
from ..db import main
from ..db import unit as unit_db
from .. import db
from . import accessory_master
from . import client_catalogue
from . import costume
from . import profile_unit_master
from . import unit


async def unit_info(context: idol.BasicSchoolIdolContext, unit_id: int):
    """Resolve against the live runtime Master, then the bundled exact profile.

    The target-card repair can create a legitimate late card even when an old
    generated workspace still has an incomplete ``unit.db_``.  The inventory
    projection must use the same exact-profile fallback or the persisted card
    will be hidden from ``unit/unitAll``.
    """
    unit_id = int(unit_id or 0)
    if unit_id <= 0:
        return None
    try:
        resolved = await db.get_decrypted_row(context.db.unit, unit_db.Unit, unit_id)
    except (ValueError, RuntimeError):
        resolved = None
    if resolved is not None:
        return resolved
    try:
        return await profile_unit_master.unit_by_id(context, unit_id)
    except (ValueError, RuntimeError, OSError):
        return None


async def unit_supported(context: idol.BasicSchoolIdolContext, unit_id: int) -> bool:
    return await unit_info(context, unit_id) is not None


async def removable_skill_supported(context: idol.BasicSchoolIdolContext, skill_id: int) -> bool:
    if int(skill_id or 0) <= 0:
        return False
    try:
        return (
            await db.get_decrypted_row(
                context.db.unit, unit_db.RemovableSkill, int(skill_id)
            )
            is not None
        )
    except (ValueError, RuntimeError):
        return False


async def filter_removable_skills(
    context: idol.BasicSchoolIdolContext, skill_ids: list[int]
) -> list[int]:
    result: list[int] = []
    for skill_id in skill_ids:
        if await removable_skill_supported(context, skill_id):
            result.append(int(skill_id))
    return result


async def accessory_supported(context: idol.BasicSchoolIdolContext, accessory_id: int) -> bool:
    if int(accessory_id or 0) <= 0:
        return False
    # Accessory catalogues diverge between the final CN and GL clients.  The
    # normal unit-master provider may be an older shared fallback and must not
    # decide whether an owned accessory is legal for the receiving client.
    try:
        return await accessory_master.accessory_by_id(context, int(accessory_id)) is not None
    except (ValueError, RuntimeError):
        return False


async def award_supported(context: idol.BasicSchoolIdolContext, award_id: int) -> bool:
    if int(award_id or 0) <= 0:
        return False
    try:
        return (
            await db.get_decrypted_row(context.db.item, item_db.Award, int(award_id))
            is not None
        )
    except (ValueError, RuntimeError):
        return False


async def background_supported(context: idol.BasicSchoolIdolContext, background_id: int) -> bool:
    if int(background_id or 0) <= 0:
        return False
    try:
        return (
            await db.get_decrypted_row(context.db.item, item_db.Background, int(background_id))
            is not None
        )
    except (ValueError, RuntimeError):
        return False


async def award_id(context: idol.BasicSchoolIdolContext, raw_id: int) -> int:
    return int(raw_id) if await award_supported(context, raw_id) else 0


async def background_id(context: idol.BasicSchoolIdolContext, raw_id: int) -> int:
    return int(raw_id) if await background_supported(context, raw_id) else 0


async def owned_unit(
    context: idol.BasicSchoolIdolContext, owned: main.Unit | None
) -> tuple[main.Unit, object, object, object] | None:
    """Project an arbitrary owned card into the receiver profile."""
    if owned is None:
        return None
    info = await unit_info(context, owned.unit_id)
    if info is None:
        return None
    try:
        full, stats = await unit.get_unit_data_full_info(
            context,
            owned,
            native_costume_fallback=True,
            social_costume_projection=True,
        )
    except (ValueError, RuntimeError, AssertionError, IndexError):
        return None
    return owned, info, full, stats


async def owned_unit_supported(
    context: idol.BasicSchoolIdolContext, owned: main.Unit | None
) -> bool:
    return await owned_unit(context, owned) is not None


async def main_deck_center_owning_id(
    context: idol.BasicSchoolIdolContext, target_user: main.User
) -> int:
    try:
        active_deck = await unit.load_unit_deck(
            context, target_user, target_user.active_deck_index
        )
    except (ValueError, RuntimeError, AssertionError, IndexError):
        return 0
    if active_deck is None or len(active_deck[1]) < 5:
        return 0
    return int(active_deck[1][4] or 0)


def navigation_partner_owning_id(target_user: main.User) -> int:
    return int(target_user.center_unit_owning_user_id or 0)


async def _get_owned_candidate(
    context: idol.BasicSchoolIdolContext, target_user: main.User, owning_id: int
) -> main.Unit | None:
    owning_id = int(owning_id or 0)
    if owning_id <= 0:
        return None
    candidate = await context.db.main.get(main.Unit, owning_id)
    if (
        candidate is None
        or int(candidate.user_id) != int(target_user.id)
        or not bool(candidate.active)
    ):
        return None
    return candidate


async def _role_projection(
    context: idol.BasicSchoolIdolContext,
    target_user: main.User,
    primary_owning_id: int,
    *,
    excluded_owning_ids: tuple[int, ...] = (),
    require_live_leader: bool = False,
) -> tuple[main.Unit, object, object, object] | None:
    """Project one social role without ever substituting the other role.

    The exact selected card is authoritative.  If it is region-exclusive, a
    same-character card is preferred, followed by another safe active card.
    Explicitly excluded owning IDs (normally the other social role) are never
    used, preventing lead/navigator collapse in either CN->GL or GL->CN.
    """
    excluded = {int(value) for value in excluded_owning_ids if int(value or 0) > 0}
    primary = await _get_owned_candidate(context, target_user, primary_owning_id)
    desired_unit_type = None
    if primary is not None:
        projected = await owned_unit(context, primary)
        if projected is not None and (
            not require_live_leader or await _live_leader_supported(context, projected[1])
        ):
            return projected
        known_types = await client_catalogue.known_unit_type_by_id(context, context.profile.value)
        desired_unit_type = known_types.get(int(primary.unit_id))

    q = (
        sqlalchemy.select(main.Unit)
        .where(main.Unit.user_id == target_user.id, main.Unit.active.is_(True))
        .order_by(
            main.Unit.favorite_flag.desc(),
            main.Unit.love.desc(),
            main.Unit.id.asc(),
        )
    )
    safe_fallbacks: list[tuple[main.Unit, object, object, object]] = []
    known_types = await client_catalogue.known_unit_type_by_id(context, context.profile.value)
    for candidate in (await context.db.main.execute(q)).scalars():
        candidate_id = int(candidate.id or 0)
        if candidate_id == int(primary_owning_id or 0) or candidate_id in excluded:
            continue
        projected = await owned_unit(context, candidate)
        if projected is None:
            continue
        if require_live_leader and not await _live_leader_supported(context, projected[1]):
            continue
        if (
            desired_unit_type is not None
            and known_types.get(int(candidate.unit_id)) == desired_unit_type
        ):
            return projected
        safe_fallbacks.append(projected)
    return safe_fallbacks[0] if safe_fallbacks else None


async def navigation_unit(
    context: idol.BasicSchoolIdolContext, target_user: main.User
) -> tuple[main.Unit, object, object, object] | None:
    partner_id = navigation_partner_owning_id(target_user)
    lead_id = await main_deck_center_owning_id(context, target_user)
    return await _role_projection(
        context, target_user, partner_id, excluded_owning_ids=(lead_id,)
    )


async def main_deck_center_unit(
    context: idol.BasicSchoolIdolContext,
    target_user: main.User,
    *,
    require_live_leader: bool = False,
) -> tuple[main.Unit, object, object, object] | None:
    lead_id = await main_deck_center_owning_id(context, target_user)
    partner_id = navigation_partner_owning_id(target_user)
    return await _role_projection(
        context,
        target_user,
        lead_id,
        excluded_owning_ids=(partner_id,),
        require_live_leader=require_live_leader,
    )


async def representative_unit(
    context: idol.BasicSchoolIdolContext,
    target_user: main.User,
    preferred_owning_ids: tuple[int, ...] = (),
) -> tuple[main.Unit, object, object, object] | None:
    """Generic safe projection retained for non-role-specific call sites."""
    excluded: set[int] = set()
    for owning_id in preferred_owning_ids:
        candidate = await _get_owned_candidate(context, target_user, owning_id)
        if candidate is None:
            continue
        excluded.add(int(candidate.id))
        projected = await owned_unit(context, candidate)
        if projected is not None:
            return projected
    q = (
        sqlalchemy.select(main.Unit)
        .where(main.Unit.user_id == target_user.id, main.Unit.active.is_(True))
        .order_by(main.Unit.favorite_flag.desc(), main.Unit.love.desc(), main.Unit.id.asc())
    )
    for candidate in (await context.db.main.execute(q)).scalars():
        if int(candidate.id) in excluded:
            continue
        projected = await owned_unit(context, candidate)
        if projected is not None:
            return projected
    return None


async def center_unit(
    context: idol.BasicSchoolIdolContext, target_user: main.User
) -> tuple[main.Unit, object, object, object] | None:
    """Traditional social center field: navigation partner, not Live lead."""
    return await navigation_unit(context, target_user)


async def social_costume(
    context: idol.BasicSchoolIdolContext,
    target_user: main.User,
    fallback_projection: tuple[main.Unit, object, object, object] | None = None,
):
    """Return the appearance of the exact projected social card.

    A social response must never combine one owned card's unit/stat/leader data
    with another owned card's navigation costume.  ``fallback_projection`` is
    therefore authoritative: its owning ID selects both the native artwork and
    any cross-profile costume binding.  Only callers without an existing
    projection resolve the safe main-deck center here.
    """
    if fallback_projection is None:
        fallback_projection = await center_unit(context, target_user)
    if fallback_projection is None:
        return None
    owned = fallback_projection[0]
    return await costume.social_appearance_for_owned_unit(
        context, owned, native_fallback=True
    )


async def _live_leader_supported(context: idol.BasicSchoolIdolContext, info: object) -> bool:
    leader_skill_id = int(getattr(info, "default_leader_skill_id", 0) or 0)
    if leader_skill_id <= 0:
        return True
    try:
        leader = await db.get_decrypted_row(
            context.db.unit, unit_db.LeaderSkill, leader_skill_id
        )
    except (ValueError, RuntimeError):
        return False
    return leader is not None


async def live_guest_center_unit(
    context: idol.BasicSchoolIdolContext, target_user: main.User
) -> tuple[main.Unit, object, object, object] | None:
    """Return only the main-deck lead role for Live guest projection."""
    return await main_deck_center_unit(
        context, target_user, require_live_leader=True
    )
