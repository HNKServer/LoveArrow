import fastapi.responses

from .. import util
from ..app import app


@app.webview.get("/announce/index")
def announce_index():
    """Use NPPS4's API documentation as the post-service announcement page.

    This is the original NPPS4 design, not an accidental Swagger leak.  The
    login announcement and the home WebView banner both intentionally land on
    the same useful server-status/API page.
    """
    util.stub("announce", "index")
    return fastapi.responses.RedirectResponse("/main.php/api", 302)


@app.webview.get("/announce/index/")
def announce_index_slash():
    return announce_index()
