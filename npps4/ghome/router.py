"""Minimal Shengqu/GHome compatibility layer for the CN SIF1 client.

This module is not a full account platform.  It mirrors the behavior needed by
CN clients before they enter the normal /main.php SIF protocol, then maps GHome
accounts onto NPPS4's own local users.
"""

import base64
import hashlib
import json
import os
import re
import urllib.parse
from typing import Any

import fastapi
import Cryptodome.Cipher.DES3
import Cryptodome.Cipher.PKCS1_v1_5
import Cryptodome.Util.Padding

from .. import idoltype
from .. import util
from ..app import app
from ..config import config
from ..idol import session as idol_session
from ..system import user as user_system

router = fastapi.APIRouter()
_DEVICE_KEYS: dict[str, str] = {}
_ACCOUNT_FILE = os.path.join(config.get_data_directory(), "ghome_accounts.json")


def _read_accounts() -> dict[str, dict[str, Any]]:
    if not os.path.isfile(_ACCOUNT_FILE):
        return {}
    with open(_ACCOUNT_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_accounts(accounts: dict[str, dict[str, Any]]):
    os.makedirs(os.path.dirname(_ACCOUNT_FILE), exist_ok=True)
    tmp = _ACCOUNT_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(accounts, f, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp, _ACCOUNT_FILE)


def _device_id(request: fastapi.Request) -> str:
    return request.headers.get("X-DEVICEID") or request.headers.get("X-DeviceID") or "default-device"


def _normalize_phone(phone: str) -> str:
    phone = phone.strip()
    if not phone:
        return ""
    if "-" in phone:
        phone = phone.split("-", 1)[1].strip()
    return re.sub(r"\s+", "", phone)


def _json_response(payload: Any):
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return fastapi.responses.Response(
        body,
        status_code=200,
        media_type="application/json",
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "X-Message-Sign": util.sign_message(body, None),
            "X-Powered-By": "KLab Native APP Platform",
            "server_version": "20120129",
            "Server-Version": config.get_latest_version_string(),
            "version_up": "0",
            "status_code": "200",
        },
    )


def _ghome_resp(code: int = 0, msg: str = "ok", data: Any = None):
    return _json_response({"code": code, "msg": msg, "data": data if data is not None else {}})


def _maybe_encrypted_response(request: fastapi.Request, obj: dict[str, Any], code: int = 0, msg: str = "ok"):
    # GHome mixes plain JSON bootstrap endpoints and encrypted account endpoints.
    # When the client has completed /v1/basic/handshake, use the encrypted shape;
    # otherwise return the normal code/msg/data wrapper. This keeps optional stubs
    # from turning into 400/500 errors merely because they are called in a slightly
    # different SDK state.
    key = _DEVICE_KEYS.get(_device_id(request))
    if key is not None and len(key) >= 24:
        try:
            return _encrypted_json_response(request, obj, code, msg)
        except Exception:
            pass
    return _ghome_resp(code, msg, obj)


def _disabled_payload(message: str = "该功能在本地私服中不可用") -> dict[str, Any]:
    return {"result": 31, "message": message}


def _get_randkey(request: fastapi.Request) -> bytes:
    key = _DEVICE_KEYS.get(_device_id(request))
    if key is None or len(key) < 24:
        raise fastapi.HTTPException(400, detail="GHome randkey not initialized; call /v1/basic/handshake first")
    return key[:24].encode("utf-8")


def _des3_encrypt(data: bytes, key: bytes) -> str:
    cipher = Cryptodome.Cipher.DES3.new(key, Cryptodome.Cipher.DES3.MODE_ECB)
    encrypted = cipher.encrypt(Cryptodome.Util.Padding.pad(data, 8))
    return base64.b64encode(encrypted).decode("ascii")


def _des3_decrypt(data: bytes, key: bytes) -> bytes:
    cipher = Cryptodome.Cipher.DES3.new(key, Cryptodome.Cipher.DES3.MODE_ECB)
    return Cryptodome.Util.Padding.unpad(cipher.decrypt(data), 8)


