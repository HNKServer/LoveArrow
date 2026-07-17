import fastapi
import fastapi.responses

from ..app import app


@app.core.get("/manga", response_class=fastapi.responses.HTMLResponse, include_in_schema=False)
async def manga_page(request: fastapi.Request):
    return app.templates.TemplateResponse(request, "manga.html", {})
