import sqlalchemy

from .. import const
from .. import data
from .. import idol
from ..db import exchange as exchange_db
from ..db import main
from ..db import unit as unit_db
from ..system import advanced
from ..system import client_catalogue
from ..system import accessory as accessory_system
from ..system import accessory_master
from ..system import exchange
from ..system import item
from ..system import item_model
from ..system import profile_unit_master
from ..system import reward
from ..system import scouting_ticket_catalogue
from ..system import unit
from ..system import user as user_system


async def give_all_supporter_units(context: idol.BasicSchoolIdolContext, user: main.User, /):
    q = sqlalchemy.select(unit.unit.Unit.unit_id).where(
        unit.unit.Unit.disable_rank_up > 0, unit.unit.Unit.disable_rank_up < 5
    )
    result = await context.db.unit.execute(q)
    for unit_id in result.scalars():
        item_data = await advanced.deserialize_item_data(
            context, item_model.BaseItem(add_type=const.ADD_TYPE.UNIT, item_id=unit_id, amount=100)
        )
        await reward.add_item(
            context, user, item_data, "追いかける, ショー・ヘーレーション!", "Oikakeru, Snow Halation!"
        )

    return "Given all supporter members (100x quantity each)."


async def _grant_collectible_units(
    context: idol.BasicSchoolIdolContext,
    user: main.User,
) -> tuple[int, int, int]:
    """Grant/max one playable copy of every card known to this profile.

    Common CN/GL unit IDs share the same owning row. Redeeming the code once in
    each client therefore adds only the region-exclusive cards missing from the
    shared account, instead of duplicating the entire catalogue.
    """
    # The configured split Master may omit late CN/GL cards even when the
    # final client and dedicated-accessory table know them. Use the immutable
    # exact receiver-profile unit master as the authority for this test-code
    # grant, then let system.unit's exact fallback serve those rows everywhere.
    master_rows = [
        row
        for row in await profile_unit_master.unit_rows(context)
        if int(row.disable_rank_up)
        in (int(const.UNIT_CATEGORY.NORMAL), int(const.UNIT_CATEGORY.COSTUME))
    ]

    rarity_rows = profile_unit_master.raw_rows(
        context.profile,
        "SELECT rarity, after_love_max, after_level_max FROM unit_rarity_m",
    )
    rarity_map = {
        int(row["rarity"]): (int(row["after_love_max"]), int(row["after_level_max"]))
        for row in rarity_rows
    }

    level_rows = profile_unit_master.raw_rows(
        context.profile,
        "SELECT unit_level_up_pattern_id, unit_level, next_exp FROM unit_level_up_pattern_m",
    )
    level_exp: dict[tuple[int, int], int] = {}
    level_fallback: dict[int, int] = {}
    for row in level_rows:
        pattern_id = int(row["unit_level_up_pattern_id"])
        target_level = int(row["unit_level"]) + 1
        value = int(row["next_exp"])
        level_exp[(pattern_id, target_level)] = value
        level_fallback[pattern_id] = max(level_fallback.get(pattern_id, 0), value)

    skill_pattern_by_id = {
        int(row["unit_skill_id"]): int(row["unit_skill_level_up_pattern_id"])
        for row in profile_unit_master.raw_rows(
            context.profile,
            "SELECT unit_skill_id, unit_skill_level_up_pattern_id FROM unit_skill_m",
        )
    }
    skill_exp_by_pattern: dict[int, int] = {}
    for row in profile_unit_master.raw_rows(
        context.profile,
        "SELECT unit_skill_level_up_pattern_id, next_exp FROM unit_skill_level_up_pattern_m",
    ):
        pattern_id = int(row["unit_skill_level_up_pattern_id"])
        skill_exp_by_pattern[pattern_id] = max(
            skill_exp_by_pattern.get(pattern_id, 0), int(row["next_exp"])
        )

    owned_rows = list(
        (
            await context.db.main.execute(
                sqlalchemy.select(main.Unit)
                .where(main.Unit.user_id == user.id)
                .order_by(main.Unit.id)
            )
        ).scalars()
    )
    owned_by_unit_id: dict[int, list[main.Unit]] = {}
    for owned in owned_rows:
        owned_by_unit_id.setdefault(int(owned.unit_id), []).append(owned)

    album_rows = list(
        (
            await context.db.main.execute(
                sqlalchemy.select(main.Album).where(main.Album.user_id == user.id)
            )
        ).scalars()
    )
    album_by_unit_id = {int(row.unit_id): row for row in album_rows}

    exact_unit_ids = (await client_catalogue.current(context)).unit_ids
    created = 0
    maxed_existing = 0
    costume_sources: dict[int, main.Unit] = {}
    for master in master_rows:
        unit_id = int(master.unit_id)
        if unit_id not in exact_unit_ids:
            continue
        rarity_id = int(master.rarity)
        rarity = rarity_map.get(rarity_id)
        if rarity is None:
            continue
        max_love, max_level = rarity
        pattern_id = int(master.unit_level_up_pattern_id)
        max_exp = level_exp.get(
            (pattern_id, max_level), level_fallback.get(pattern_id, 0)
        )
        skill_id = int(master.default_unit_skill_id or 0)
        skill_pattern = skill_pattern_by_id.get(skill_id, 0)
        max_skill_exp = skill_exp_by_pattern.get(skill_pattern, 0)

        rows = owned_by_unit_id.get(unit_id)
        if not rows:
            owned = main.Unit(
                user_id=user.id,
                unit_id=unit_id,
                active=True,
                exp=max_exp,
                skill_exp=max_skill_exp,
                max_level=max_level,
                love=max_love,
                rank=int(master.rank_max),
                display_rank=int(master.rank_max),
                level_limit_id=int(rarity_id == 4),
                unit_removable_skill_capacity=int(master.max_removable_skill_capacity),
            )
            context.db.main.add(owned)
            owned_by_unit_id[unit_id] = [owned]
            rows = [owned]
            created += 1
        else:
            maxed_existing += 1

        # Max all existing copies as well. This is a test-code action and makes
        # duplicate/deck copies immediately usable without changing ownership.
        for owned in rows:
            owned.exp = max(int(owned.exp), max_exp)
            owned.skill_exp = max(int(owned.skill_exp), max_skill_exp)
            owned.max_level = max(int(owned.max_level), max_level)
            owned.love = max(int(owned.love), max_love)
            owned.rank = max(int(owned.rank), int(master.rank_max))
            owned.display_rank = max(int(owned.display_rank), int(master.rank_max))
            owned.unit_removable_skill_capacity = max(
                int(owned.unit_removable_skill_capacity),
                int(master.max_removable_skill_capacity),
            )

        album_row = album_by_unit_id.get(unit_id)
        if album_row is None:
            album_row = main.Album(user_id=user.id, unit_id=unit_id)
            context.db.main.add(album_row)
            album_by_unit_id[unit_id] = album_row
        album_row.rank_max_flag = True
        album_row.love_max_flag = True
        album_row.rank_level_max_flag = True
        album_row.highest_love_per_unit = max(
            int(album_row.highest_love_per_unit), max_love
        )

        if int(master.disable_rank_up) == int(const.UNIT_CATEGORY.COSTUME):
            costume_sources[unit_id] = rows[0]

    await context.db.main.flush()

    # Costume-only cards are meant to appear in the costume catalogue as soon
    # as they are obtained. Normal cards remain max-level and can be registered
    # manually, preserving the actual costume registration workflow for tests.
    profile_value = getattr(context.profile, "value", str(context.profile))
    existing_costume_ids = set(
        (
            await context.db.main.execute(
                sqlalchemy.select(main.UserCostume.unit_id).where(
                    main.UserCostume.user_id == user.id,
                    main.UserCostume.profile == profile_value,
                    main.UserCostume.is_signed.is_(False),
                )
            )
        ).scalars()
    )
    registered = 0
    for unit_id, source in costume_sources.items():
        if unit_id in existing_costume_ids:
            continue
        context.db.main.add(
            main.UserCostume(
                user_id=user.id,
                profile=profile_value,
                unit_id=unit_id,
                is_rank_max=True,
                is_signed=False,
                source_unit_owning_user_id=source.id,
            )
        )
        registered += 1

    await context.db.main.flush()
    return created, maxed_existing, registered


