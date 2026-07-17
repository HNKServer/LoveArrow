from __future__ import annotations

import dataclasses

from .. import idol
from .. import util
from ..config import config
from ..db import main
from . import album
from . import unit


@dataclasses.dataclass
class OnboardingSnapshot:
    """Database state which must stay internally consistent during onboarding."""

    active_units: list[main.Unit]
    all_units: list[main.Unit]
    active_by_id: dict[int, main.Unit]
    deck_data: tuple[main.UnitDeck, list[int]] | None
    deck_ids: list[int]
    album_unit_ids: set[int]
    deck_full: bool
    center_valid: bool


async def snapshot(
    context: idol.BasicSchoolIdolContext, current_user: main.User
) -> OnboardingSnapshot:
    active_units = sorted(
        list(await unit.get_all_units(context, current_user, True)), key=lambda item: item.id
    )
    all_units = sorted(
        list(await unit.get_all_units(context, current_user, None)), key=lambda item: item.id
    )
    deck_data = await unit.load_unit_deck(context, current_user, 1, False)
    deck_ids = list(deck_data[1]) if deck_data is not None else [0] * 9
    active_by_id = {item.id: item for item in active_units}
    album_unit_ids = {item.unit_id for item in await album.all(context, current_user)}
    deck_full = len(deck_ids) == 9 and all(
        owning_id > 0 and owning_id in active_by_id for owning_id in deck_ids
    )
    center_valid = current_user.center_unit_owning_user_id in active_by_id
    return OnboardingSnapshot(
        active_units=active_units,
        all_units=all_units,
        active_by_id=active_by_id,
        deck_data=deck_data,
        deck_ids=deck_ids,
        album_unit_ids=album_unit_ids,
        deck_full=deck_full,
        center_valid=center_valid,
    )


def log_snapshot(label: str, current_user: main.User, state: OnboardingSnapshot) -> None:
    util.log(
        f"CN onboarding {label}",
        f"user={current_user.id}",
        f"tutorial_state={current_user.tutorial_state}",
        f"active={len(state.active_units)}",
        f"all_units={len(state.all_units)}",
        f"album={len(state.album_unit_ids)}",
        f"deck_full={state.deck_full}",
        f"deck={state.deck_ids}",
        f"center={current_user.center_unit_owning_user_id}",
        f"center_valid={state.center_valid}",
        severity=util.logging.WARNING,
    )


def is_v434_v437_completed_empty(
    current_user: main.User, state: OnboardingSnapshot
) -> bool:
    """Match only the impossible account shape created by v4.34-v4.37.

    Requiring an empty album and no active *or inactive* units avoids resetting a
    legitimate completed account merely because it currently has no active deck.
    """

    return (
        current_user.tutorial_state == -1
        and len(state.all_units) == 0
        and not state.album_unit_ids
        and not any(state.deck_ids)
        and current_user.center_unit_owning_user_id == 0
    )


async def repair_v434_v437_completed_empty(
    context: idol.BasicSchoolIdolContext, current_user: main.User
) -> bool:
    if not config.is_cn_compat() or current_user.tutorial_state != -1:
        return False

    state = await snapshot(context, current_user)
    if not is_v434_v437_completed_empty(current_user, state):
        return False

    log_snapshot("repair-before", current_user, state)
    current_user.tutorial_state = 0
    await context.db.main.flush()
    util.log(
        "CN onboarding repair: reset v4.34-v4.37 completed-empty state to 0",
        f"user={current_user.id}",
        severity=util.logging.WARNING,
    )
    return True


def deck_matches_master_ids(state: OnboardingSnapshot, master_ids: list[int]) -> bool:
    if len(state.deck_ids) != len(master_ids) or not all(state.deck_ids):
        return False
    for owning_id, expected_master_id in zip(state.deck_ids, master_ids, strict=True):
        unit_data = state.active_by_id.get(owning_id)
        if unit_data is None or unit_data.unit_id != expected_master_id:
            return False
    return True


async def ensure_starter_roster_and_deck(
    context: idol.SchoolIdolUserParams,
    current_user: main.User,
    master_ids: list[int],
) -> list[main.Unit]:
    """Create missing starter members and rebuild deck 1 idempotently.

    This keeps NPPS4's real unit/album/deck mutations.  It does not return a
    synthetic success response when the database postconditions are absent.
    """

    state = await snapshot(context, current_user)
    candidates_by_master: dict[int, list[main.Unit]] = {}
    for unit_data in state.active_units:
        candidates_by_master.setdefault(unit_data.unit_id, []).append(unit_data)

    selected: list[main.Unit] = []
    used_owning_ids: set[int] = set()
    for master_id in master_ids:
        selected_unit = next(
            (
                item
                for item in candidates_by_master.get(master_id, [])
                if item.id not in used_owning_ids
            ),
            None,
        )
        if selected_unit is None:
            selected_unit = await unit.add_unit_simple(context, current_user, master_id, True)
        if selected_unit is None:
            raise RuntimeError(f"unable to add starter unit {master_id}")
        used_owning_ids.add(selected_unit.id)
        selected.append(selected_unit)

    center = selected[4]
    await unit.idolize(context, current_user, center)
    await unit.set_unit_center(context, current_user, center)

    deck, _ = await unit.load_unit_deck(context, current_user, 1, True)
    await unit.save_unit_deck(context, current_user, deck, [item.id for item in selected])

    # unitSelect is the state-1 operation.  The client then explicitly calls
    # tutorial/progress or tutorial/skip; do not finish onboarding here.
    current_user.tutorial_state = 1
    await context.db.main.flush()
    return selected


async def require_starter_postconditions(
    context: idol.BasicSchoolIdolContext,
    current_user: main.User,
    master_ids: list[int],
    *,
    expected_tutorial_state: int | None = 1,
) -> OnboardingSnapshot:
    """Reject unitSelect success unless the complete client-visible state exists."""

    state = await snapshot(context, current_user)
    problems: list[str] = []

    if (
        expected_tutorial_state is not None
        and current_user.tutorial_state != expected_tutorial_state
    ):
        problems.append(
            f"tutorial_state={current_user.tutorial_state}, "
            f"expected {expected_tutorial_state}"
        )
    if not state.deck_full:
        problems.append("deck 1 is absent or contains invalid owning IDs")
    if not deck_matches_master_ids(state, master_ids):
        problems.append("deck 1 does not match the selected starter master IDs")

    expected_center_owning_id = state.deck_ids[4] if len(state.deck_ids) == 9 else 0
    if current_user.center_unit_owning_user_id != expected_center_owning_id:
        problems.append(
            "center_unit_owning_user_id does not match deck slot 5 "
            f"({current_user.center_unit_owning_user_id} != {expected_center_owning_id})"
        )
    center = state.active_by_id.get(current_user.center_unit_owning_user_id)
    if center is None or center.unit_id != master_ids[4]:
        problems.append("center member is absent or has the wrong master ID")

    missing_album_ids = sorted(set(master_ids) - state.album_unit_ids)
    if missing_album_ids:
        problems.append(f"album rows missing for starter units {missing_album_ids}")

    if problems:
        log_snapshot("postcondition-failed", current_user, state)
        raise RuntimeError("unitSelect postcondition failure: " + "; ".join(problems))

    return state
