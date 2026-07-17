import pydantic

from .. import idol
from ..config import config
from ..system import common
from ..system import item
from ..system import user

from typing import Annotated, Any


def empty_list_is_empty_dict(value: Any):
    if isinstance(value, list) and len(value) == 0:
        return {}
    return value


class CnGeneralItemCount(common.ItemCount):
    # Fields expected by the CN 9.7.x client.  They extend rather than replace
    # NPPS4's item model.
    use_button_flag: bool = False
    general_item_type: int = 0


class CnBuffItemCount(common.ItemCount):
    buff_type: int = 0


class ItemListReinforceInfoUnitReinforceItem(pydantic.BaseModel):
    unit_reinforce_item_id: int
    reinforce_type: int
    addition_value: int
    target_unit_ids: list[int]


class ItemListReinforceInfo(pydantic.BaseModel):
    event_id: int
    item_list: list[ItemListReinforceInfoUnitReinforceItem]
    available_unit_list: list[dict]  # Additionally has mark_id (int) and sub_evaluation (int)


class ItemListResponse(pydantic.BaseModel):
    general_item_list: list[common.ItemCount]
    buff_item_list: list[common.ItemCount]
    reinforce_item_list: list[common.ItemCount]
    reinforce_info: Annotated[dict[str, ItemListReinforceInfo], pydantic.BeforeValidator(empty_list_is_empty_dict)] = (
        pydantic.Field(default_factory=dict)
    )


class CnCompatibleItemListResponse(ItemListResponse):
    """NPPS4's complete response plus the CN client's per-item metadata."""

    general_item_list: list[CnGeneralItemCount]
    buff_item_list: list[CnBuffItemCount]


def _cn_general_item_count(src: common.ItemCount) -> CnGeneralItemCount:
    return CnGeneralItemCount(item_id=src.item_id, amount=src.amount)


def _cn_buff_item_count(src: common.ItemCount) -> CnBuffItemCount:
    return CnBuffItemCount(item_id=src.item_id, amount=src.amount)


@idol.register("item", "list")
async def item_list(context: idol.SchoolIdolUserParams) -> ItemListResponse | CnCompatibleItemListResponse:
    current_user = await user.get_current(context=context)
    general_item_list, buff_item_list, reinforce_item_list = await item.get_item_list(context, current_user)

    if config.is_cn_compat():
        # Add the CN metadata without dropping NPPS4's reinforce inventory and
        # reinforce_info fields.  Extra JSON keys are harmless to the CN client,
        # while retaining them keeps the richer NPPS4 feature set available.
        return CnCompatibleItemListResponse(
            general_item_list=[_cn_general_item_count(x) for x in general_item_list],
            buff_item_list=[_cn_buff_item_count(x) for x in buff_item_list],
            reinforce_item_list=reinforce_item_list,
        )

    return ItemListResponse(
        general_item_list=general_item_list,
        buff_item_list=buff_item_list,
        reinforce_item_list=reinforce_item_list,
    )