async def _create_maxed_profile_unit(
    context: idol.BasicSchoolIdolContext,
    user: main.User,
    unit_id: int,
) -> main.Unit:
    """Create one maxed collectible card from the exact receiver master.

    This is used only by the explicit test serial code.  It is intentionally
    independent of the mutable split Master so a late CN/GL card referenced by
    ``accessory_special_m`` cannot be silently skipped merely because the
    reconstructed runtime database omitted its template row.
    """
    unit_info = await unit.get_unit_info(context, int(unit_id))
    rarity = await unit.get_unit_rarity(context, int(unit_info.rarity))
    if rarity is None:
        raise RuntimeError(f"missing rarity {unit_info.rarity} for exact unit {unit_id}")
    max_level = int(rarity.after_level_max)
    level_pattern = await unit.get_unit_level_up_pattern(
        context, int(unit_info.unit_level_up_pattern_id)
    )
    if not level_pattern:
        raise RuntimeError(f"missing level pattern for exact unit {unit_id}")
    max_exp = int(unit.get_exp_for_target_level(unit_info, level_pattern, max_level))
    max_skill_exp = int(await unit.get_max_skill_exp(context, unit_info=unit_info))
    owned = main.Unit(
        user_id=user.id,
        unit_id=int(unit_id),
        active=True,
        favorite_flag=False,
        is_signed=False,
        exp=max_exp,
        skill_exp=max_skill_exp,
        max_level=max_level,
        love=int(rarity.after_love_max),
        rank=int(unit_info.rank_max),
        display_rank=int(unit_info.rank_max),
        level_limit_id=int(int(unit_info.rarity) == 4),
        unit_removable_skill_capacity=int(unit_info.max_removable_skill_capacity),
    )
    context.db.main.add(owned)
    return owned


