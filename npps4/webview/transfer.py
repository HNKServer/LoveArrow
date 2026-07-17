from __future__ import annotations

import fastapi
import fastapi.responses
import sqlalchemy

from .. import idol
from ..app import app
from ..db import main
from ..system import handover
from ..system import transfer_web


async def _load_user(context: idol.BasicSchoolIdolContext, token: str) -> main.User:
    try:
        user_id = transfer_web.load_token(token)
    except ValueError as exc:
        raise fastapi.HTTPException(403, detail=str(exc)) from exc
    user = await context.db.main.get(main.User, user_id)
    if user is None:
        raise fastapi.HTTPException(404, detail="user not found")
    return user


def _render(request: fastapi.Request, token: str, user: main.User, *, code: str | None = None, message: str = ""):
    return app.templates.TemplateResponse(
        request,
        "transfer.html",
        {
            "token": token,
            "invite_code": user.invite_code,
            "registered": user.transfer_sha1 is not None,
            "generated_code": code,
            "message": message,
        },
    )


@app.core.get("/transfer", response_class=fastapi.responses.HTMLResponse, include_in_schema=False)
async def transfer_page(request: fastapi.Request, t: str):
    async with idol.create_basic_context(request) as context:
        user = await _load_user(context, t)
        return _render(request, t, user)


@app.core.post("/transfer/reserve", response_class=fastapi.responses.HTMLResponse, include_in_schema=False)
async def transfer_reserve(request: fastapi.Request, t: str = fastapi.Form(...)):
    async with idol.create_basic_context(request) as context:
        user = await _load_user(context, t)
        code = handover.generate_transfer_code()
        user.transfer_sha1 = handover.generate_passcode_sha1(user.invite_code, code)
        await context.db.main.flush()
        return _render(request, t, user, code=code, message="新的迁移密码已生成。请立即保存，页面关闭后无法再次查看。")


@app.core.post("/transfer/abort", response_class=fastapi.responses.HTMLResponse, include_in_schema=False)
async def transfer_abort(request: fastapi.Request, t: str = fastapi.Form(...)):
    async with idol.create_basic_context(request) as context:
        user = await _load_user(context, t)
        user.transfer_sha1 = None
        await context.db.main.flush()
        return _render(request, t, user, message="现有迁移密码已作废。")


@app.core.post("/transfer/execute", response_class=fastapi.responses.HTMLResponse, include_in_schema=False)
async def transfer_execute(
    request: fastapi.Request,
    t: str = fastapi.Form(...),
    handover_id: str = fastapi.Form(...),
    handover_code: str = fastapi.Form(...),
):
    async with idol.create_basic_context(request) as context:
        current_user = await _load_user(context, t)
        digest = handover.generate_passcode_sha1(handover_id.strip(), handover_code.strip().upper())
        target_user = await handover.find_user_by_passcode(context, digest)
        if target_user is None:
            return _render(request, t, current_user, message="迁移 ID 或迁移密码不正确。")
        if target_user.locked:
            return _render(request, t, current_user, message="目标账号已被锁定，无法迁移。")
        if target_user.id == current_user.id:
            return _render(request, t, current_user, message="不能把数据迁移到当前同一账号。")

        handover.swap_credentials(current_user, target_user)
        target_user.transfer_sha1 = None
        # The game API invalidates the current session.  A WebView operation has
        # no game-session token of its own, so invalidate both users' saved
        # sessions and force the client to log in with the newly swapped key.
        await context.db.main.execute(
            sqlalchemy.delete(main.Session).where(main.Session.user_id.in_([current_user.id, target_user.id]))
        )
        await context.db.main.flush()
        return _render(
            request,
            transfer_web.make_token(target_user.id),
            target_user,
            message="数据迁移已完成。请彻底关闭并重新启动游戏。迁移密码已经自动失效。",
        )
