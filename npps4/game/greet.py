import pydantic

from .. import idol
from ..system import greet as greet_system
from ..system import user as user_system


class GreetUserRequest(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="allow")

    to_user_id: int
    message: str
    replied_notice_id: int = 0


class GreetDeleteRequest(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="allow")

    is_send_mail: bool = False
    mail_notice_id: int


class EmptyListResponse(pydantic.RootModel[list]):
    root: list = pydantic.Field(default_factory=list)


@idol.register("greet", "user", batchable=False)
async def greet_user(context: idol.SchoolIdolUserParams, request: GreetUserRequest) -> EmptyListResponse:
    current_user = await user_system.get_current(context)
    target = await greet_system.resolve_user(context, request.to_user_id)
    await greet_system.create_greeting(context, current_user, target, request.message, request.replied_notice_id)
    return EmptyListResponse.model_validate([])


@idol.register("greet", "delete", batchable=False)
async def greet_delete(context: idol.SchoolIdolUserParams, request: GreetDeleteRequest) -> EmptyListResponse:
    current_user = await user_system.get_current(context)
    await greet_system.delete_greeting(context, current_user, request.mail_notice_id, request.is_send_mail)
    return EmptyListResponse.model_validate([])