async def _create_maxed_unit_from_bundled_profile(
    context: idol.BasicSchoolIdolContext,
    user: main.User,
    unit_id: int,
    source_profile: str,
) -> main.Unit:
    """Create one card directly from a named bundled immutable Unit Master.

    A shared account can own a GL dedicated accessory while the serial WebView
    is opened from CN (and vice versa).  In that case the target card must be
    resolved from the profile which defines the accessory.  No installed APK
    or client-side file is consulted.
    """
    unit_rows = profile_unit_master.raw_rows(
        source_profile,
        "SELECT * FROM unit_m WHERE unit_id=:id LIMIT 1",
        {"id": int(unit_id)},
    )
    if not unit_rows:
        raise RuntimeError(
            f"{source_profile.upper()} exact Unit Master has no unit {unit_id}"
        )
    unit_info = unit_rows[0]

    rarity_rows = profile_unit_master.raw_rows(
        source_profile,
        "SELECT * FROM unit_rarity_m WHERE rarity=:id LIMIT 1",
        {"id": int(unit_info["rarity"])},
    )
    if not rarity_rows:
        raise RuntimeError(
            f"{source_profile.upper()} exact Unit Master has no rarity "
            f"{unit_info['rarity']} for unit {unit_id}"
        )
    rarity = rarity_rows[0]
    max_level = int(rarity["after_level_max"])

    level_rows = profile_unit_master.raw_rows(
        source_profile,
        "SELECT unit_level, next_exp FROM unit_level_up_pattern_m "
        "WHERE unit_level_up_pattern_id=:id ORDER BY unit_level",
        {"id": int(unit_info["unit_level_up_pattern_id"])},
    )
    if not level_rows:
        raise RuntimeError(
            f"{source_profile.upper()} exact Unit Master has no level pattern "
            f"for unit {unit_id}"
        )
    max_exp = next(
        (
            int(row["next_exp"])
            for row in level_rows
            if int(row["unit_level"]) == max_level - 1
        ),
        int(level_rows[-2 if len(level_rows) > 1 else -1]["next_exp"]),
    )

    max_skill_exp = 0
    skill_id = int(unit_info.get("default_unit_skill_id") or 0)
    if skill_id > 0:
        skill_rows = profile_unit_master.raw_rows(
            source_profile,
            "SELECT unit_skill_level_up_pattern_id FROM unit_skill_m "
            "WHERE unit_skill_id=:id LIMIT 1",
            {"id": skill_id},
        )
        if skill_rows:
            skill_level_rows = profile_unit_master.raw_rows(
                source_profile,
                "SELECT skill_level, next_exp FROM unit_skill_level_up_pattern_m "
                "WHERE unit_skill_level_up_pattern_id=:id ORDER BY skill_level",
                {"id": int(skill_rows[0]["unit_skill_level_up_pattern_id"])},
            )
            if len(skill_level_rows) > 1:
                max_skill_exp = int(skill_level_rows[-2]["next_exp"])

    owned = main.Unit(
        user_id=user.id,
        unit_id=int(unit_id),
        active=True,
        favorite_flag=False,
        is_signed=False,
        exp=max_exp,
        skill_exp=max_skill_exp,
        max_level=max_level,
        love=int(rarity["after_love_max"]),
        rank=int(unit_info["rank_max"]),
        display_rank=int(unit_info["rank_max"]),
        level_limit_id=int(int(unit_info["rarity"]) == 4),
        unit_removable_skill_capacity=int(
            unit_info.get("max_removable_skill_capacity") or 0
        ),
    )
    context.db.main.add(owned)
    return owned


