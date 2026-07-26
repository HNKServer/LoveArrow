from . import client_catalogue
from . import common
from . import item
from . import secretbox_model
from . import user
from .. import const
from .. import data
from .. import idol
from .. import util
from ..db import main
from ..db import unit as unit_db

import sqlalchemy
from ..config import config


def _determine_en_path(context: idol.BasicSchoolIdolContext, path: str, path_en: str | None, /):
    # The CN 9.7.1 client reports an English UI language, but its resource
    # archive is still the unprefixed CN namespace.  Treating that language as
    # the GL English profile made the server return en/... secretbox textures;
    # the GL overlay then injected later-version .texb files and the CN native
    # renderer trapped.  Region/profile wins over language for CN resources.
    if config.is_cn_compat():
        return path

    if path_en is None or context.is_lang_jp():
        return path

    if path_en == "":
        return f"en/{path}"
    else:
        return path_en


def encode_cost_id(secretbox_id: int, button_index: int, cost_index: int, /):
    return (button_index << 36) | (cost_index << 32) | secretbox_id


def decode_cost_id(cost_id: int):
    secretbox_id = cost_id & 0xFFFFFFFF
    cost_index = (cost_id >> 32) & 0xF
    button_index = cost_id >> 36
    return secretbox_id, button_index, cost_index


async def query_secretbox_button(
    context: idol.BasicSchoolIdolContext,
    user: main.User,
    button: data.schema.SecretboxButton,
    secretbox_name: str,
    ids: tuple[int, int],
):
    costs = [
        secretbox_model.SecretboxAllCost(
            id=encode_cost_id(ids[0], ids[1], j),
            payable=await get_user_currency(context, user, cost.cost_type, cost.cost_item_id) >= cost.cost_amount,
            unit_count=button.unit_count,
            type=cost.cost_type,
            item_id=cost.cost_item_id,
            amount=cost.cost_amount,
        )
        for j, cost in enumerate(button.costs, 1)
    ]

    name = secretbox_name
    if button.name is not None:
        name = context.get_text(button.name, button.name_en)

    if button.balloon_asset is not None:
        return secretbox_model.SecretboxAllButtonWithBaloon(
            secret_box_button_type=button.button_type,
            cost_list=costs,
            secret_box_name=name,
            balloon_asset=_determine_en_path(context, button.balloon_asset, button.balloon_asset_en),
        )
    else:
        return secretbox_model.SecretboxAllButton(
            secret_box_button_type=button.button_type,
            cost_list=costs,
            secret_box_name=name,
        )


async def get_secretbox_button_response(
    context: idol.BasicSchoolIdolContext, target_user: main.User, secretbox: data.schema.SecretboxData
):
    return [
        # TODO: Free once a day scouting
        await query_secretbox_button(
            context,
            target_user,
            button,
            context.get_text(secretbox.name, secretbox.name_en),
            (secretbox.secretbox_id, i),
        )
        for i, button in enumerate(secretbox.buttons, 1)
    ]


async def get_secretbox_info_response(
    context: idol.BasicSchoolIdolContext,
    target_user: main.User,
    secretbox: data.schema.SecretboxData,
    can_do_more: bool,
):
    return secretbox_model.SecretboxAllSecretboxInfo(
        secret_box_id=secretbox.secretbox_id,
        secret_box_type=secretbox.secretbox_type,
        name=context.get_text(secretbox.name, secretbox.name_en),
        start_date=util.timestamp_to_datetime(secretbox.start_time),
        end_date=util.timestamp_to_datetime(secretbox.end_time),
        add_gauge=0,  # TODO
        always_display_flag=1,
        pon_count=can_do_more * 100,  # TODO
    )


