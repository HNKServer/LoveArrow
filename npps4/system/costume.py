from __future__ import annotations

import sqlalchemy

from .. import const
from .. import db
from .. import idol
from ..db import main
from ..db import unit as unit_db
from . import unit as unit_system
from . import unit_model


def _profile(context: idol.BasicSchoolIdolContext) -> str:
    return context.profile.value


def _invalid(detail: str):
    # HTTP 200 plus a game-status error is important here: the KLab client
    # otherwise retries a transport failure and can leave the modal input-locked.
    return idol.error.IdolError(
        idol.error.ERROR_CODE_GAME_LOGIC_ERROR,
        600,
        detail,
        http_code=200,
    )


async def _master(context: idol.BasicSchoolIdolContext, unit_id: int):
    if int(unit_id or 0) <= 0:
        return None
    try:
        return await db.get_decrypted_row(context.db.unit, unit_db.Unit, int(unit_id))
    except (ValueError, RuntimeError):
        return None


async def _registered_key_row(
    context: idol.BasicSchoolIdolContext,
    user: main.User,
    unit_id: int,
    is_signed: bool,
) -> main.UserCostume | None:
    # Client Costume.convertMapId is unit_id + signed; rank is intentionally
    # excluded. There can be only one registered rank variant for this key.
    q = sqlalchemy.select(main.UserCostume).where(
        main.UserCostume.user_id == user.id,
        main.UserCostume.profile == _profile(context),
        main.UserCostume.unit_id == int(unit_id),
        main.UserCostume.is_signed.is_(bool(is_signed)),
    )
    return (await context.db.main.execute(q)).scalar_one_or_none()


async def _registered_row_for_profile(
    context: idol.BasicSchoolIdolContext,
    user_id: int,
    profile: str,
    unit_id: int,
    is_rank_max: bool,
    is_signed: bool,
) -> main.UserCostume | None:
    q = sqlalchemy.select(main.UserCostume).where(
        main.UserCostume.user_id == int(user_id),
        main.UserCostume.profile == str(profile),
        main.UserCostume.unit_id == int(unit_id),
        main.UserCostume.is_signed.is_(bool(is_signed)),
    )
    row = (await context.db.main.execute(q)).scalar_one_or_none()
    if row is None or bool(row.is_rank_max) != bool(is_rank_max):
        return None
    return row


async def _registered_row(
    context: idol.BasicSchoolIdolContext,
    user: main.User,
    unit_id: int,
    is_rank_max: bool,
    is_signed: bool,
) -> main.UserCostume | None:
    return await _registered_row_for_profile(
        context, user.id, _profile(context), unit_id, is_rank_max, is_signed
    )


async def _register_info(
    context: idol.BasicSchoolIdolContext,
    user: main.User,
    *,
    unit_id: int,
    is_rank_max: bool,
    is_signed: bool,
    source_unit_owning_user_id: int,
) -> tuple[unit_model.CostumeInfo, bool]:
    existing = await _registered_key_row(context, user, unit_id, is_signed)
    if existing is not None:
        return (
            unit_model.CostumeInfo(
                unit_id=existing.unit_id,
                is_rank_max=existing.is_rank_max,
                is_signed=existing.is_signed,
            ),
            False,
        )

    row = main.UserCostume(
        user_id=user.id,
        profile=_profile(context),
        unit_id=int(unit_id),
        is_rank_max=bool(is_rank_max),
        is_signed=bool(is_signed),
        source_unit_owning_user_id=int(source_unit_owning_user_id),
    )
    context.db.main.add(row)
    await context.db.main.flush()
    return (
        unit_model.CostumeInfo(
            unit_id=row.unit_id,
            is_rank_max=row.is_rank_max,
            is_signed=row.is_signed,
        ),
        True,
    )


async def is_enabled(context: idol.BasicSchoolIdolContext, user: main.User) -> bool:
    q = sqlalchemy.select(main.UserCostumeSetting).where(
        main.UserCostumeSetting.user_id == user.id,
        main.UserCostumeSetting.profile == _profile(context),
    )
    setting = (await context.db.main.execute(q)).scalar_one_or_none()
    return True if setting is None else bool(setting.enabled)