async def _special_accessory_target_sources(
    context: idol.BasicSchoolIdolContext,
    user: main.User,
) -> tuple[dict[int, set[str]], dict[str, int]]:
    """Resolve target cards from the Master actually relevant to this account.

    Sources are intentionally combined:
    * the active runtime ``accessory_special_m`` (authoritative for the current
      deployment and data package);
    * the bundled exact current-profile map (fresh-account fallback);
    * CN and GL bundled mappings for accessories already owned by the shared
      account. This last source is essential because accessory inventory is
      shared and an accessory obtained in GL remains visible from CN.
    """
    current_profile = context.profile.value
    sources: dict[int, set[str]] = {}
    stats = {
        "runtime_pairs": 0,
        "current_exact_pairs": 0,
        "owned_accessories": 0,
        "owned_cross_profile_pairs": 0,
    }

    def add(unit_id: int, profile: str) -> None:
        unit_id = int(unit_id or 0)
        if unit_id > 0:
            sources.setdefault(unit_id, set()).add(str(profile).lower())

    # Prefer the live runtime Master. It may be newer or combined compared with
    # an originally extracted client snapshot.
    try:
        runtime_rows = (
            await context.db.unit.execute(
                sqlalchemy.select(
                    unit_db.AccessorySpecial.accessory_id,
                    unit_db.AccessorySpecial.unit_id,
                )
            )
        ).all()
    except Exception:
        runtime_rows = []
    stats["runtime_pairs"] = len(runtime_rows)
    for row in runtime_rows:
        add(int(row.unit_id), current_profile)

    current_rows = accessory_master.raw_rows_for_profile(
        current_profile,
        "SELECT accessory_id, unit_id FROM accessory_special_m",
    )
    stats["current_exact_pairs"] = len(current_rows)
    for row in current_rows:
        add(int(row["unit_id"]), current_profile)

    owned_accessory_ids = {
        int(value)
        for value in (
            await context.db.main.execute(
                sqlalchemy.select(main.UserAccessory.accessory_id).where(
                    main.UserAccessory.user_id == user.id
                )
            )
        ).scalars()
    }
    stats["owned_accessories"] = len(owned_accessory_ids)
    if owned_accessory_ids:
        for profile in ("cn", "gl"):
            for row in accessory_master.raw_rows_for_profile(
                profile,
                "SELECT accessory_id, unit_id FROM accessory_special_m",
            ):
                if int(row["accessory_id"]) not in owned_accessory_ids:
                    continue
                before = len(sources.get(int(row["unit_id"]), ()))
                add(int(row["unit_id"]), profile)
                if profile != current_profile and len(sources[int(row["unit_id"])]) > before:
                    stats["owned_cross_profile_pairs"] += 1

    return sources, stats


