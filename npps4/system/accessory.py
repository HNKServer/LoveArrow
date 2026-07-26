from __future__ import annotations

import dataclasses
import datetime
import importlib.resources as resources
import json
from typing import Any

import sqlalchemy

from . import accessory_model
from . import accessory_master
from . import client_catalogue
from . import unit as unit_system
from . import profile_projection
from .. import idol
from .. import util
from ..db import main


MAX_RANK_UP_COUNT = 4


@dataclasses.dataclass(frozen=True)
class AccessoryLevelState:
    level: int
    max_level: int
    rank_up_count: int
    next_exp: int
    rest_exp: int
    row: dict[str, Any]


@dataclasses.dataclass(frozen=True)
class AccessoryCreateResult:
    created: main.UserAccessory
    use_game_coin: int
    reward_box_flag: bool = False


@dataclasses.dataclass(frozen=True)
class AccessoryBulkCreateResult:
    created: list[main.UserAccessory]
    use_game_coin: int
    reward_box_flags: list[bool]

    @property
    def reward_box_flag(self) -> bool:
        return any(self.reward_box_flags)


@dataclasses.dataclass(frozen=True)
class AccessoryMergeResult:
    before: accessory_model.AccessoryListInfo
    after: accessory_model.AccessoryListInfo
    use_game_coin: int
    gain_exp: int
    rank_up_count_after: int
    is_enough: bool
    rest_exp: int


@dataclasses.dataclass(frozen=True)
class AccessorySaleResult:
    total: int
    reward_box_flag: bool


async def _unit_db_table_exists(context: idol.BasicSchoolIdolContext, table: str) -> bool:
    return await accessory_master.table_exists(context, table)


