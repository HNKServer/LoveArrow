import pydantic

from .. import idol
from ..system import common


class AreaListResponse(common.TimestampMixin):
    # Stock clients accept an empty catalogue when location campaigns are not
    # configured.  This is a contract-correct safe state, not a fake success
    # for a claimed reward operation.
    secret_banner_flag: bool = False
    area_list: list[dict] = pydantic.Field(default_factory=list)


@idol.register("area", "list")
async def area_list(context: idol.SchoolIdolUserParams) -> AreaListResponse:
    return AreaListResponse()