async def _grant_special_accessory_test_units(
    context: idol.BasicSchoolIdolContext,
    user: main.User,
    target_count: int = 3,
) -> dict[str, object]:
    """Keep three usable copies of every relevant dedicated-accessory target.

    Unlike the previous catalogue-only implementation, this follows the active
    runtime mapping and mappings for every dedicated accessory already present
    in the shared account. The post-write verification is returned to the
    serial-code UI so a missing target can no longer be hidden behind a generic
    success message.
    """
    target_sources, source_stats = await _special_accessory_target_sources(
        context, user
    )
    target_unit_ids = set(target_sources)
    if not target_unit_ids:
        return {
            "created": 0,
            "targets": 0,
            "verified": 0,
            "missing": [],
            **source_stats,
        }

    deck_columns = [
        getattr(main.UnitDeck, f"unit_owning_user_id_{index}")
        for index in range(1, 10)
    ]
    deck_rows = (
        await context.db.main.execute(
            sqlalchemy.select(*deck_columns).where(main.UnitDeck.user_id == user.id)
        )
    ).all()
    deck_ids = {
        int(value) for row in deck_rows for value in row if int(value or 0) > 0
    }
    worn_ids = {
        int(value)
        for value in (
            await context.db.main.execute(
                sqlalchemy.select(main.UserAccessoryWear.unit_owning_user_id).where(
                    main.UserAccessoryWear.user_id == user.id
                )
            )
        ).scalars()
    }
    excluded_ids = deck_ids | worn_ids
    if int(user.center_unit_owning_user_id or 0) > 0:
        excluded_ids.add(int(user.center_unit_owning_user_id))

    rows = list(
        (
            await context.db.main.execute(
                sqlalchemy.select(main.Unit)
                .where(
                    main.Unit.user_id == user.id,
                    main.Unit.unit_id.in_(target_unit_ids),
                )
                .order_by(main.Unit.unit_id, main.Unit.id)
            )
        ).scalars()
    )
    by_unit: dict[int, list[main.Unit]] = {}
    for row in rows:
        by_unit.setdefault(int(row.unit_id), []).append(row)

    created = 0
    unresolved: list[str] = []
    for unit_id in sorted(target_unit_ids):
        copies = by_unit.get(unit_id, [])
        if not copies:
            template = None
            current_error: Exception | None = None
            try:
                template = await _create_maxed_profile_unit(context, user, unit_id)
            except Exception as exc:
                current_error = exc

            if template is None:
                for source_profile in sorted(target_sources[unit_id]):
                    try:
                        template = await _create_maxed_unit_from_bundled_profile(
                            context, user, unit_id, source_profile
                        )
                        break
                    except Exception:
                        continue

            if template is None:
                unresolved.append(
                    f"{unit_id}({type(current_error).__name__ if current_error else 'unresolved'})"
                )
                continue
            copies = [template]
            by_unit[unit_id] = copies
            created += 1
        else:
            template = copies[0]

        eligible = [
            row
            for row in copies
            if bool(row.active)
            and not bool(row.favorite_flag)
            and (row.id is None or int(row.id) not in excluded_ids)
        ]
        while len(eligible) < target_count:
            clone = main.Unit(
                user_id=user.id,
                unit_id=int(template.unit_id),
                active=True,
                favorite_flag=False,
                is_signed=False,
                exp=int(template.exp),
                skill_exp=int(template.skill_exp),
                max_level=int(template.max_level),
                love=int(template.love),
                rank=int(template.rank),
                display_rank=int(template.display_rank),
                level_limit_id=int(template.level_limit_id),
                unit_removable_skill_capacity=int(
                    template.unit_removable_skill_capacity
                ),
            )
            context.db.main.add(clone)
            eligible.append(clone)
            copies.append(clone)
            created += 1

    await context.db.main.flush()

    # Re-read persisted rows. This verifies the database state rather than the
    # in-memory list used while constructing new ORM objects.
    persisted = list(
        (
            await context.db.main.execute(
                sqlalchemy.select(
                    main.Unit.unit_id,
                    main.Unit.id,
                    main.Unit.active,
                    main.Unit.favorite_flag,
                ).where(
                    main.Unit.user_id == user.id,
                    main.Unit.unit_id.in_(target_unit_ids),
                )
            )
        ).all()
    )
    eligible_counts: dict[int, int] = {}
    for row in persisted:
        if (
            bool(row.active)
            and not bool(row.favorite_flag)
            and int(row.id) not in excluded_ids
        ):
            eligible_counts[int(row.unit_id)] = (
                eligible_counts.get(int(row.unit_id), 0) + 1
            )

    missing = [
        f"{unit_id}={eligible_counts.get(unit_id, 0)}/{target_count}"
        for unit_id in sorted(target_unit_ids)
        if eligible_counts.get(unit_id, 0) < target_count
    ]
    missing.extend(unresolved)
    return {
        "created": created,
        "targets": len(target_unit_ids),
        "verified": sum(
            eligible_counts.get(unit_id, 0) >= target_count
            for unit_id in target_unit_ids
        ),
        "missing": missing,
        **source_stats,
    }


