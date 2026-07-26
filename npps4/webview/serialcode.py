import urllib.parse

import fastapi
import pydantic

from .. import data
from .. import idol
from ..idol import session as idol_session
from .. import serialcode
from .. import util
from ..app import app
from ..system import user

from typing import Annotated


class SerialCodeAPIRequest(pydantic.BaseModel):
    key: str


class SerialCodeAPIResponse(pydantic.BaseModel):
    ok: bool
    msg: str


@app.webview.get("/serialCode/index")
async def serial_code_index(request: fastapi.Request):
    token = ""
    authorize_header = request.headers.get("Authorize")
    if authorize_header is not None:
        token = util.extract_token_from_authorize(authorize_header)

    return app.templates.TemplateResponse(
        request, "serialcode.html", {"token": token, "lang": request.headers.get("lang", "en")}
    )


@app.webview.post(
    "/serialCode/index", response_class=fastapi.responses.JSONResponse, response_model=SerialCodeAPIResponse
)
async def serial_code_index_post(
    authorize: Annotated[str, fastapi.Header()],
    lang: Annotated[idol.Language, fastapi.Header(alias="LANG")],
    key_request: SerialCodeAPIRequest,
):
    try:
        async with idol.BasicSchoolIdolContext(lang) as context:
            token = util.extract_token_from_authorize(authorize)
            if token is None:
                return SerialCodeAPIResponse(ok=False, msg="Missing Token")

            # WebView requests do not contain the normal game API's
            # Client-Version header. Resolve the authenticated session before
            # any profile-specific Master lookup, otherwise both clients run
            # serial codes on the configured default profile.
            token_data = await idol_session.decapsulate_token(context, token)
            if token_data is None or int(token_data.user_id or 0) <= 0:
                return SerialCodeAPIResponse(ok=False, msg="Missing User")
            context.select_profile(token_data.profile)

            current_user = await user.get(context, int(token_data.user_id))
            if current_user is None:
                return SerialCodeAPIResponse(ok=False, msg="Missing User")

            # Find the serial code
            input_code = key_request.key.strip()
            for serial_code in data.get().serial_codes:
                if serial_code.check_serial_code(input_code):
                    # Found
                    return SerialCodeAPIResponse(
                        ok=True, msg=await serialcode.execute(context, current_user, input_code, serial_code)
                    )

            return SerialCodeAPIResponse(ok=False, msg="unknown or invalid serial code")
    except Exception as e:
        util.log("Error while running serial code", severity=util.logging.ERROR, e=e)
        return SerialCodeAPIResponse(ok=False, msg=str(e))