def _encrypted_json_response(request: fastapi.Request, obj: dict[str, Any], code: int = 0, msg: str = "ok"):
    key = _get_randkey(request)
    data = _des3_encrypt(json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), key)
    return _ghome_resp(code, msg, data)


async def _decode_encrypted_form(request: fastapi.Request) -> dict[str, str]:
    raw = await request.body()
    if not raw:
        return {}
    decoded = base64.b64decode(raw.strip())
    plain = _des3_decrypt(decoded, _get_randkey(request)).decode("utf-8", "replace")
    plain = urllib.parse.unquote_plus(plain)
    parsed = urllib.parse.parse_qs(plain, keep_blank_values=True)
    return {k: v[-1] if v else "" for k, v in parsed.items()}


async def _get_or_create_user(phone: str, password: str) -> tuple[int, str, str, bool]:
    """Map a GHome account onto an ordinary NPPS4 login account.

    Important CN behavior: after GHome login, the game-layer /login/login uses
    the returned `userid` as login_key and `ticket` as login_passwd.  Do not
    weaken NPPS4's /login/login password check; instead keep NPPS4 intact by
    creating/updating a normal NPPS4 user whose key is exactly str(user_id) and
    whose current password is the latest GHome ticket.
    """
    accounts = _read_accounts()
    acct = accounts.get(phone)
    passwd_hash = hashlib.md5(password.encode("utf-8")).hexdigest()
    now = util.time()

    async with idol_session.BasicSchoolIdolContext(idoltype.Language.zh_cn) as ctx:
        u = None
        is_new = False

        if acct is not None:
            if acct.get("password_md5") != passwd_hash:
                raise ValueError("账号不存在或者密码有误！")
            # v2 stored an NPPS4 key; v3 stores the canonical user_id. Support
            # both so test databases can be upgraded in place.
            if acct.get("user_id"):
                u = await user_system.get(ctx, int(acct["user_id"]))
            if u is None and acct.get("npps4_key"):
                u = await user_system.find_by_key(ctx, acct["npps4_key"])

        if u is None:
            if not config.cn_autocreate_ghome_users():
                raise ValueError("账号不存在！")
            # Create a normal NPPS4 user, then set the login key to the numeric
            # id the CN client will later send to /login/login.
            u = await user_system.create(ctx, None, None)
            is_new = True
            u.name = "梦路"
            u.bio = "你好。"

        autokey = (acct or {}).get("autokey") or ("AUTO" + util.randbytes(16).hex().upper())
        ticket = f"9999999{u.id}{now}"
        # This is the key preservation point: existing NPPS4 /login/login can now
        # authenticate CN clients without any special-case bypass.
        u.key = str(u.id)
        u.set_passwd(ticket)

        accounts[phone] = {
            "user_id": u.id,
            "password_md5": passwd_hash,
            "autokey": autokey,
            "ticket": ticket,
            "last_login_time": now,
        }
        _write_accounts(accounts)
        return u.id, autokey, ticket, is_new


def _login_payload(user_id: int, autokey: str, ticket: str, is_new: bool) -> dict[str, Any]:
    return {
        "activation": 0,
        "autokey": autokey,
        "captchaParams": "",
        "checkCodeGuid": "",
        "checkCodeUrl": "",
        "hasExtendAccs": 0,
        "has_realInfo": 1,
        "imagecodeType": 0,
        "isNewUser": 1 if is_new else 0,
        "message": "ok",
        "nextAction": 0,
        "prompt_msg": "",
        "realInfoNotification": "",
        "realInfo_force": 1,
        "realInfo_force_pay": 0,
        "realInfo_status": 1,
        "realInfo_status_pay": 1,
        "result": 0,
        "sdg_height": 0,
        "sdg_width": 0,
        "ticket": ticket,
        "userAttribute": "0",
        "userid": user_id,
    }


