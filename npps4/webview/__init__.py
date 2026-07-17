import html
import urllib.parse
from pathlib import Path

import fastapi.responses
import fastapi.templating

from ..config import config

if not config.is_script_mode():
    from . import announce
    from . import helper
    from . import manga
    from . import secretbox
    from . import serialcode
    from . import static
    from . import tos
    from . import transfer

from .. import errhand
from ..app import app


def _template_bytes(name: str) -> bytes:
    workspace = Path(config.ROOT_DIR) / "templates" / name
    if workspace.is_file():
        return workspace.read_bytes()
    bundled = Path(__file__).resolve().parents[2] / "templates" / name
    return bundled.read_bytes()


def _html_page(title: str, message: str) -> fastapi.responses.HTMLResponse:
    safe_title = html.escape(title or "Information")
    safe_message = html.escape(message or "")
    return fastapi.responses.HTMLResponse(
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<style>body{background:#fff;color:#333;font-family:sans-serif;padding:1em;}"
        "pre{white-space:pre-wrap;word-break:break-word;}h1{font-size:1.2em;}</style>"
        f"</head><body><h1>{safe_title}</h1><pre>{safe_message}</pre></body></html>"
    )


@app.core.get("/resources/maintenace/maintenance.php", response_class=fastapi.responses.HTMLResponse)
@app.core.get("/resources/maintenance/maintenance.php", response_class=fastapi.responses.HTMLResponse)
async def maintenance_page(request: fastapi.Request):
    if config.is_maintenance():
        return _template_bytes("maintenance.html")
    else:
        # Error?
        message = "No additional error message available"
        authorize = request.headers.get("authorize")
        if authorize is not None:
            authorize_decoded = dict(urllib.parse.parse_qsl(authorize))
            token = authorize_decoded.get("token")
            if token:
                exc = errhand.load_error(token.replace(" ", "+"))
                if exc:
                    message = "\n".join(exc)

        try:
            return app.templates.TemplateResponse(request, "error.html", {"error": message})
        except Exception:
            return _html_page("Maintenance information", message)


@app.core.get("/resources/maintenace/update.php", response_class=fastapi.responses.HTMLResponse)
@app.core.get("/resources/maintenance/update.php", response_class=fastapi.responses.HTMLResponse)
async def update_page(request: fastapi.Request):
    # Some SIF1 clients open this WebView immediately after server_info is loaded.
    # Returning a stable HTML page is safer than leaking a traceback into the
    # game's modal WebView when no real update announcement exists.
    try:
        return _template_bytes("update.html")
    except Exception:
        return _html_page("Update information", "No update notice is available on this private server.")


@app.core.get("/resources/maintenace/{path:path}", response_class=fastapi.responses.HTMLResponse)
@app.core.get("/resources/maintenance/{path:path}", response_class=fastapi.responses.HTMLResponse)
async def resource_notice_fallback(path: str):
    return _html_page("Information", "The requested notice page is not available: " + path)
