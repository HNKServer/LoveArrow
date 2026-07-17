import pydantic

from .. import idol
from .. import util
from ..system import museum
from ..system import user


class MuseumInfoResponse(pydantic.BaseModel):
    museum_info: museum.MuseumInfoData


@idol.register("museum", "info")
async def museum_info(context: idol.SchoolIdolUserParams) -> MuseumInfoResponse:
    current_user = await user.get_current(context)
    info = await museum.get_museum_info_data(context, current_user)
    util.log(
        "Museum info",
        f"user_id={current_user.id}",
        f"contents_count={len(info.contents_id_list)}",
        f"buff=({info.parameter.smile},{info.parameter.pure},{info.parameter.cool})",
        severity=util.logging.INFO,
    )
    return MuseumInfoResponse(museum_info=info)