@router.post("/v1/basic/publickey")
async def publickey():
    try:
        key = base64.b64encode(config.get_server_rsa().publickey().export_key(format="DER")).decode("ascii")
        data = {"result": 0, "message": "ok", "key": key, "method": "rsa"}
        return _ghome_resp(0, "ok", data)
    except Exception:
        return _ghome_resp(31, "公钥读取失败！", {"result": 31, "message": "公钥读取失败！"})


@router.post("/v1/basic/handshake")
async def handshake(request: fastapi.Request):
    raw = await request.body()
    try:
        encrypted = base64.b64decode(raw.strip())
        cipher = Cryptodome.Cipher.PKCS1_v1_5.new(config.get_server_rsa())
        plain = cipher.decrypt(encrypted, None)
        if not plain:
            raise ValueError("bad RSA payload")
        params = urllib.parse.parse_qs(plain.decode("utf-8", "replace"), keep_blank_values=True)
        randkey = params.get("randkey", [""])[-1]
        if len(randkey) < 24:
            raise ValueError("invalid randkey")
        _DEVICE_KEYS[_device_id(request)] = randkey
        token = {"message": "ok", "result": 0, "token": util.randbytes(17).hex().upper()[:33]}
        return _ghome_resp(0, "ok", _des3_encrypt(json.dumps(token, separators=(",", ":")).encode("utf-8"), randkey[:24].encode("utf-8")))
    except Exception as e:
        return _ghome_resp(31, str(e), "")


@router.post("/v1/account/initialize")
async def initialize(request: fastapi.Request):
    data = {
        "brand_logo": "http://gskd.sdo.com/ghome/ztc/logo/og/logo_xhdpi.png",
        "brand_name": "盛趣游戏",
        "force_show_agreement": 1,
        "greport_log_level": "off",
        "log_level": "off",
        "login_button": ["official"],
        "login_icon": [],
        "need_float_window_permission": 0,
        "new_device_id_server": hashlib.md5(_device_id(request).encode("utf-8")).hexdigest().upper(),
        "show_guest_confirm": 1,
        "voicetip_button": 1,
    }
    return _encrypted_json_response(request, data)


@router.post("/v1/account/login")
async def login(request: fastapi.Request):
    try:
        params = await _decode_encrypted_form(request)
        phone = _normalize_phone(params.get("phone", ""))
        password = params.get("password", "")
        if not phone or not password:
            raise ValueError("invalid login params")
        user_id, autokey, ticket, is_new = await _get_or_create_user(phone, password)
        return _encrypted_json_response(request, _login_payload(user_id, autokey, ticket, is_new), 0, "ok")
    except Exception as e:
        data = {"result": 31, "message": str(e)}
        return _encrypted_json_response(request, data, 31, str(e))


@router.post("/v1/account/loginauto")
async def login_auto(request: fastapi.Request):
    params = await _decode_encrypted_form(request)
    autokey = params.get("autokey", "")
    accounts = _read_accounts()
    for acct in accounts.values():
        if acct.get("autokey") == autokey:
            user_id = int(acct["user_id"])
            ticket = acct.get("ticket") or f"9999999{user_id}{util.time()}"
            # Keep the game-layer login password synchronized with the ticket.
            async with idol_session.BasicSchoolIdolContext(idoltype.Language.zh_cn) as ctx:
                u = await user_system.get(ctx, user_id)
                if u is not None:
                    u.key = str(u.id)
                    u.set_passwd(ticket)
            data = {"result": 0, "message": "ok", "autokey": autokey, "userid": str(user_id), "ticket": ticket}
            return _encrypted_json_response(request, data, 0, "ok")
    data = {"result": 31, "message": "账号不存在或者登陆状态已过期！"}
    return _encrypted_json_response(request, data, 31, data["message"])


@router.post("/v1/basic/loginarea")
async def login_area(userid: str = fastapi.Form(default="")):
    return _ghome_resp(0, "ok", {"userid": userid})


@router.post("/v1/account/active")
async def active():
    return _ghome_resp(0, "ok", {"message": "ok", "result": 0})