async def _grant_accessory_catalogue(
    context: idol.BasicSchoolIdolContext,
    user: main.User,
    material_target: int,
) -> tuple[int, int, int, int]:
    """Grant one maxed copy of every accessory plus ample materials."""
    # Use only exact profile-specific client master rows. A catalogue-only ID
    # with a synthesized level-1 placeholder can appear in the Jewelry Box but
    # is filtered out by the member equipment screen's exact master rules.
    master_rows = await accessory_system._raw_accessory_rows(context)
    if not master_rows:
        return 0, 0, 0, 0

    max_exp_by_id: dict[int, int] = {}
    if await accessory_system._unit_db_table_exists(context, "accessory_level_m"):
        for row in await accessory_system._raw_rows(
            context,
            "SELECT accessory_id, MAX(COALESCE(next_exp, 0)) AS max_exp "
            "FROM accessory_level_m GROUP BY accessory_id",
        ):
            max_exp_by_id[int(row["accessory_id"])] = int(row["max_exp"] or 0)

    owned_rows = list(
        (
            await context.db.main.execute(
                sqlalchemy.select(main.UserAccessory)
                .where(main.UserAccessory.user_id == user.id)
                .order_by(main.UserAccessory.id)
            )
        ).scalars()
    )
    owned_by_id: dict[int, list[main.UserAccessory]] = {}
    for row in owned_rows:
        owned_by_id.setdefault(int(row.accessory_id), []).append(row)

    material_rows = list(
        (
            await context.db.main.execute(
                sqlalchemy.select(main.UserAccessoryMaterial).where(
                    main.UserAccessoryMaterial.user_id == user.id
                )
            )
        ).scalars()
    )
    materials_by_id = {int(row.accessory_id): row for row in material_rows}

    capacity, material_capacity = await accessory_system._capacities(context)
    current_count = len(owned_rows)
    created = 0
    maxed = 0
    materials = 0
    skipped_capacity = 0
    for master in master_rows:
        accessory_id = int(master["accessory_id"])
        if int(master.get("is_material") or 0) != 0:
            row = materials_by_id.get(accessory_id)
            target = min(int(material_target), int(material_capacity))
            if row is None:
                row = main.UserAccessoryMaterial(
                    user_id=user.id,
                    accessory_id=accessory_id,
                    amount=target,
                )
                context.db.main.add(row)
                materials_by_id[accessory_id] = row
            else:
                row.amount = max(int(row.amount), target)
            materials += 1
            continue

        rows = owned_by_id.get(accessory_id)
        max_exp = max_exp_by_id.get(accessory_id, 0)
        if not rows:
            if current_count >= int(capacity):
                # Do not corrupt client capacity semantics. A fresh test account
                # fits the complete catalogue; duplicate-heavy accounts may need
                # to sell duplicates before re-entering the code.
                skipped_capacity += 1
                continue
            owned = main.UserAccessory(
                user_id=user.id,
                accessory_id=accessory_id,
                exp=max_exp,
                rank_up_count=accessory_system.MAX_RANK_UP_COUNT,
                favorite_flag=False,
            )
            context.db.main.add(owned)
            owned_by_id[accessory_id] = [owned]
            current_count += 1
            created += 1
        else:
            for owned in rows:
                owned.exp = max(int(owned.exp), max_exp)
                owned.rank_up_count = max(
                    int(owned.rank_up_count), accessory_system.MAX_RANK_UP_COUNT
                )
            maxed += 1

    await context.db.main.flush()
    return created, maxed, materials, skipped_capacity


async def _grant_profile_cosmetics(
    context: idol.BasicSchoolIdolContext,
    user: main.User,
) -> tuple[int, int]:
    """Unlock every title and background present in the current profile."""
    catalogue = await client_catalogue.current(context)
    award_ids = set(catalogue.award_ids)
    background_ids = set(catalogue.background_ids)
    existing_awards = set(
        int(value)
        for value in (
            await context.db.main.execute(
                sqlalchemy.select(main.Award.award_id).where(main.Award.user_id == user.id)
            )
        ).scalars()
    )
    existing_backgrounds = set(
        int(value)
        for value in (
            await context.db.main.execute(
                sqlalchemy.select(main.Background.background_id).where(
                    main.Background.user_id == user.id
                )
            )
        ).scalars()
    )
    for award_id in sorted(award_ids - existing_awards):
        context.db.main.add(main.Award(user_id=user.id, award_id=award_id))
    for background_id in sorted(background_ids - existing_backgrounds):
        context.db.main.add(
            main.Background(user_id=user.id, background_id=background_id)
        )
    await context.db.main.flush()
    return len(award_ids - existing_awards), len(background_ids - existing_backgrounds)