async def _raw_rows(
    context: idol.BasicSchoolIdolContext,
    sql: str,
    params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    return await accessory_master.raw_rows(context, sql, params)


async def _raw_accessory_rows(context: idol.BasicSchoolIdolContext, *, materials: bool | None = None) -> list[dict]:
    return await accessory_master.accessory_rows(context, materials=materials)


async def accessory_master_by_id(context: idol.BasicSchoolIdolContext, accessory_id: int) -> dict | None:
    # Never synthesize a dummy master for an ID which merely exists in the
    # capability catalogue. The equipment screen applies exact master effects,
    # levels and special-target rules; a placeholder can be visible in the
    # Jewelry Box while being unusable in the member equipment selector.
    return await accessory_master.accessory_by_id(context, accessory_id)


async def _level_rows(context: idol.BasicSchoolIdolContext, accessory_id: int) -> list[dict[str, Any]]:
    return await accessory_master.level_rows(context, accessory_id)


async def _level_state(context: idol.BasicSchoolIdolContext, owned: main.UserAccessory) -> AccessoryLevelState:
    master = await accessory_master_by_id(context, owned.accessory_id)
    rows = await _level_rows(context, owned.accessory_id)
    if master is None or not rows:
        row = {"level": 1, "next_exp": 0, "smile_diff": 0, "pure_diff": 0, "cool_diff": 0,
               "grant_exp": 0, "merge_cost": 0, "sale_price": 0}
        return AccessoryLevelState(1, 1, max(int(getattr(owned, "rank_up_count", 0)), 0), 0, 0, row)

    default_max = max(int(master.get("default_max_level") or 1), 1)
    absolute_max = max(int(master.get("max_level") or default_max), default_max)
    rank_count = max(min(int(getattr(owned, "rank_up_count", 0)), MAX_RANK_UP_COUNT, absolute_max - default_max), 0)
    current_max = min(default_max + rank_count, absolute_max)

    # accessory_level_m.next_exp is the cumulative threshold needed to leave
    # that row's level.  For example, level 3's threshold is the EXP needed to
    # reach level 4.  The CN and GL clients use the same rule in
    # common/model/accessory.lua:getExpInfo/getPreview.
    row_by_level = {int(row["level"]): row for row in rows}
    level = 1
    for row in rows:
        row_level = int(row["level"])
        if row_level >= current_max:
            break
        threshold = int(row.get("next_exp") or 0)
        if threshold <= 0 or owned.exp < threshold:
            break
        level = min(row_level + 1, current_max)

    current_row = row_by_level.get(level, rows[0])
    if level >= current_max:
        next_exp = 0
        cap_threshold = 0 if current_max <= 1 else int(row_by_level.get(current_max - 1, {}).get("next_exp") or 0)
        # Preserve EXP gained while capped.  After a remake raises max_level,
        # this overflow immediately contributes to the newly available level.
        rest_exp = max(int(owned.exp) - cap_threshold, 0) if cap_threshold > 0 else max(int(owned.exp), 0)
    else:
        next_exp = int(current_row.get("next_exp") or 0)
        rest_exp = 0

    return AccessoryLevelState(level, current_max, rank_count, next_exp, rest_exp, current_row)


async def to_api_info(
    context: idol.BasicSchoolIdolContext, owned: main.UserAccessory
) -> accessory_model.AccessoryListInfo:
    state = await _level_state(context, owned)
    return accessory_model.AccessoryListInfo(
        accessory_owning_user_id=owned.id,
        accessory_id=owned.accessory_id,
        exp=owned.exp,
        next_exp=state.next_exp,
        level=state.level,
        max_level=state.max_level,
        rank_up_count=state.rank_up_count,
        favorite_flag=owned.favorite_flag,
    )


async def _capacities(context: idol.BasicSchoolIdolContext) -> tuple[int, int]:
    rows = await _raw_rows(
        context,
        "SELECT owning_capacity, owning_material_capacity FROM accessory_base_setting_m "
        "ORDER BY accessory_base_setting_id LIMIT 1",
    )
    if not rows:
        return 999, 999999999
    return int(rows[0]["owning_capacity"]), int(rows[0]["owning_material_capacity"])


async def add_accessory(
    context: idol.BasicSchoolIdolContext,
    user: main.User,
    accessory_id: int,
    amount: int = 1,
    *,
    exp: int = 0,
    rank_up_count: int = 0,
) -> list[main.UserAccessory]:
    if amount < 1:
        raise ValueError("amount must be positive")
    master = await accessory_master_by_id(context, accessory_id)
    if master is None:
        raise idol.error.IdolError(detail="invalid accessory id")
    if int(master.get("is_material") or 0) != 0:
        await add_accessory_material(context, user, accessory_id, amount)
        return []

    capacity, _ = await _capacities(context)
    count = int(
        (await context.db.main.execute(
            sqlalchemy.select(sqlalchemy.func.count(main.UserAccessory.id)).where(main.UserAccessory.user_id == user.id)
        )).scalar_one()
    )
    if count + amount > capacity:
        raise idol.error.IdolError(detail="accessory capacity exceeded")

    created: list[main.UserAccessory] = []
    for _ in range(amount):
        item = main.UserAccessory(
            user_id=user.id,
            accessory_id=accessory_id,
            exp=max(int(exp), 0),
            rank_up_count=max(int(rank_up_count), 0),
            favorite_flag=False,
        )
        context.db.main.add(item)
        created.append(item)
    await context.db.main.flush()
    return created


async def add_accessory_material(context: idol.BasicSchoolIdolContext, user: main.User, accessory_id: int, amount: int) -> bool:
    if amount < 1:
        raise ValueError("amount must be positive")
    master = await accessory_master_by_id(context, accessory_id)
    if master is None or int(master.get("is_material") or 0) == 0:
        raise idol.error.IdolError(detail="invalid accessory material")
    _, capacity = await _capacities(context)
    q = sqlalchemy.select(main.UserAccessoryMaterial).where(
        main.UserAccessoryMaterial.user_id == user.id,
        main.UserAccessoryMaterial.accessory_id == accessory_id,
    )
    row = (await context.db.main.execute(q)).scalar()
    if row is None:
        row = main.UserAccessoryMaterial(user_id=user.id, accessory_id=accessory_id, amount=0)
        context.db.main.add(row)
    if row.amount + amount > capacity:
        raise idol.error.IdolError(detail="accessory material capacity exceeded")
    row.amount += amount
    await context.db.main.flush()
    return True


async def _deck_unit_ids(context: idol.BasicSchoolIdolContext, user: main.User) -> set[int]:
    columns = [getattr(main.UnitDeck, f"unit_owning_user_id_{index}") for index in range(1, 10)]
    rows = (
        await context.db.main.execute(
            sqlalchemy.select(*columns).where(main.UnitDeck.user_id == user.id)
        )
    ).all()
    return {int(value) for row in rows for value in row if int(value or 0) > 0}


async def _worn_unit_ids(context: idol.BasicSchoolIdolContext, user: main.User) -> set[int]:
    return {
        int(value)
        for value in (
            await context.db.main.execute(
                sqlalchemy.select(main.UserAccessoryWear.unit_owning_user_id).where(
                    main.UserAccessoryWear.user_id == user.id
                )
            )
        ).scalars()
    }


async def _special_target_unit_id(
    context: idol.BasicSchoolIdolContext, accessory_id: int
) -> int | None:
    return await accessory_master.special_target(context, accessory_id)


async def _validate_special_wear_target(
    context: idol.BasicSchoolIdolContext,
    owned_accessory: main.UserAccessory,
    owned_unit: main.Unit,
) -> None:
    """Mirror the client restriction for dedicated accessories.

    Before the accessory reaches its absolute remake cap it is limited to the
    exact card in accessory_special_m. At the absolute cap, the client permits
    other cards of the same character (unit_type_id). Ordinary accessories have
    no entry and are unaffected.
    """
    target_unit_id = await _special_target_unit_id(context, int(owned_accessory.accessory_id))
    if target_unit_id is None or int(owned_unit.unit_id) == target_unit_id:
        return

    master = await accessory_master_by_id(context, int(owned_accessory.accessory_id))
    if master is not None:
        default_max = max(int(master.get("default_max_level") or 1), 1)
        absolute_max = max(int(master.get("max_level") or default_max), default_max)
        state = await _level_state(context, owned_accessory)
        # CN and GL Lua compare the owned accessory's current *level* with the
        # master absolute max_level. Unlocking the cap alone is insufficient.
        if state.level >= absolute_max:
            target_info = await unit_system.get_unit_info(context, target_unit_id)
            candidate_info = await unit_system.get_unit_info(context, int(owned_unit.unit_id))
            if (
                target_info is not None
                and candidate_info is not None
                and int(target_info.unit_type_id) == int(candidate_info.unit_type_id)
            ):
                return

    raise idol.error.IdolError(detail="this dedicated accessory cannot be worn by the selected member")


async def _has_special_creation_candidate(context: idol.BasicSchoolIdolContext, user: main.User) -> bool:
    target_unit_ids = set((await client_catalogue.current(context)).special_target_unit_ids)
    if not target_unit_ids:
        return False

    excluded = await _deck_unit_ids(context, user) | await _worn_unit_ids(context, user)
    if int(user.center_unit_owning_user_id or 0) > 0:
        excluded.add(int(user.center_unit_owning_user_id))
    rows = (
        await context.db.main.execute(
            sqlalchemy.select(
                main.Unit.unit_id, main.Unit.id, main.Unit.active, main.Unit.favorite_flag
            ).where(main.Unit.user_id == user.id, main.Unit.unit_id.in_(target_unit_ids))
        )
    ).all()
    eligible_by_unit: dict[int, int] = {}
    for row in rows:
        if bool(row.active) and not bool(row.favorite_flag) and int(row.id) not in excluded:
            unit_id = int(row.unit_id)
            eligible_by_unit[unit_id] = eligible_by_unit.get(unit_id, 0) + 1
    return any(amount >= 2 for amount in eligible_by_unit.values())


async def get_accessory_all_info(
    context: idol.BasicSchoolIdolContext, user: main.User
) -> accessory_model.AccessoryAllInfo:
    q = sqlalchemy.select(main.UserAccessory).where(main.UserAccessory.user_id == user.id).order_by(
        main.UserAccessory.accessory_id, main.UserAccessory.id
    )
    result = await context.db.main.execute(q)
    visible_accessories: dict[int, main.UserAccessory] = {}
    accessory_list: list[accessory_model.AccessoryListInfo] = []
    for row in result.scalars():
        master = await accessory_master_by_id(context, row.accessory_id)
        if master is None or int(master.get("is_material") or 0) != 0:
            continue
        visible_accessories[row.id] = row
        accessory_list.append(await to_api_info(context, row))

    q = sqlalchemy.select(main.UserAccessoryWear).where(main.UserAccessoryWear.user_id == user.id).order_by(
        main.UserAccessoryWear.unit_owning_user_id
    )
    result = await context.db.main.execute(q)
    wearing_info: list[accessory_model.AccessoryWearInfo] = []
    for row in result.scalars():
        if row.accessory_owning_user_id not in visible_accessories:
            continue
        owned_unit = await unit_system.get_unit(context, row.unit_owning_user_id)
        if owned_unit is None or not await profile_projection.unit_supported(context, owned_unit.unit_id):
            continue
        wearing_info.append(
            accessory_model.AccessoryWearInfo(
                unit_owning_user_id=row.unit_owning_user_id,
                accessory_owning_user_id=row.accessory_owning_user_id,
            )
        )
    return accessory_model.AccessoryAllInfo(
        accessory_list=accessory_list,
        wearing_info=wearing_info,
        especial_create_flag=await _has_special_creation_candidate(context, user),
    )


async def get_accessory_material_all_info(
    context: idol.BasicSchoolIdolContext, user: main.User
) -> accessory_model.AccessoryMaterialAllInfo:
    q = sqlalchemy.select(main.UserAccessoryMaterial).where(main.UserAccessoryMaterial.user_id == user.id).order_by(
        main.UserAccessoryMaterial.accessory_id
    )
    result = await context.db.main.execute(q)
    visible: list[accessory_model.AccessoryMaterialInfo] = []
    for row in result.scalars():
        if row.amount <= 0:
            continue
        master = await accessory_master_by_id(context, row.accessory_id)
        if master is None or int(master.get("is_material") or 0) == 0:
            continue
        visible.append(accessory_model.AccessoryMaterialInfo(accessory_id=row.accessory_id, amount=row.amount))
    return accessory_model.AccessoryMaterialAllInfo(accessory_material_list=visible)


# This is a client-resource contract, not a master-data sequence.  In the
# supplied final CN/GL clients the list image numbers are intentionally
# non-contiguous across Nijigasaki and Liella.  Generating them arithmetically
# shifts Liella members into Nijigasaki, omits unit_type_id 214, advertises
# nonexistent list_40..list_48 assets, and makes the Liella Jewelry Box tab
# crash in Lua.  Keep the exact table bundled with the server so Android does
# not depend on its current working directory.
_EXPECTED_ACCESSORY_TAB_IDS = (
    tuple(range(1, 10)),
    tuple(range(101, 110)),
    (201, 202, 203, 204, 205, 206, 207, 208, 209, 212, 213, 214),
    tuple(range(301, 310)),
)
_EXPECTED_ACCESSORY_TAB_ASSET_NUMBERS = (
    tuple(range(1, 10)),
    tuple(range(10, 19)),
    tuple(range(24, 36)),
    (19, 20, 21, 22, 23, 36, 37, 38, 39),
)


def _load_accessory_tab_contract() -> accessory_model.AccessoryTabListInfo:
    raw = resources.files("npps4.assets.accessory").joinpath("accessory_tab_list.json").read_text(encoding="utf-8")
    info = accessory_model.AccessoryTabListInfo.model_validate({"tab_list": json.loads(raw)})
    if len(info.tab_list) != 4:
        raise RuntimeError("accessory tab contract must contain exactly four groups")

    seen_units: set[int] = set()
    seen_assets: set[str] = set()
    for index, tab in enumerate(info.tab_list):
        unit_ids = tuple(item.unit_type_id for item in tab.asset_list)
        asset_paths = tuple(item.asset_path for item in tab.asset_list)
        expected_assets = tuple(
            f"assets/image/accessory/list/list_{number}.png"
            for number in _EXPECTED_ACCESSORY_TAB_ASSET_NUMBERS[index]
        )
        if unit_ids != _EXPECTED_ACCESSORY_TAB_IDS[index] or asset_paths != expected_assets:
            raise RuntimeError(f"invalid accessory tab contract at index {index}")
        if seen_units.intersection(unit_ids) or seen_assets.intersection(asset_paths):
            raise RuntimeError("accessory tab contract contains duplicate unit or asset entries")
        seen_units.update(unit_ids)
        seen_assets.update(asset_paths)
    return info


async def get_accessory_tab_info(context: idol.BasicSchoolIdolContext) -> accessory_model.AccessoryTabListInfo:
    # ``context`` remains part of the public system API because future client
    # families may require a separate contract.  The supplied CN and GL builds
    # use the same exact four-tab mapping.
    del context
    return _load_accessory_tab_contract()


async def get_user_accessory(
    context: idol.BasicSchoolIdolContext, user: main.User, accessory_owning_user_id: int
) -> main.UserAccessory:
    item = await context.db.main.get(main.UserAccessory, accessory_owning_user_id)
    if item is None or item.user_id != user.id:
        raise idol.error.IdolError(detail="accessory not found")
    return item


async def _is_worn(context: idol.BasicSchoolIdolContext, user: main.User, owned_id: int) -> bool:
    q = sqlalchemy.select(main.UserAccessoryWear.id).where(
        main.UserAccessoryWear.user_id == user.id,
        main.UserAccessoryWear.accessory_owning_user_id == owned_id,
    ).limit(1)
    return (await context.db.main.execute(q)).scalar() is not None


async def _validate_disposable_accessory(
    context: idol.BasicSchoolIdolContext, user: main.User, owned: main.UserAccessory
) -> None:
    if owned.favorite_flag:
        raise idol.error.IdolError(detail="favorite accessory cannot be consumed")
    if await _is_worn(context, user, owned.id):
        raise idol.error.IdolError(detail="equipped accessory cannot be consumed")


async def _remove_accessory(context: idol.BasicSchoolIdolContext, user: main.User, owned: main.UserAccessory) -> None:
    await context.db.main.execute(
        sqlalchemy.delete(main.UserAccessoryWear).where(
            main.UserAccessoryWear.user_id == user.id,
            main.UserAccessoryWear.accessory_owning_user_id == owned.id,
        )
    )
    await context.db.main.delete(owned)


async def _material_row(
    context: idol.BasicSchoolIdolContext, user: main.User, accessory_id: int
) -> main.UserAccessoryMaterial:
    q = sqlalchemy.select(main.UserAccessoryMaterial).where(
        main.UserAccessoryMaterial.user_id == user.id,
        main.UserAccessoryMaterial.accessory_id == accessory_id,
    )
    row = (await context.db.main.execute(q)).scalar()
    if row is None:
        raise idol.error.IdolError(detail="accessory material not found")
    return row


async def _consume_material(
    context: idol.BasicSchoolIdolContext, user: main.User, accessory_id: int, amount: int
) -> None:
    if amount <= 0:
        raise idol.error.IdolError(detail="invalid accessory material amount")
    row = await _material_row(context, user, accessory_id)
    if row.amount < amount:
        raise idol.error.IdolError(detail="not enough accessory material")
    row.amount -= amount
    if row.amount == 0:
        await context.db.main.delete(row)


async def wear_accessories(
    context: idol.BasicSchoolIdolContext,
    user: main.User,
    wear: list[tuple[int, int]],
    remove: list[tuple[int, int]],
) -> None:
    for accessory_owning_user_id, unit_owning_user_id in remove:
        await context.db.main.execute(
            sqlalchemy.delete(main.UserAccessoryWear).where(
                main.UserAccessoryWear.user_id == user.id,
                main.UserAccessoryWear.accessory_owning_user_id == accessory_owning_user_id,
                main.UserAccessoryWear.unit_owning_user_id == unit_owning_user_id,
            )
        )

    for accessory_owning_user_id, unit_owning_user_id in wear:
        owned_accessory = await get_user_accessory(context, user, accessory_owning_user_id)
        unit_data = await unit_system.get_unit(context, unit_owning_user_id)
        unit_system.validate_unit(user, unit_data)
        if not unit_data.active:
            raise idol.error.IdolError(detail="cannot wear accessory on inactive unit")
        await _validate_special_wear_target(context, owned_accessory, unit_data)
        await context.db.main.execute(
            sqlalchemy.delete(main.UserAccessoryWear).where(
                main.UserAccessoryWear.user_id == user.id,
                sqlalchemy.or_(
                    main.UserAccessoryWear.accessory_owning_user_id == accessory_owning_user_id,
                    main.UserAccessoryWear.unit_owning_user_id == unit_owning_user_id,
                ),
            )
        )
        context.db.main.add(
            main.UserAccessoryWear(
                user_id=user.id,
                unit_owning_user_id=unit_owning_user_id,
                accessory_owning_user_id=accessory_owning_user_id,
            )
        )
    await context.db.main.flush()


async def set_favorite(context: idol.BasicSchoolIdolContext, user: main.User, accessory_owning_user_id: int, flag: bool) -> None:
    item = await get_user_accessory(context, user, accessory_owning_user_id)
    item.favorite_flag = flag
    await context.db.main.flush()


async def _lottery_cost_for_value(context: idol.BasicSchoolIdolContext, status_type: int, value: int) -> int:
    rows = await _raw_rows(
        context,
        "SELECT cost_value FROM accessory_lottery_cost_m "
        "WHERE status_type=:type AND from_value<=:value AND to_value>=:value "
        "ORDER BY accessory_lottery_cost_id LIMIT 1",
        {"type": status_type, "value": value},
    )
    if not rows:
        raise idol.error.IdolError(detail=f"accessory lottery cost is undefined for type={status_type}, value={value}")
    return int(rows[0]["cost_value"])


async def _special_accessory_for_unit(context: idol.BasicSchoolIdolContext, unit_id: int) -> int | None:
    return await accessory_master.special_accessory_for_unit(context, unit_id)


async def _lottery_accessory(context: idol.BasicSchoolIdolContext, cost: int) -> int:
    groups = await _raw_rows(
        context,
        "SELECT accessory_lottery_group_id FROM accessory_lottery_group_m "
        "WHERE from_cost<=:cost AND to_cost>=:cost ORDER BY accessory_lottery_group_id LIMIT 1",
        {"cost": cost},
    )
    if not groups:
        raise idol.error.IdolError(detail="accessory lottery group not found")
    group_id = int(groups[0]["accessory_lottery_group_id"])
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    candidates = await _raw_rows(
        context,
        "SELECT accessory_id, weight FROM accessory_lottery_list_m "
        "WHERE accessory_lottery_group_id=:group_id "
        "AND (start_date IS NULL OR start_date='' OR start_date<=:now) "
        "AND (end_date IS NULL OR end_date='' OR end_date>=:now) "
        "ORDER BY accessory_lottery_list_id",
        {"group_id": group_id, "now": now},
    )
    if not candidates:
        raise idol.error.IdolError(detail="accessory lottery list is empty")
    valid_candidates: list[dict[str, Any]] = []
    valid_weights: list[int] = []
    for candidate in candidates:
        candidate_id = int(candidate["accessory_id"])
        master = await accessory_master_by_id(context, candidate_id)
        weight = max(int(candidate["weight"]), 0)
        if master is None or int(master.get("is_material") or 0) != 0 or weight <= 0:
            continue
        valid_candidates.append(candidate)
        valid_weights.append(weight)
    if not valid_candidates:
        raise idol.error.IdolError(detail="accessory lottery has no usable client-master candidate")
    chosen = util.SYSRAND.choices(valid_candidates, weights=valid_weights, k=1)[0]
    return int(chosen["accessory_id"])


async def create_from_units(
    context: idol.SchoolIdolParams, user: main.User, unit_owning_user_ids: list[int]
) -> AccessoryCreateResult:
    ids = list(dict.fromkeys(int(x) for x in unit_owning_user_ids))
    # Both normal make and dedicated make consume two members.  A dedicated
    # accessory additionally requires two copies of the exact same mapped UR.
    if len(ids) != 2 or len(ids) != len(unit_owning_user_ids):
        raise idol.error.IdolError(detail="accessory creation requires exactly two distinct owned cards")

    units: list[main.Unit] = []
    full_infos = []
    game_coin_cost = 0
    lottery_cost = 0
    deck_ids = await _deck_unit_ids(context, user)
    worn_ids = await _worn_unit_ids(context, user)
    for owning_id in ids:
        unit_data = await unit_system.get_unit(context, owning_id)
        unit_system.validate_unit(user, unit_data)
        if not unit_data.active:
            raise idol.error.IdolError(detail="inactive unit cannot be used for accessory creation")
        if unit_data.favorite_flag:
            raise idol.error.IdolError(detail="favorite unit cannot be used for accessory creation")
        if unit_data.id == user.center_unit_owning_user_id:
            raise idol.error.IdolError(detail="partner unit cannot be used for accessory creation")
        if int(unit_data.id) in deck_ids:
            raise idol.error.IdolError(detail="deck unit cannot be used for accessory creation")
        if int(unit_data.id) in worn_ids:
            raise idol.error.IdolError(detail="unit wearing an accessory cannot be consumed")
        full, stats = await unit_system.get_unit_data_full_info(context, unit_data)
        unit_info = await unit_system.get_unit_info(context, unit_data.unit_id)
        if unit_info is None:
            raise idol.error.IdolError(detail="unit master not found")
        lottery_cost += await _lottery_cost_for_value(context, 1, int(unit_info.rarity))
        lottery_cost += await _lottery_cost_for_value(context, 2, int(full.level))
        lottery_cost += await _lottery_cost_for_value(context, 3, int(full.unit_skill_level))
        game_coin_cost += int(stats.merge_cost)
        units.append(unit_data)
        full_infos.append(full)

    if game_coin_cost > user.game_coin:
        raise idol.error.IdolError(detail="not enough game coin")

    accessory_id = None
    if int(units[0].unit_id) == int(units[1].unit_id):
        mapped = await _special_accessory_for_unit(context, units[0].unit_id)
        if mapped is not None:
            # accessory_special_m only maps the official dedicated UR source.
            # Validate rarity as defense against a malformed/foreign master.
            unit_info = await unit_system.get_unit_info(context, units[0].unit_id)
            if unit_info is None or int(unit_info.rarity) != 4:
                raise idol.error.IdolError(detail="dedicated accessory source must be the mapped UR card")
            accessory_id = mapped
    if accessory_id is None:
        accessory_id = await _lottery_accessory(context, lottery_cost)

    # Validate capacity and result before consuming cards.
    created = await add_accessory(context, user, accessory_id, 1)
    if not created:
        raise idol.error.IdolError(detail="lottery returned an accessory material")

    for unit_data in units:
        await unit_system.remove_unit(context, user, unit_data)
    user.game_coin -= game_coin_cost
    await context.db.main.flush()
    return AccessoryCreateResult(created=created[0], use_game_coin=game_coin_cost)


async def create_from_unit_groups(
    context: idol.SchoolIdolParams,
    user: main.User,
    unit_owning_user_id_groups: list[list[int]],
) -> AccessoryBulkCreateResult:
    """Create one accessory for each GL auto-create candidate group.

    GL's ``AccessoryModel.bulkCreate`` deliberately sends a nested list to the
    same ``unit/createAccessory`` endpoint.  Each inner list is one ordinary or
    special creation transaction.  The surrounding request context commits
    only after this function returns, so any invalid later group rolls back all
    earlier creations, card removals and coin deductions.
    """
    if not unit_owning_user_id_groups:
        raise idol.error.IdolError(detail="empty accessory creation group list")

    normalized_groups: list[list[int]] = []
    all_ids: list[int] = []
    for group in unit_owning_user_id_groups:
        normalized = [int(value) for value in group]
        if not normalized:
            raise idol.error.IdolError(detail="empty unit group for accessory creation")
        normalized_groups.append(normalized)
        all_ids.extend(normalized)
    if len(set(all_ids)) != len(all_ids):
        raise idol.error.IdolError(detail="a unit cannot be used by multiple accessory creation groups")

    created: list[main.UserAccessory] = []
    reward_flags: list[bool] = []
    total_coin = 0
    for group in normalized_groups:
        result = await create_from_units(context, user, group)
        created.append(result.created)
        reward_flags.append(result.reward_box_flag)
        total_coin += result.use_game_coin

    return AccessoryBulkCreateResult(
        created=created,
        use_game_coin=total_coin,
        reward_box_flags=reward_flags,
    )


async def _consume_stats(
    context: idol.BasicSchoolIdolContext, owned: main.UserAccessory
) -> tuple[int, int, int]:
    state = await _level_state(context, owned)
    return (
        int(state.row.get("grant_exp") or 0),
        int(state.row.get("merge_cost") or 0),
        int(state.row.get("sale_price") or 0),
    )


async def _material_stats(context: idol.BasicSchoolIdolContext, accessory_id: int) -> tuple[int, int, int, int, int]:
    master = await accessory_master_by_id(context, accessory_id)
    if master is None or int(master.get("is_material") or 0) == 0:
        raise idol.error.IdolError(detail="invalid accessory material")
    rows = await _level_rows(context, accessory_id)
    if not rows:
        raise idol.error.IdolError(detail="accessory material level master missing")
    row = rows[0]
    return (
        int(master.get("rarity") or 0),
        int(master.get("effect_type") or 0),
        int(row.get("grant_exp") or 0),
        int(row.get("merge_cost") or 0),
        int(row.get("sale_price") or 0),
    )


def _is_rank_up_merge_type(merge_type: int | str) -> bool:
    if isinstance(merge_type, str):
        return merge_type.lower() in {"2", "overcome", "rankup", "rank_up", "remake"}
    return int(merge_type) == 2


async def merge_accessory(
    context: idol.BasicSchoolIdolContext,
    user: main.User,
    base_accessory_owning_user_id: int,
    accessory_owning_user_ids: list[int],
    material_list: list[tuple[int, int]],
    merge_type: int | str,
) -> AccessoryMergeResult:
    base = await get_user_accessory(context, user, base_accessory_owning_user_id)
    before = await to_api_info(context, base)
    base_master = await accessory_master_by_id(context, base.accessory_id)
    if base_master is None or int(base_master.get("is_material") or 0) != 0:
        raise idol.error.IdolError(detail="invalid base accessory")

    ids = list(dict.fromkeys(int(x) for x in accessory_owning_user_ids))
    if len(ids) != len(accessory_owning_user_ids) or base.id in ids:
        raise idol.error.IdolError(detail="invalid accessory merge list")
    normalized_materials = [(int(i), int(a)) for i, a in material_list if int(a) > 0]
    if not ids and not normalized_materials:
        raise idol.error.IdolError(detail="no accessory merge material")

    rank_up = _is_rank_up_merge_type(merge_type)
    consumed_accessories: list[main.UserAccessory] = []
    gain_exp = 0
    use_game_coin = 0
    for owning_id in ids:
        owned = await get_user_accessory(context, user, owning_id)
        await _validate_disposable_accessory(context, user, owned)
        master = await accessory_master_by_id(context, owned.accessory_id)
        if master is None or int(master.get("is_material") or 0) != 0:
            raise idol.error.IdolError(detail="invalid accessory merge material")
        if rank_up and owned.accessory_id != base.accessory_id:
            # The client's getRankUpAccessoryList only exposes duplicates of
            # the base accessory.  Ordinary accessories each count as one
            # remake material.
            raise idol.error.IdolError(detail="remake accessory must have the same accessory id")
        exp_gain, coin_cost, _ = await _consume_stats(context, owned)
        if not rank_up:
            gain_exp += exp_gain
        use_game_coin += coin_cost
        consumed_accessories.append(owned)

    rank_up_from_materials = 0
    for accessory_id, amount in normalized_materials:
        rarity, effect_type, exp_gain, coin_cost, _ = await _material_stats(context, accessory_id)
        row = await _material_row(context, user, accessory_id)
        if row.amount < amount:
            raise idol.error.IdolError(detail="not enough accessory material")
        if rank_up:
            # effect_type=2 is the client's overcome/remake material class
            # (Jewel Parts). Glass Parts (effect_type=1) are enhancement-only.
            if effect_type != 2:
                raise idol.error.IdolError(detail="invalid remake material type")
            rows = await _raw_rows(
                context,
                "SELECT amount FROM accessory_level_limit_over_m "
                "WHERE base_rarity=:base AND material_rarity=:material LIMIT 1",
                {"base": int(base_master.get("rarity") or 0), "material": rarity},
            )
            if not rows:
                raise idol.error.IdolError(detail="invalid remake rarity combination")
            required = int(rows[0]["amount"])
            rank_up_from_materials += amount // required
        else:
            # effect_type=1 is the client's enhance material class.
            if effect_type != 1:
                raise idol.error.IdolError(detail="invalid enhancement material type")
            gain_exp += exp_gain * amount
        use_game_coin += coin_cost * amount

    if use_game_coin > user.game_coin:
        raise idol.error.IdolError(detail="not enough game coin")

    rank_increase = 0
    if rank_up:
        base_default = int(base_master.get("default_max_level") or 1)
        base_absolute = int(base_master.get("max_level") or base_default)
        maximum_rank = min(MAX_RANK_UP_COUNT, max(base_absolute - base_default, 0))
        remaining = maximum_rank - int(base.rank_up_count)
        if remaining <= 0:
            raise idol.error.IdolError(detail="accessory is already at maximum remake count")
        rank_increase = len(consumed_accessories) + rank_up_from_materials
        if rank_increase <= 0:
            raise idol.error.IdolError(detail="not enough remake material")
        if rank_increase > remaining:
            # Normal clients cap the selection at the remaining remake count.
            # Reject a forged over-consumption request instead of silently
            # destroying excess accessories/materials.
            raise idol.error.IdolError(detail="too many remake materials")
        gain_exp = 0

    for owned in consumed_accessories:
        await _remove_accessory(context, user, owned)
    for accessory_id, amount in normalized_materials:
        await _consume_material(context, user, accessory_id, amount)

    user.game_coin -= use_game_coin
    if rank_up:
        base.rank_up_count += rank_increase
    else:
        base.exp += max(gain_exp, 0)
    await context.db.main.flush()

    after = await to_api_info(context, base)
    after_state = await _level_state(context, base)
    return AccessoryMergeResult(
        before=before,
        after=after,
        use_game_coin=use_game_coin,
        gain_exp=gain_exp,
        rank_up_count_after=after.rank_up_count,
        is_enough=(after.rank_up_count >= MAX_RANK_UP_COUNT if rank_up else after.level >= after.max_level),
        rest_exp=after_state.rest_exp,
    )


async def sale_accessories(
    context: idol.BasicSchoolIdolContext,
    user: main.User,
    accessory_owning_user_ids: list[int],
    material_list: list[tuple[int, int]],
) -> AccessorySaleResult:
    ids = list(dict.fromkeys(int(x) for x in accessory_owning_user_ids))
    if len(ids) != len(accessory_owning_user_ids):
        raise idol.error.IdolError(detail="duplicate accessory sale id")
    normalized_materials = [(int(i), int(a)) for i, a in material_list if int(a) > 0]
    if not ids and not normalized_materials:
        raise idol.error.IdolError(detail="no accessory selected")

    total = 0
    owned_rows: list[main.UserAccessory] = []
    for owning_id in ids:
        owned = await get_user_accessory(context, user, owning_id)
        await _validate_disposable_accessory(context, user, owned)
        _, _, sale_price = await _consume_stats(context, owned)
        total += sale_price
        owned_rows.append(owned)
    for accessory_id, amount in normalized_materials:
        _, _, _, _, sale_price = await _material_stats(context, accessory_id)
        row = await _material_row(context, user, accessory_id)
        if row.amount < amount:
            raise idol.error.IdolError(detail="not enough accessory material")
        total += sale_price * amount

    for owned in owned_rows:
        await _remove_accessory(context, user, owned)
    for accessory_id, amount in normalized_materials:
        await _consume_material(context, user, accessory_id, amount)

    # The normal coin cap/present-box behavior is centralized in advanced;
    # callers convert the boolean into the protocol's reward_box_flag.
    from . import advanced
    from . import item

    reward_box_flag = not bool(await advanced.add_item(context, user, item.game_coin(total)))
    await context.db.main.flush()
    return AccessorySaleResult(total=total, reward_box_flag=reward_box_flag)


async def get_worn_accessory_stats(
    context: idol.BasicSchoolIdolContext, user: main.User, unit_owning_user_ids: list[int]
) -> dict[int, tuple[int, int, int]]:
    if not unit_owning_user_ids:
        return {}
    q = (
        sqlalchemy.select(main.UserAccessoryWear, main.UserAccessory)
        .join(main.UserAccessory, main.UserAccessoryWear.accessory_owning_user_id == main.UserAccessory.id)
        .where(
            main.UserAccessoryWear.user_id == user.id,
            main.UserAccessoryWear.unit_owning_user_id.in_(unit_owning_user_ids),
        )
    )
    rows = list((await context.db.main.execute(q)).all())
    if not rows or not await _unit_db_table_exists(context, "accessory_m"):
        return {}

    output: dict[int, tuple[int, int, int]] = {}
    for wear, owned in rows:
        master = await accessory_master_by_id(context, owned.accessory_id)
        if master is None:
            continue
        state = await _level_state(context, owned)
        output[wear.unit_owning_user_id] = (
            max(int(master.get("smile_max") or 0) - int(state.row.get("smile_diff") or 0), 0),
            max(int(master.get("pure_max") or 0) - int(state.row.get("pure_diff") or 0), 0),
            max(int(master.get("cool_max") or 0) - int(state.row.get("cool_diff") or 0), 0),
        )
    return output