@router.post("/v1/account/reportRole")
async def report_role(request: fastapi.Request):
    return _encrypted_json_response(request, {"message": "ok"})


@router.post("/v1/basic/getProductList")
async def get_product_list():
    return _ghome_resp(1, "ok", {"message": [], "result": 0})


@router.get("/v1/basic/getcode")
@router.post("/v1/basic/getcode")
async def get_code():
    return _ghome_resp(0, "ok", {"codeArray": [], "codeVersion": "1.0.5"})


@router.post("/v1/guest/status")
async def guest_status():
    return _ghome_resp(0, "ok", {"disablead": 1, "loginswitch": 1, "message": "ok", "result": 0})


@router.get("/agreement/all")
async def agreement_all():
    return _json_response({"return_code": 0, "error_type": 0, "return_message": "", "data": {}})


@router.get("/integration/appReport/initialize")
async def app_report_initialize():
    return _json_response({"code": 0, "msg": "", "data": {"needReport": 0}})


@router.post("/v1/basic/checktoken")
async def check_token(request: fastapi.Request):
    return _maybe_encrypted_response(request, {"result": 0, "message": "ok"}, 0, "ok")


@router.get("/v1/basic/countrycode")
@router.post("/v1/basic/countrycode")
async def country_code():
    return _ghome_resp(0, "ok", {"result": 0, "message": "ok", "countryCodeList": [{"code": "86", "name": "中国大陆"}]})


@router.get("/v1/basic/getAreaList")
@router.post("/v1/basic/getAreaList")
async def get_area_list():
    return _ghome_resp(0, "ok", {"result": 0, "message": "ok", "areaList": [{"areaId": "1", "areaName": "默认区", "groupId": ""}]})


@router.get("/v1/basic/getPackageUrl")
@router.post("/v1/basic/getPackageUrl")
async def get_package_url(request: fastapi.Request, gameVersion: str = ""):
    # The SDK treats this as an optional app-package update check.  Point it at
    # the local server rather than an external CDN, but mark it as not required.
    base = str(request.base_url).rstrip("/")
    return _ghome_resp(0, "ok", {"result": 0, "message": "ok", "url": "", "packageUrl": "", "server": base, "force": 0, "gameVersion": gameVersion})


@router.get("/v1/basic/getadinfo")
@router.post("/v1/basic/getadinfo")
async def get_ad_info():
    return _ghome_resp(0, "ok", {"result": 0, "message": "ok", "adList": []})


@router.get("/v1/basic/game/error")
@router.post("/v1/basic/game/error")
async def game_error_report():
    return _ghome_resp(0, "ok", {"result": 0, "message": "ok"})


@router.post("/v1/basic/smssend")
@router.post("/v1/basic/picCheckSmsSend2")
async def sms_send_disabled(request: fastapi.Request):
    return _maybe_encrypted_response(request, _disabled_payload(), 31, "unsupported")


@router.post("/v1/account/logout")
async def logout(request: fastapi.Request):
    return _maybe_encrypted_response(request, {"result": 0, "message": "ok"}, 0, "ok")


@router.post("/v1/account/status")
async def account_status(request: fastapi.Request):
    return _maybe_encrypted_response(request, {"result": 0, "message": "ok", "status": 1}, 0, "ok")


