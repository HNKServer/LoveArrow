import pydantic

from .. import idol
from ..system import costume
from ..system import unit_model
from ..system import user


class CostumeListResponse(pydantic.BaseModel):
    costume_list: list[unit_model.CostumeInfo]


class CostumeStatusRequest(pydantic.BaseModel):
    status: bool


class CostumeDressUpRequest(pydantic.BaseModel):
    unit_owning_user_id: int
    unit_id: int | None = None
    is_rank_max: bool | None = None
    is_signed: bool | None = None


class CostumeMakeRequest(pydantic.BaseModel):
    unit_owning_user_id: int


class CostumeMakeResponse(pydantic.BaseModel):
    costume_list: list[unit_model.CostumeInfo]


@idol.register("costume", "costumeList")
async def costume_costumelist(context: idol.SchoolIdolUserParams) -> CostumeListResponse:
    current_user = await user.get_current(context)
    return CostumeListResponse(
        costume_list=await costume.list_registered(context, current_user)
    )


@idol.register("costume", "costumeStatus")
async def costume_costumestatus(
    context: idol.SchoolIdolUserParams, request: CostumeStatusRequest
) -> None:
    current_user = await user.get_current(context)
    await costume.set_enabled(context, current_user, request.status)


@idol.register("costume", "dressUp")
async def costume_dressup(
    context: idol.SchoolIdolUserParams, request: CostumeDressUpRequest
) -> None:
    current_user = await user.get_current(context)
    await costume.dress_up(
        context,
        current_user,
        request.unit_owning_user_id,
        request.unit_id,
        request.is_rank_max,
        request.is_signed,
    )


@idol.register("costume", "makeCostume")
async def costume_makecostume(
    context: idol.SchoolIdolUserParams, request: CostumeMakeRequest
) -> CostumeMakeResponse:
    current_user = await user.get_current(context)
    info, created = await costume.register_from_owned_unit(
        context, current_user, request.unit_owning_user_id
    )
    # The exact CN and GL clients blindly append response_data.costume_list.
    # Return only the newly registered appearance; an idempotent retry is empty.
    return CostumeMakeResponse(costume_list=[info] if created else [])
