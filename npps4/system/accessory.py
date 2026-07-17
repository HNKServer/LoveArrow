from __future__ import annotations

import dataclasses
import datetime
import json
import os
from typing import Any

import sqlalchemy

from . import accessory_model
from . import unit as unit_system
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
    try:
        result = await context.db.unit.execute(
            sqlalchemy.text("SELECT name FROM sqlite_master WHERE type='table' AND name=:name"), {"name": table}
        )
        return result.scalar() is not None
    except Exception:
        return False


async def _raw_rows(
    context: idol.BasicSchoolIdolContext,
    sql: str,
    params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    result = await context.db.unit.execute(sqlalchemy.text(sql), params or {})
    return [dict(row._mapping) for row in result]


async def _raw_accessory_rows(context: idol.BasicSchoolIdolContext, *, materials: bool | None = None) -> list[dict]:
    if not await _unit_db_table_exists(context, "accessory_m"):
        return []
    where = ""
    if materials is True:
        where = " WHERE COALESCE(is_material, 0) != 0"
    elif materials is False:
        where = " WHERE COALESCE(is_material, 0) = 0"
    try:
        return await _raw_rows(
            context,
            "SELECT accessory_id, name, name_en, rarity, "
            "COALESCE(smile_max, 0) AS smile_max, "
            "COALESCE(pure_max, 0) AS pure_max, "
            "COALESCE(cool_max, 0) AS cool_max, "
            "COALESCE(is_material, 0) AS is_material, "
            "COALESCE(effect_type, 0) AS effect_type, "
            "COALESCE(default_max_level, 1) AS default_max_level, "
            "COALESCE(max_level, COALESCE(default_max_level, 1)) AS max_level, "
            "COALESCE(accessory_asset_id, accessory_id) AS accessory_asset_id "
            f"FROM accessory_m{where} ORDER BY accessory_id ASC",
        )
    except Exception as e:
        util.log("Unable to read accessory_m; returning empty accessory master list", severity=util.logging.WARNING, e=e)
        return []


async def accessory_master_by_id(context: idol.BasicSchoolIdolContext, accessory_id: int) -> dict | None:
    if not await _unit_db_table_exists(context, "accessory_m"):
        return None
    rows = await _raw_rows(
        context,
        "SELECT accessory_id, name, name_en, rarity, COALESCE(smile_max,0) AS smile_max, "
        "COALESCE(pure_max,0) AS pure_max, COALESCE(cool_max,0) AS cool_max, "
        "COALESCE(is_material,0) AS is_material, COALESCE(effect_type,0) AS effect_type, "
        "COALESCE(default_max_level,1) AS default_max_level, "
        "COALESCE(max_level,COALESCE(default_max_level,1)) AS max_level, "
        "COALESCE(accessory_asset_id,accessory_id) AS accessory_asset_id "
        "FROM accessory_m WHERE accessory_id=:id LIMIT 1",
        {"id": accessory_id},
    )
    return rows[0] if rows else None


async def _level_rows(context: idol.BasicSchoolIdolContext, accessory_id: int) -> list[dict[str, Any]]:
    if not await _unit_db_table_exists(context, "accessory_level_m"):
        return []
    return await _raw_rows(
        context,
        "SELECT accessory_id, level, COALESCE(next_exp,0) AS next_exp, "
        "COALESCE(smile_diff,0) AS smile_diff, COALESCE(pure_diff,0) AS pure_diff, "
        "COALESCE(cool_diff,0) AS cool_diff, COALESCE(grant_exp,0) AS grant_exp, "
        "COALESCE(merge_cost,0) AS merge_cost, COALESCE(sale_price,0) AS sale_price "
        "FROM accessory_level_m WHERE accessory_id=:id ORDER BY level ASC",
        {"id": accessory_id},
    )


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
    if not await _unit_db_table_exists(context, "accessory_base_setting_m"):
        return 999, 999999999
    rows = await _raw_rows(
        context,
        "SELECT owning_capacity, owning_material_capacity FROM accessory_base_setting_m ORDER BY accessory_base_setting_id LIMIT 1",
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


async def _has_special_creation_candidate(context: idol.BasicSchoolIdolContext, user: main.User) -> bool:
    if not await _unit_db_table_exists(context, "accessory_special_m"):
        return False
    result = await context.db.unit.execute(sqlalchemy.text("SELECT unit_id FROM accessory_special_m"))
    unit_ids = [int(row[0]) for row in result]
    if not unit_ids:
        return False
    q = sqlalchemy.select(main.Unit.id).where(main.Unit.user_id == user.id, main.Unit.unit_id.in_(unit_ids)).limit(1)
    return (await context.db.main.execute(q)).scalar() is not None


async def get_accessory_all_info(
    context: idol.BasicSchoolIdolContext, user: main.User
) -> accessory_model.AccessoryAllInfo:
    q = sqlalchemy.select(main.UserAccessory).where(main.UserAccessory.user_id == user.id).order_by(
        main.UserAccessory.accessory_id, main.UserAccessory.id
    )
    result = await context.db.main.execute(q)
    accessory_list = [await to_api_info(context, row) for row in result.scalars()]

    q = sqlalchemy.select(main.UserAccessoryWear).where(main.UserAccessoryWear.user_id == user.id).order_by(
        main.UserAccessoryWear.unit_owning_user_id
    )
    result = await context.db.main.execute(q)
    wearing_info = [
        accessory_model.AccessoryWearInfo(
            unit_owning_user_id=row.unit_owning_user_id,
            accessory_owning_user_id=row.accessory_owning_user_id,
        )
        for row in result.scalars()
    ]
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
    return accessory_model.AccessoryMaterialAllInfo(
        accessory_material_list=[
            accessory_model.AccessoryMaterialInfo(accessory_id=row.accessory_id, amount=row.amount)
            for row in result.scalars()
            if row.amount > 0
        ]
    )


_FALLBACK_TABS = [
    ("μ's", list(range(1, 10))),
    ("Aqours", list(range(101, 110))),
    ("虹ヶ咲", list(range(201, 214))),
    ("Liella!", list(range(301, 314))),
]


def _tab_asset(unit_type_id: int) -> accessory_model.AccessoryTabAssetInfo:
    if 1 <= unit_type_id <= 9:
        list_id = unit_type_id
    elif 101 <= unit_type_id <= 109:
        list_id = unit_type_id - 91
    elif 201 <= unit_type_id <= 213:
        list_id = unit_type_id - 182
    elif 301 <= unit_type_id <= 313:
        list_id = unit_type_id - 265
    else:
        list_id = unit_type_id
    return accessory_model.AccessoryTabAssetInfo(
        unit_type_id=unit_type_id,
        asset_path=f"assets/image/accessory/list/list_{list_id}.png",
    )


async def get_accessory_tab_info(context: idol.BasicSchoolIdolContext) -> accessory_model.AccessoryTabListInfo:
    candidate_paths = [
        os.path.join("npps4", "accessory_tab_list.json"),
        os.path.join("npps4", "data", "accessory_tab_list.json"),
        os.path.join("assets", "serverdata", "accessory_tab_list.json"),
    ]
    for path in candidate_paths:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return accessory_model.AccessoryTabListInfo.model_validate({"tab_list": data})

    return accessory_model.AccessoryTabListInfo(
        tab_list=[
            accessory_model.AccessoryTabInfo(tab_name=name, asset_list=[_tab_asset(uid) for uid in unit_type_ids])
            for name, unit_type_ids in _FALLBACK_TABS
        ]
    )


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
        await get_user_accessory(context, user, accessory_owning_user_id)
        unit_data = await unit_system.get_unit(context, unit_owning_user_id)
        unit_system.validate_unit(user, unit_data)
        if not unit_data.active:
            raise idol.error.IdolError(detail="cannot wear accessory on inactive unit")
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
    if not await _unit_db_table_exists(context, "accessory_special_m"):
        return None
    rows = await _raw_rows(
        context,
        "SELECT accessory_id FROM accessory_special_m WHERE unit_id=:unit_id ORDER BY accessory_id LIMIT 1",
        {"unit_id": unit_id},
    )
    return int(rows[0]["accessory_id"]) if rows else None


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
    chosen = util.SYSRAND.choices(candidates, weights=[max(int(x["weight"]), 0) for x in candidates], k=1)[0]
    return int(chosen["accessory_id"])


async def create_from_units(
    context: idol.SchoolIdolParams, user: main.User, unit_owning_user_ids: list[int]
) -> AccessoryCreateResult:
    ids = list(dict.fromkeys(int(x) for x in unit_owning_user_ids))
    if not ids or len(ids) != len(unit_owning_user_ids):
        raise idol.error.IdolError(detail="invalid unit list for accessory creation")

    units: list[main.Unit] = []
    full_infos = []
    game_coin_cost = 0
    lottery_cost = 0
    for owning_id in ids:
        unit_data = await unit_system.get_unit(context, owning_id)
        unit_system.validate_unit(user, unit_data)
        if unit_data.favorite_flag:
            raise idol.error.IdolError(detail="favorite unit cannot be used for accessory creation")
        if unit_data.id == user.center_unit_owning_user_id:
            raise idol.error.IdolError(detail="partner unit cannot be used for accessory creation")
        worn = await context.db.main.execute(
            sqlalchemy.select(main.UserAccessoryWear.id).where(
                main.UserAccessoryWear.user_id == user.id,
                main.UserAccessoryWear.unit_owning_user_id == unit_data.id,
            ).limit(1)
        )
        if worn.scalar() is not None:
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
    if len(units) == 1:
        accessory_id = await _special_accessory_for_unit(context, units[0].unit_id)
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