@router.post("/v1/account/register")
@router.post("/v1/account/sendcaptcha")
@router.post("/v1/account/smsLogin")
@router.post("/v1/account/fillRealInfo")
@router.post("/v1/account/checkCodeAuth")
@router.post("/v1/account/checkCodeLogin")
@router.post("/v1/account/resetpasswdlogin")
@router.post("/v1/account/setAccPassword")
@router.post("/v1/account/smsAuth")
@router.post("/v1/account/pwdAuth")
@router.post("/v1/account/guestLogin")
@router.post("/v1/account/guestUpgradeLogin")
@router.post("/v1/account/thirdAccountBindPhone")
@router.post("/v1/account/thirdAccountChangePhone")
@router.post("/v1/account/thirdAccountTicketLogin")
@router.post("/v1/account/thirdRealInfoBindPhone")
@router.post("/v1/account/acctDeletionInitialize")
@router.post("/v1/account/checkRealInfo4AcctDeletion")
@router.post("/v1/account/checkSmsCode4AcctDeletion")
@router.post("/v1/account/comfirmAcctDeletion")
@router.post("/v1/account/activation")
@router.post("/v1/account/extendAccLogin")
@router.post("/v1/account/modifyExtendAcc")
@router.post("/v1/account/queryExtendAcc")
@router.post("/v1/account/daoyuAuthLogin")
async def account_optional_disabled(request: fastapi.Request):
    return _maybe_encrypted_response(request, _disabled_payload(), 31, "unsupported")


@router.get("/agreement/content")
@router.post("/agreement/content")
@router.get("/agreement/user")
@router.post("/agreement/user")
async def agreement_optional():
    return _json_response({"return_code": 0, "error_type": 0, "return_message": "", "data": {"content": ""}})


@router.get("/v1/pay/status")
@router.post("/v1/pay/status")
@router.post("/v1/pay/entrance")
@router.post("/v1/pay/params")
@router.post("/v1/gchannel/pay/purchase")
@router.get("/v1/gchannel/pay/orderstatus")
@router.post("/v1/gchannel/pay/orderstatus")
@router.get("/v1/gchannel/third/pay/alisimple/order")
@router.post("/v1/gchannel/third/pay/alisimple/order")
@router.get("/hps4gpay/qrcode/confirm")
@router.post("/hps4gpay/qrcode/confirm")
async def pay_disabled(request: fastapi.Request):
    return _maybe_encrypted_response(request, _disabled_payload("支付功能在本地私服中不可用"), 31, "unsupported")


@router.post("/v1/gqrcode/scan")
@router.post("/v1/gqrcode/confirm")
@router.post("/v1/gqrcode/cancelQRCode")
async def qrcode_disabled(request: fastapi.Request):
    return _maybe_encrypted_response(request, _disabled_payload("二维码登录在本地私服中不可用"), 31, "unsupported")


@router.get("/v1/open/getticket2")
@router.post("/v1/open/getticket2")
async def open_ticket_disabled(request: fastapi.Request):
    return _maybe_encrypted_response(request, _disabled_payload(), 31, "unsupported")


@router.get("/v1/ioschannel/queryChannelInfo")
@router.post("/v1/ioschannel/queryChannelInfo")
@router.get("/v1/gchannel/basic/getGameChannelClientCfg")
@router.post("/v1/gchannel/basic/getGameChannelClientCfg")
async def channel_info_stub(request: fastapi.Request):
    return _maybe_encrypted_response(request, {"result": 0, "message": "ok"}, 0, "ok")


@router.api_route("/v1/{path:path}", methods=["GET", "POST"])
async def v1_fallback(path: str, request: fastapi.Request):
    util.log("GHome optional fallback", {"path": "/v1/" + path, "method": request.method}, severity=util.logging.INFO)
    return _maybe_encrypted_response(request, _disabled_payload(), 31, "unsupported")


@router.api_route("/agreement/{path:path}", methods=["GET", "POST"])
async def agreement_fallback(path: str):
    return _json_response({"return_code": 0, "error_type": 0, "return_message": "", "data": {}})


@router.api_route("/integration/{path:path}", methods=["GET", "POST"])
async def integration_fallback(path: str):
    return _json_response({"code": 0, "msg": "", "data": {}})


@router.api_route("/hps4gpay/{path:path}", methods=["GET", "POST"])
async def hps4gpay_fallback(path: str, request: fastapi.Request):
    return _maybe_encrypted_response(request, _disabled_payload("支付功能在本地私服中不可用"), 31, "unsupported")


@router.post("/report/ge/app")
async def report_ge_app():
    return fastapi.responses.Response(status_code=200)


app.core.include_router(router)