async def give_comprehensive_test_resources(context: idol.BasicSchoolIdolContext, user: main.User, /):
    """Initialize a reusable, profile-aware test account.

    LOVEARROWSHOOT tops up stackable resources and also grants collectible
    content which cannot realistically be obtained quickly on an offline test
    server: one maxed copy of every card, one maxed copy of every accessory,
    all accessory materials, titles and backgrounds available to the current
    CN/GL profile. Re-entering it is idempotent and only adds missing catalogue
    entries or restores values below the targets.
    """
    currency_target = 99_999_999
    loveca_target = 99_999
    item_target = 9_999
    sis_target = 99
    supporter_target = 100
    lp_target = 9_999

    user.game_coin = max(user.game_coin, currency_target)
    user.social_point = max(user.social_point, currency_target)
    user.free_sns_coin = max(user.free_sns_coin, loveca_target)
    user.paid_sns_coin = max(user.paid_sns_coin, loveca_target)
    user.unit_max = max(user.unit_max, 10_000)
    user.waiting_unit_max = max(user.waiting_unit_max, 10_000)
    user.friend_max = max(user.friend_max, 1_000)
    user.training_energy_max = max(user.training_energy_max, 99)
    user.training_energy = max(user.training_energy, user.training_energy_max)
    current_lp = user_system.get_current_energy(user)
    if current_lp < lp_target:
        user_system.add_energy(user, lp_target - current_lp)

    counts = {
        "items": 0,
        "recovery": 0,
        "stickers": 0,
        "sis": 0,
        "supporters": 0,
        "cards_created": 0,
        "cards_maxed": 0,
        "costumes": 0,
        "special_test_cards": 0,
        "accessories_created": 0,
        "accessories_maxed": 0,
        "accessory_materials": 0,
        "accessories_skipped_capacity": 0,
        "titles": 0,
        "backgrounds": 0,
        "exclusive_scouting_tickets": 0,
    }
    errors: list[str] = []

    try:
        # Use the exact supplied client item catalogue, not only the active
        # reconstructed server item DB. This guarantees ordinary scouting
        # tickets (1), blue scouting coupons (5), SR+ tickets (6), Scout 11
        # coupons/tickets (7/8), and every other client-recognized item are
        # restored to a large test quantity. IDs 2/3/4 are currency aliases in
        # NPPS4 (Friend Pts, G and Love Gems) and were topped up above instead.
        item_ids: set[int] = set((await client_catalogue.current(context)).item_ids)
        item_ids.update({1, 5})
        for secretbox_data in data.get().secretbox_data.values():
            if secretbox_data.profiles is not None and context.profile.value not in secretbox_data.profiles:
                continue
            for button in secretbox_data.buttons:
                for cost in button.costs:
                    if (
                        cost.cost_type == const.SECRETBOX_COST_TYPE.ITEM_TICKET
                        and cost.cost_item_id is not None
                    ):
                        item_ids.add(int(cost.cost_item_id))
        for shop_row in data.get().sticker_shop:
            if (
                shop_row.add_type == const.ADD_TYPE.ITEM
                and (shop_row.profiles is None or context.profile.value in shop_row.profiles)
            ):
                item_ids.add(int(shop_row.item_id))

        for item_id in sorted(item_ids - {2, 3, 4}):
            current = await item.get_item_count(context, user, item_id)
            if current < item_target:
                await item.add_item(context, user, item_id, item_target - current)
            counts["items"] += 1
        exclusive_ticket_catalogue = await scouting_ticket_catalogue.current(context)
        # All of these IDs are already included in the exact client item set
        # above.  Keep the count in the result so an administrator can see that
        # region-specific ticket resources were actually restored, while not
        # claiming that their missing historical server-side pools were
        # reconstructed from item names alone.
        counts["exclusive_scouting_tickets"] = len(
            exclusive_ticket_catalogue.item_ids & item_ids
        )
    except Exception as exc:
        errors.append(f"items: {type(exc).__name__}: {exc}")

    try:
        # Top up every LP-recovery object which the currently connected client
        # can actually render and consume. CN's generated item Master contains
        # the 52 honoka/client rows; GL uses its own active Master catalogue.
        recovery_ids = sorted(
            await item.get_supported_recovery_item_ids(
                context, context.profile.value
            )
        )
        for item_id in recovery_ids:
            current_obj = await item.get_recovery_item_data(context, user, item_id)
            current = 0 if current_obj is None else int(current_obj.amount)
            if current < item_target:
                await item.add_recovery_item(context, user, item_id, item_target - current)
            counts["recovery"] += 1
        await context.db.main.flush()
        verified = {
            int(row.item_id): int(row.amount)
            for row in (
                await context.db.main.execute(
                    sqlalchemy.select(main.RecoveryItem).where(
                        main.RecoveryItem.user_id == user.id,
                        main.RecoveryItem.item_id.in_(recovery_ids),
                    )
                )
            ).scalars()
        }
        missing = [
            item_id for item_id in recovery_ids
            if verified.get(item_id, 0) < item_target
        ]
        if missing:
            raise RuntimeError(f"LP recovery top-up verification failed: {missing}")
    except Exception as exc:
        errors.append(f"recovery: {type(exc).__name__}: {exc}")

    try:
        result = await context.db.exchange.execute(sqlalchemy.select(exchange_db.ExchangePoint.exchange_point_id))
        for point_id in result.scalars():
            point_id = int(point_id)
            current = await exchange.get_exchange_point_amount(context, user, point_id)
            if current < item_target:
                await exchange.add_exchange_point(context, user, point_id, item_target - current)
            counts["stickers"] += 1
    except Exception as exc:
        errors.append(f"stickers: {type(exc).__name__}: {exc}")

    try:
        result = await context.db.unit.execute(sqlalchemy.select(unit_db.RemovableSkill.unit_removable_skill_id))
        for skill_id in result.scalars():
            skill_id = int(skill_id)
            current_obj = await unit.get_removable_skill_info(context, user, skill_id)
            current = 0 if current_obj is None else int(current_obj.amount)
            if current < sis_target:
                await unit.add_unit_removable_skill(context, user, skill_id, sis_target - current)
            counts["sis"] += 1
    except Exception as exc:
        errors.append(f"sis: {type(exc).__name__}: {exc}")

    try:
        result = await context.db.unit.execute(
            sqlalchemy.select(unit.unit.Unit.unit_id).where(
                unit.unit.Unit.disable_rank_up > 0,
                unit.unit.Unit.disable_rank_up < 5,
            )
        )
        for unit_id in result.scalars():
            unit_id = int(unit_id)
            current_obj = await unit.get_supporter_unit(context, user, unit_id)
            current = 0 if current_obj is None else int(current_obj.amount)
            if current < supporter_target:
                await unit.add_supporter_unit(context, user, unit_id, supporter_target - current)
            counts["supporters"] += 1
    except Exception as exc:
        errors.append(f"supporters: {type(exc).__name__}: {exc}")

    try:
        (
            counts["cards_created"],
            counts["cards_maxed"],
            counts["costumes"],
        ) = await _grant_collectible_units(context, user)
    except Exception as exc:
        errors.append(f"cards/costumes: {type(exc).__name__}: {exc}")

    try:
        special_card_result = await _grant_special_accessory_test_units(
            context, user, target_count=3
        )
        counts["special_test_cards"] = int(special_card_result["created"])
        counts["special_targets"] = int(special_card_result["targets"])
        counts["special_targets_verified"] = int(special_card_result["verified"])
        counts["special_runtime_pairs"] = int(special_card_result["runtime_pairs"])
        counts["special_owned_cross_pairs"] = int(
            special_card_result["owned_cross_profile_pairs"]
        )
        special_missing = list(special_card_result["missing"])
        if special_missing:
            errors.append(
                "special target verification: "
                + ", ".join(special_missing[:24])
                + (f" (+{len(special_missing) - 24} more)" if len(special_missing) > 24 else "")
            )
    except Exception as exc:
        errors.append(f"special accessory test cards: {type(exc).__name__}: {exc}")

    try:
        (
            counts["accessories_created"],
            counts["accessories_maxed"],
            counts["accessory_materials"],
            counts["accessories_skipped_capacity"],
        ) = await _grant_accessory_catalogue(context, user, item_target)
        if counts["accessories_skipped_capacity"]:
            errors.append(
                f"accessory capacity: {counts['accessories_skipped_capacity']} missing types were not added; sell duplicates and enter the code again"
            )
    except Exception as exc:
        errors.append(f"accessories: {type(exc).__name__}: {exc}")

    try:
        counts["titles"], counts["backgrounds"] = await _grant_profile_cosmetics(
            context, user
        )
    except Exception as exc:
        errors.append(f"titles/backgrounds: {type(exc).__name__}: {exc}")

    await context.db.main.flush()
    return (
        f"LOVEARROWSHOOT {getattr(context.profile, 'value', str(context.profile)).upper()} test account restored: "
        f"{counts['cards_created']} cards added ({counts['cards_maxed']} existing catalogue entries maxed), "
        f"{counts['costumes']} costume-only looks registered, "
        f"{counts['special_test_cards']} extra dedicated-accessory test cards added "
        f"({counts.get('special_targets_verified', 0)}/{counts.get('special_targets', 0)} targets verified; "
        f"runtime mappings={counts.get('special_runtime_pairs', 0)}, "
        f"owned cross-profile mappings={counts.get('special_owned_cross_pairs', 0)}), "
        f"{counts['accessories_created']} accessories added ({counts['accessories_maxed']} existing types maxed), "
        f"{counts['accessory_materials']} accessory materials, "
        f"{counts['titles']} titles and {counts['backgrounds']} backgrounds unlocked; "
        f"{counts['items']} items, {counts['recovery']} LP items, "
        f"{counts['stickers']} sticker currencies, {counts['sis']} SIS, "
        f"{counts['supporters']} supporter members topped up; "
        f"{counts['exclusive_scouting_tickets']} profile-exclusive scouting-ticket items audited and restored."
        + (" Warnings: " + " | ".join(errors) if errors else "")
    )
