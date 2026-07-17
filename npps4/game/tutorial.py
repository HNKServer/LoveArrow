from .. import idol
from .. import util
from ..idol import error
from ..config import config
from ..system import onboarding
from ..system import tutorial
from ..system import user

import pydantic


class TutorialProgressRequest(pydantic.BaseModel):
    # Both supplied clients send exactly this required field.  Do not infer a
    # transition from a malformed request: doing so can mutate account state
    # while the client and server disagree about the current tutorial phase.
    tutorial_state: int


@idol.register("tutorial", "progress", batchable=False)
async def tutorial_progress(
    context: idol.SchoolIdolUserParams, request: TutorialProgressRequest
) -> None:
    current_user = await user.get_current(context)
    await onboarding.repair_v434_v437_completed_empty(context, current_user)

    if current_user.tutorial_state == -1:
        raise error.IdolError(detail="Tutorial already finished")

    requested_state = request.tutorial_state
    util.log(
        "Tutorial progress",
        f"user={current_user.id}",
        f"current={current_user.tutorial_state}",
        f"requested={requested_state}",
        severity=util.logging.WARNING if config.is_cn_compat() else util.logging.INFO,
    )

    if current_user.tutorial_state == 0 and requested_state == 1:
        await tutorial.phase1(context, current_user)
    elif current_user.tutorial_state == 1 and requested_state == 2:
        await tutorial.phase2(context, current_user)
    elif current_user.tutorial_state == 2 and requested_state == 3:
        await tutorial.phase3(context, current_user)
    elif current_user.tutorial_state == 3 and requested_state == -1:
        await tutorial.finalize(context, current_user)
    else:
        raise error.IdolError(
            detail=f"Unknown state, u {current_user.tutorial_state} r {requested_state}"
        )

    await context.db.main.flush()


@idol.register("tutorial", "skip", batchable=False)
async def tutorial_skip(context: idol.SchoolIdolUserParams) -> None:
    current_user = await user.get_current(context)
    await onboarding.repair_v434_v437_completed_empty(context, current_user)

    if current_user.tutorial_state == -1:
        raise error.IdolError(detail="Tutorial already finished")

    util.log(
        "Tutorial skip",
        f"user={current_user.id}",
        f"current={current_user.tutorial_state}",
        severity=util.logging.WARNING if config.is_cn_compat() else util.logging.INFO,
    )

    match current_user.tutorial_state:
        case 0:
            await tutorial.phase1(context, current_user)
            await tutorial.phase2(context, current_user)
            await tutorial.phase3(context, current_user)
            await tutorial.finalize(context, current_user)
        case 1:
            await tutorial.phase2(context, current_user)
            await tutorial.phase3(context, current_user)
            await tutorial.finalize(context, current_user)
        case 2:
            await tutorial.phase3(context, current_user)
            await tutorial.finalize(context, current_user)
        case 3:
            await tutorial.finalize(context, current_user)
        case _:
            raise error.IdolError(detail=f"Invalid tutorial state: {current_user.tutorial_state}")

    await context.db.main.flush()