@common.context_cacheable("secretbox_thanks_pools")
async def _thanks_festival_pools(
    context: idol.BasicSchoolIdolContext, member_category: int, /
) -> list[list[int]]:
    """Return profile-exact SSR/UR pools without trusting reconstructed UnitType rows.

    Several fallback masters contain the Unit rows but incomplete or mismatched
    ``unit_type_m.member_category`` metadata.  The exact supplied-client
    catalogue carries a pre-audited category map; candidates are then
    intersected with Unit rows which really exist in the active backend so a
    visible page can never draw an unresolvable card.
    """
    catalogue = await client_catalogue.current(context)
    configured = catalogue.thanks_festival_pools.get(int(member_category), {})
    candidates = sorted(
        set(configured.get(5, ())) | set(configured.get(4, ()))
    )
    if not candidates:
        return [[], []]
    rows = (
        await context.db.unit.execute(
            sqlalchemy.select(unit_db.Unit.unit_id, unit_db.Unit.rarity)
            .where(
                unit_db.Unit.unit_id.in_(candidates),
                unit_db.Unit.disable_rank_up == int(const.UNIT_CATEGORY.NORMAL),
                unit_db.Unit.rarity.in_((5, 4)),
            )
            .order_by(unit_db.Unit.unit_id)
        )
    ).all()
    existing = {int(row.unit_id): int(row.rarity) for row in rows}
    by_rarity = {
        rarity: [
            int(unit_id)
            for unit_id in configured.get(rarity, ())
            if existing.get(int(unit_id)) == rarity
        ]
        for rarity in (5, 4)
    }
    util.log(
        "Thanks Festival profile pool",
        f"profile={context.profile.value}",
        f"member_category={member_category}",
        f"SSR={len(by_rarity[5])}",
        f"UR={len(by_rarity[4])}",
    )
    # Client page order is SSR then UR.
    return [by_rarity[5], by_rarity[4]]


@common.context_cacheable("projected_secretbox")
async def _project_secretbox(
    context: idol.BasicSchoolIdolContext, secretbox_id: int, /
) -> data.schema.SecretboxData | None:
    raw = data.get().secretbox_data.get(secretbox_id)
    if raw is None:
        return None
    if raw.profiles is not None and context.profile.value not in raw.profiles:
        return None

    if raw.pool_mode == "thanks_festival":
        pools = await _thanks_festival_pools(context, int(raw.member_category))
    else:
        supported = (await client_catalogue.current(context)).unit_ids
        pools = [[int(unit_id) for unit_id in pool if int(unit_id) in supported] for pool in raw.rarity_pools]

    if len(pools) != len(raw.rarity_rates) or len(raw.rarity_names) != len(raw.rarity_rates):
        util.log("Invalid secretbox rarity layout", raw.id_string, severity=util.logging.WARNING)
        return None
    if any(int(rate) > 0 and not pools[index] for index, rate in enumerate(raw.rarity_rates)):
        util.log(
            "Hiding secretbox with an empty profile pool",
            raw.id_string,
            f"profile={context.profile.value}",
            severity=util.logging.WARNING,
        )
        return None
    return raw.model_copy(update={"rarity_pools": pools})


async def get_visible_secretboxes(context: idol.BasicSchoolIdolContext) -> list[data.schema.SecretboxData]:
    now = util.time()
    result: list[data.schema.SecretboxData] = []
    for secretbox_id in data.get().secretbox_data:
        projected = await _project_secretbox(context, int(secretbox_id))
        if projected is None:
            continue
        if int(projected.start_time) <= now <= int(projected.end_time):
            result.append(projected)
    return result


def resolve_menu_asset(context: idol.BasicSchoolIdolContext, secretbox: data.schema.SecretboxData) -> str:
    return _determine_en_path(context, secretbox.menu_asset, secretbox.menu_asset_en)


async def get_all_secretbox_data_response(context: idol.BasicSchoolIdolContext, target_user: main.User):
    member_category_list: dict[int, list[secretbox_model.SecretboxAllPage]] = {}
    visible_pages = await get_visible_secretboxes(context)

    for secretbox in visible_pages:
        if len(secretbox.animation_asset_layout) > 3:
            animation_assets = secretbox_model.SecretboxAllAnimation3Asset(
                type=secretbox.animation_layout_type,
                background_asset=_determine_en_path(
                    context, secretbox.animation_asset_layout[0], secretbox.animation_asset_layout_en[0]
                ),
                additional_asset_1=_determine_en_path(
                    context, secretbox.animation_asset_layout[1], secretbox.animation_asset_layout_en[1]
                ),
                additional_asset_2=_determine_en_path(
                    context, secretbox.animation_asset_layout[2], secretbox.animation_asset_layout_en[2]
                ),
                additional_asset_3=_determine_en_path(
                    context, secretbox.animation_asset_layout[3], secretbox.animation_asset_layout_en[3]
                ),
            )
        else:
            animation_assets = secretbox_model.SecretboxAllAnimation2Asset(
                type=secretbox.animation_layout_type,
                background_asset=_determine_en_path(
                    context, secretbox.animation_asset_layout[0], secretbox.animation_asset_layout_en[0]
                ),
                additional_asset_1=_determine_en_path(
                    context, secretbox.animation_asset_layout[1], secretbox.animation_asset_layout_en[1]
                ),
                additional_asset_2=_determine_en_path(
                    context, secretbox.animation_asset_layout[2], secretbox.animation_asset_layout_en[2]
                ),
            )
        page = secretbox_model.SecretboxAllPage(
            menu_asset=resolve_menu_asset(context, secretbox),
            page_order=secretbox.order,
            animation_assets=animation_assets,
            button_list=await get_secretbox_button_response(context, target_user, secretbox),
            secret_box_info=await get_secretbox_info_response(context, target_user, secretbox, False),
        )
        member_category_list.setdefault(secretbox.member_category, []).append(page)

    result = sorted(
        (
            secretbox_model.SecretboxAllMemberCategory(
                member_category=k, page_list=sorted(v, key=lambda page: page.page_order)
            )
            for k, v in member_category_list.items()
        ),
        key=lambda k: k.member_category,
    )
    if config.is_cn_compat(context.profile):
        util.log(
            "CN secretbox asset contract",
            f"pages={len(visible_pages)}",
            f"ids={[page.secretbox_id for page in visible_pages]}",
            f"sample_paths={[resolve_menu_asset(context, page) for page in visible_pages[:6]]}",
            severity=util.logging.WARNING,
        )
    return result


