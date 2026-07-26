from pathlib import Path

import fastapi
import fastapi.responses

from ..app import app

from typing import Annotated


# Do not rely on the process working directory. Android/Chaquopy may start the
# service from an app-private directory, while desktop launchers may start it
# from the repository root. Keep the historical editable path as an override
# and always fall back to the template bundled beside the Python package.
_BUNDLED_STATIC_DIR = Path(__file__).resolve().parents[2] / "templates" / "static"


def _resolve_static_page(page_id: int) -> Path | None:
    filename = f"{page_id}.html"
    for directory in (Path("templates") / "static", _BUNDLED_STATIC_DIR):
        candidate = directory / filename
        if candidate.is_file():
            return candidate
    return None


@app.webview.get("/static/index")
async def static_index(id: Annotated[int, fastapi.Query()]):
    # CN common/const.lua assigns Android id=12 to VERSION_UP_WEBVIEW_URL.
    # That native modal deliberately has no close button.  The server must keep
    # Client/Server-Version and the resolved profile correct so normal startup
    # never enters it; redirecting id=12 to news only changes the HTML inside a
    # still-non-dismissible forced-update dialog.
    path = _resolve_static_page(id)
    if path is not None:
        return fastapi.responses.FileResponse(
            path,
            media_type="text/html; charset=utf-8",
            headers={"Cache-Control": "no-store"},
        )

    return fastapi.responses.JSONResponse({"detail": "not found", "id": id}, 404)
