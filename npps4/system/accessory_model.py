import pydantic


class AccessoryListInfo(pydantic.BaseModel):
    accessory_owning_user_id: int
    accessory_id: int
    exp: int
    next_exp: int = 0
    level: int = 1
    max_level: int = 1
    rank_up_count: int = 0
    favorite_flag: bool = False


class AccessoryWearInfo(pydantic.BaseModel):
    unit_owning_user_id: int
    accessory_owning_user_id: int


class AccessoryAllInfo(pydantic.BaseModel):
    accessory_list: list[AccessoryListInfo]
    wearing_info: list[AccessoryWearInfo]
    especial_create_flag: bool = False


class AccessoryMaterialInfo(pydantic.BaseModel):
    accessory_id: int
    amount: int


class AccessoryMaterialAllInfo(pydantic.BaseModel):
    accessory_material_list: list[AccessoryMaterialInfo]


class AccessoryTabAssetInfo(pydantic.BaseModel):
    unit_type_id: int
    asset_path: str


class AccessoryTabInfo(pydantic.BaseModel):
    tab_name: str
    asset_list: list[AccessoryTabAssetInfo]


class AccessoryTabListInfo(pydantic.BaseModel):
    tab_list: list[AccessoryTabInfo]
