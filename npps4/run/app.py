# Must be loaded first!
import json
import logging

import fastapi

from .. import game
from ..config import config
if config.is_cn_compat():
    from .. import ghome  # CN Shengqu/GHome compatibility routes
from .. import webview
from .. import other
from .. import cn_audit
from .. import util
from ..build_info import BUILD_ID, COMPAT_POLICY
from ..app import app

from typing import Annotated


util.log(f"NPPS4 build: {BUILD_ID}", COMPAT_POLICY, severity=logging.WARNING)


# 404 handler
@app.main.post("/{module}/{action}")
async def not_found_handler(module: str, action: str, request_data: bytes = fastapi.Form()) -> dict:
    util.log("Endpoint not found", f"{module}/{action}", json.loads(request_data), severity=logging.ERROR)
    raise fastapi.HTTPException(404)


app.core.include_router(app.main)
app.core.include_router(app.webview)
main = app.core