async def set_enabled(
    context: idol.BasicSchoolIdolContext, user: main.User, enabled: bool
) -> None:
    q = sqlalchemy.select(main.UserCostumeSetting).where(
        main.UserCostumeSetting.user_id == user.id,
        main.UserCostumeSetting.profile == _profile(context),
    )
    setting = (await context.db.main.execute(q)).scalar_one_or_none()
    if setting is None:
        setting = main.UserCostumeSetting(
            user_id=user.id,
            profile=_profile(context),
            enabled=bool(enabled),
        )
        context.db.main.add(setting)
    else:
        setting.enabled = bool(enabled)
    await context.db.main.flush()


async def _discover_costume_only_owned(
    context: idol.BasicSchoolIdolContext,
    user: main.User,
) -> None:
    """Persist client-defined costume-only cards (disable_rank_up == 5).

    The client calls Costume.addCostumeOnly immediately when such a UNIT reward
    is received. Persisting the same entries server-side makes them survive a
    restart and lets costumeList reconstruct the client's local map.
    """
    q = sqlalchemy.select(main.Unit).where(main.Unit.user_id == user.id)
    changed = False
    for owned in (await context.db.main.execute(q)).scalars():
        master = await _master(context, owned.unit_id)
        if master is None or int(master.disable_rank_up) != int(const.UNIT_CATEGORY.COSTUME):
            continue
        full, _stats = await unit_system.get_unit_data_full_info(
            context, owned, include_costume=False
        )
        existing = await _registered_key_row(
            context, user, owned.unit_id, full.is_signed
        )
        if existing is not None:
            continue
        context.db.main.add(
            main.UserCostume(
                user_id=user.id,
                profile=_profile(context),
                unit_id=owned.unit_id,
                is_rank_max=full.is_rank_max,
                is_signed=full.is_signed,
                source_unit_owning_user_id=owned.id,
            )
        )
        changed = True
    if changed:
        await context.db.main.flush()


async def list_registered(
    context: idol.BasicSchoolIdolContext, user: main.User
) -> list[unit_model.CostumeInfo]:
    await _discover_costume_only_owned(context, user)
    q = (
        sqlalchemy.select(main.UserCostume)
        .where(
            main.UserCostume.user_id == user.id,
            main.UserCostume.profile == _profile(context),
        )
        .order_by(
            main.UserCostume.unit_id.asc(),
            main.UserCostume.is_signed.asc(),
            main.UserCostume.id.asc(),
        )
    )
    result: list[unit_model.CostumeInfo] = []
    for row in (await context.db.main.execute(q)).scalars():
        # A shared account can hold a region-exclusive costume registration.
        # Hide it in the receiving profile; never serialize an unknown master ID.
        if await _master(context, row.unit_id) is None:
            continue
        result.append(
            unit_model.CostumeInfo(
                unit_id=row.unit_id,
                is_rank_max=row.is_rank_max,
                is_signed=row.is_signed,
            )
        )
    return result


async def register_from_owned_unit(
    context: idol.BasicSchoolIdolContext,
    user: main.User,
    unit_owning_user_id: int,
) -> tuple[unit_model.CostumeInfo, bool]:
    owned = await context.db.main.get(main.Unit, int(unit_owning_user_id))
    if owned is None or owned.user_id != user.id or not owned.active:
        raise _invalid("The selected card is not an active card owned by this user.")

    master = await _master(context, owned.unit_id)
    if master is None:
        raise _invalid("The selected card is unavailable in this client profile.")

    full, stats = await unit_system.get_unit_data_full_info(
        context, owned, include_costume=False
    )
    if int(master.disable_rank_up) != int(const.UNIT_CATEGORY.COSTUME):
        rarity = await unit_system.get_unit_rarity(context, master.rarity)
        if rarity is None:
            raise _invalid("The selected card rarity data is unavailable.")
        if stats.level < int(rarity.costume_level_limit):
            raise _invalid(
                f"The selected card must reach level {int(rarity.costume_level_limit)} before its costume can be registered."
            )

    # The exact client registers the card's actual rank/sign state. display_rank
    # only changes the card artwork selector and is not the makeCostume contract.
    return await _register_info(
        context,
        user,
        unit_id=owned.unit_id,
        is_rank_max=full.is_rank_max,
        is_signed=full.is_signed,
        source_unit_owning_user_id=owned.id,
    )


