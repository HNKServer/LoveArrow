# Must be loaded first!
import json
import logging

import fastapi

from .. import idoltype
from ..idol import core as idol_core
from ..idol import error as idol_error
from ..idol import session as idol_session

from .. import game
from ..config import config
if config.profile_enabled("cn"):
    from .. import ghome  # CN Shengqu/GHome compatibility routes
from .. import webview
from .. import other
from .. import cn_audit
from .. import util
from ..build_info import BUILD_ID, COMPAT_POLICY
from ..app import app

from typing import Annotated


util.log(f"NPPS4 build: {BUILD_ID}", COMPAT_POLICY, severity=logging.WARNING)


# Catch unknown SIF endpoints after every real route has been registered.
# Ordinary HTTP resources still use FastAPI's normal 404 handler; only
# authenticated /main.php game calls receive a signed protocol error.
@app.main.post("/{module}/{action}")
async def not_found_handler(
    module: str,
    action: str,
    context: Annotated[idol_session.SchoolIdolUserParams, fastapi.Depends(idol_session.SchoolIdolUserParams)],
    request_data: bytes = fastapi.Form(default=b"{}"),
):
    try:
        decoded = json.loads(request_data or b"{}")
    except Exception:
        decoded = {"raw_size": len(request_data or b"")}
    util.log("Endpoint not found", f"{module}/{action}", decoded, severity=logging.ERROR)
    async with context:
        await context.finalize()
    response = await idol_core.client_check(context, True, idoltype.XMCVerifyMode.SHARED)
    if response is not None:
        return response
    return await idol_core.build_response(
        context,
        idol_error.IdolError(
            idol_error.ERROR_CODE_LIB_ERROR,
            600,
            f"Endpoint not implemented: {module}/{action}",
            http_code=200,
        ),
    )


app.core.include_router(app.main)
app.core.include_router(app.webview)
main = app.core