async def get_secretbox_data(
    context: idol.BasicSchoolIdolContext, secretbox_id: int
) -> data.schema.SecretboxData:
    projected = await _project_secretbox(context, int(secretbox_id))
    if projected is None:
        raise KeyError(secretbox_id)
    return projected


def roll_units(
    secretbox_data: data.schema.SecretboxData,
    amount: int,
    /,
    *,
    guarantee_rarity: int = 0,
    guarantee_amount: int = 0,
    rate_modifier: list[int] | None = None,
):
    rates = rate_modifier if rate_modifier is not None else secretbox_data.rarity_rates
    if len(rates) != len(secretbox_data.rarity_pools):
        raise ValueError("secretbox rate modifier does not match rarity pools")
    picked_rarity_index = util.SYSRAND.choices(range(len(secretbox_data.rarity_rates)), rates, k=amount)

    if guarantee_rarity > 0 and guarantee_amount > 0:
        rindex = guarantee_rarity - 1
        indices = range(amount)
        while sum(k >= rindex for k in picked_rarity_index) < guarantee_amount:
            random_index = util.SYSRAND.choice(indices)
            if picked_rarity_index[random_index] < rindex:
                picked_rarity_index[random_index] = rindex

    return [util.SYSRAND.choice(secretbox_data.rarity_pools[i]) for i in picked_rarity_index]


def get_secretbox_button(secretbox_data: data.schema.SecretboxData, button_index: int):
    return secretbox_data.buttons[button_index - 1]


async def get_user_currency(
    context: idol.BasicSchoolIdolContext,
    target_user: main.User,
    /,
    cost_type: const.SECRETBOX_COST_TYPE,
    cost_item_id: int | None,
):
    match cost_type:
        case const.SECRETBOX_COST_TYPE.ITEM_TICKET:
            if cost_item_id is None:
                raise ValueError("Empty item_id for type 1000")
            return await item.get_item_count(context, target_user, cost_item_id)
        case const.SECRETBOX_COST_TYPE.GAME_COIN:
            return target_user.game_coin
        case const.SECRETBOX_COST_TYPE.LOVECA:
            return user.get_loveca(target_user, include_free=cost_item_id != 1)
        case const.SECRETBOX_COST_TYPE.FRIEND:
            return target_user.social_point
        case _:
            return 0


async def sub_user_currency(
    context: idol.BasicSchoolIdolContext,
    target_user: main.User,
    /,
    cost_type: const.SECRETBOX_COST_TYPE,
    cost_item_id: int | None,
    amount: int,
):
    match cost_type:
        case const.SECRETBOX_COST_TYPE.ITEM_TICKET:
            if cost_item_id is None:
                raise ValueError("Empty item_id for type 1000")
            await item.add_item(context, target_user, cost_item_id, -amount)
        case const.SECRETBOX_COST_TYPE.GAME_COIN:
            target_user.game_coin = target_user.game_coin - amount
        case const.SECRETBOX_COST_TYPE.LOVECA:
            user.sub_loveca(target_user, amount, sub_paid_only=cost_item_id == 1)
        case const.SECRETBOX_COST_TYPE.FRIEND:
            target_user.social_point = target_user.social_point - amount