async def _remove_dress(
    context: idol.BasicSchoolIdolContext,
    user: main.User,
    unit_owning_user_id: int,
) -> None:
    q = sqlalchemy.delete(main.UserCostumeDress).where(
        main.UserCostumeDress.user_id == user.id,
        main.UserCostumeDress.profile == _profile(context),
        main.UserCostumeDress.unit_owning_user_id == int(unit_owning_user_id),
    )
    await context.db.main.execute(q)
    await context.db.main.flush()


async def dress_up(
    context: idol.BasicSchoolIdolContext,
    user: main.User,
    unit_owning_user_id: int,
    costume_unit_id: int | None,
    is_rank_max: bool | None,
    is_signed: bool | None,
) -> unit_model.CostumeInfo | None:
    target = await context.db.main.get(main.Unit, int(unit_owning_user_id))
    if target is None or target.user_id != user.id or not target.active:
        raise _invalid("The target card is not an active card owned by this user.")

    # The exact client removes a costume by calling dressUp with only the owning
    # ID. Lua omits all three nil appearance fields from the JSON object.
    if costume_unit_id is None:
        await _remove_dress(context, user, target.id)
        return None
    if is_rank_max is None or is_signed is None:
        raise _invalid("A costume rank and signed flag are required when dressing up.")

    # Recover costume-only UNIT rewards for databases created before this route
    # was called, then enforce the exact registered tuple.
    await _discover_costume_only_owned(context, user)
    registered = await _registered_row(
        context, user, costume_unit_id, is_rank_max, is_signed
    )
    if registered is None:
        raise _invalid("The selected costume has not been registered.")

    target_master = await _master(context, target.unit_id)
    costume_master = await _master(context, costume_unit_id)
    if target_master is None or costume_master is None:
        raise _invalid("The selected card or costume is unavailable in this client profile.")
    if int(target_master.unit_type_id) != int(costume_master.unit_type_id):
        raise _invalid("A costume can only be worn by the same school-idol member.")

    # A registered appearance is one wardrobe item. Native/base artwork never
    # consumes it; only a real UserCostumeDress row does. The check is executed
    # only when dressUp is called and does not preload another user's wardrobe.
    in_use_q = sqlalchemy.select(main.UserCostumeDress).where(
        main.UserCostumeDress.user_id == user.id,
        main.UserCostumeDress.profile == _profile(context),
        main.UserCostumeDress.costume_unit_id == int(costume_unit_id),
        main.UserCostumeDress.is_rank_max.is_(bool(is_rank_max)),
        main.UserCostumeDress.is_signed.is_(bool(is_signed)),
        main.UserCostumeDress.unit_owning_user_id != target.id,
    )
    if (await context.db.main.execute(in_use_q)).scalar_one_or_none() is not None:
        raise _invalid("The selected costume is already used by another card.")

    q = sqlalchemy.select(main.UserCostumeDress).where(
        main.UserCostumeDress.user_id == user.id,
        main.UserCostumeDress.profile == _profile(context),
        main.UserCostumeDress.unit_owning_user_id == target.id,
    )
    row = (await context.db.main.execute(q)).scalar_one_or_none()
    if row is None:
        row = main.UserCostumeDress(
            user_id=user.id,
            profile=_profile(context),
            unit_owning_user_id=target.id,
            costume_unit_id=int(costume_unit_id),
            is_rank_max=bool(is_rank_max),
            is_signed=bool(is_signed),
        )
        context.db.main.add(row)
    else:
        row.costume_unit_id = int(costume_unit_id)
        row.is_rank_max = bool(is_rank_max)
        row.is_signed = bool(is_signed)
    await context.db.main.flush()
    return unit_model.CostumeInfo(
        unit_id=int(costume_unit_id),
        is_rank_max=bool(is_rank_max),
        is_signed=bool(is_signed),
    )


async def default_appearance(
    context: idol.BasicSchoolIdolContext,
    owned: main.Unit,
) -> unit_model.CostumeInfo:
    master = await _master(context, owned.unit_id)
    rank_max = bool(master is not None and int(owned.display_rank) >= int(master.rank_max))
    signed = bool(owned.is_signed and await unit_system.has_signed_variant(context, owned.unit_id))
    return unit_model.CostumeInfo(
        unit_id=owned.unit_id,
        is_rank_max=rank_max,
        is_signed=signed,
    )


async def appearance_for_owned_unit(
    context: idol.BasicSchoolIdolContext,
    owned: main.Unit,
) -> unit_model.CostumeInfo | None:
    """Return only a persisted costume override for an owned card.

    The native card appearance is already represented by unit_id, rank,
    display_rank and signed state. Returning it through ``costume`` makes the
    wardrobe client interpret registration as an active SET/occupied binding.
    """
    user = await context.db.main.get(main.User, owned.user_id)
    if user is None or not await is_enabled(context, user):
        return None

    q = sqlalchemy.select(main.UserCostumeDress).where(
        main.UserCostumeDress.user_id == owned.user_id,
        main.UserCostumeDress.profile == _profile(context),
        main.UserCostumeDress.unit_owning_user_id == owned.id,
    )
    row = (await context.db.main.execute(q)).scalar_one_or_none()
    if row is None:
        return None

    registered = await _registered_row(
        context,
        user,
        row.costume_unit_id,
        row.is_rank_max,
        row.is_signed,
    )
    costume_master = await _master(context, row.costume_unit_id)
    target_master = await _master(context, owned.unit_id)
    valid = (
        registered is not None
        and costume_master is not None
        and target_master is not None
        and int(costume_master.unit_type_id) == int(target_master.unit_type_id)
    )
    if not valid:
        await context.db.main.delete(row)
        await context.db.main.flush()
        return None

    return unit_model.CostumeInfo(
        unit_id=row.costume_unit_id,
        is_rank_max=row.is_rank_max,
        is_signed=row.is_signed,
    )

async def _social_dress_rows(
    context: idol.BasicSchoolIdolContext,
    owned: main.Unit,
) -> list[main.UserCostumeDress]:
    """Return targeted social-display bindings, receiver profile first.

    This deliberately performs at most two indexed queries for the one partner
    card being rendered.  It is not a wardrobe preload and creates no process-
    or session-resident per-user cache.
    """
    current_profile = _profile(context)
    exact_q = sqlalchemy.select(main.UserCostumeDress).where(
        main.UserCostumeDress.user_id == owned.user_id,
        main.UserCostumeDress.profile == current_profile,
        main.UserCostumeDress.unit_owning_user_id == owned.id,
    )
    exact = (await context.db.main.execute(exact_q)).scalar_one_or_none()

    other_q = (
        sqlalchemy.select(main.UserCostumeDress)
        .where(
            main.UserCostumeDress.user_id == owned.user_id,
            main.UserCostumeDress.profile != current_profile,
            main.UserCostumeDress.unit_owning_user_id == owned.id,
        )
        .order_by(
            main.UserCostumeDress.update_date.desc(),
            main.UserCostumeDress.id.desc(),
        )
    )
    others = list((await context.db.main.execute(other_q)).scalars())
    return ([exact] if exact is not None else []) + others


async def social_appearance_for_owned_unit(
    context: idol.BasicSchoolIdolContext,
    owned: main.Unit,
    *,
    native_fallback: bool,
) -> unit_model.CostumeInfo | None:
    """Project one user's partner appearance into the receiving client.

    Friend/profile/Live screens carry a viewer-side costume toggle, so their
    payload must contain the target user's selected appearance independently of
    the target user's own local toggle.  Prefer a binding made in the receiver's
    profile, then a binding from the other profile when that costume asset exists
    in the receiving Master DB.  Region-exclusive or stale IDs are skipped, never
    deleted from their source profile, and never serialized to the other client.
    """
    for row in await _social_dress_rows(context, owned):
        registered = await _registered_row_for_profile(
            context,
            owned.user_id,
            row.profile,
            row.costume_unit_id,
            row.is_rank_max,
            row.is_signed,
        )
        if registered is None:
            continue
        costume_master = await _master(context, row.costume_unit_id)
        if costume_master is None:
            continue
        target_master = await _master(context, owned.unit_id)
        if (
            target_master is not None
            and int(costume_master.unit_type_id) != int(target_master.unit_type_id)
        ):
            continue
        if bool(row.is_signed) and not await unit_system.has_signed_variant(
            context, row.costume_unit_id
        ):
            continue
        return unit_model.CostumeInfo(
            unit_id=row.costume_unit_id,
            is_rank_max=row.is_rank_max,
            is_signed=row.is_signed,
        )

    if native_fallback and await _master(context, owned.unit_id) is not None:
        return await default_appearance(context, owned)
    return None

