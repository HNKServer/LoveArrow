import base64

from .. import const
from .. import idol
from .. import util
from ..config import config
from ..db import main
from ..system import achievement
from ..system import common
from ..system import friend
from ..system import greet
from ..system import onboarding
from ..system import reward
from ..system import tutorial
from ..system import unit
from ..system import user
from ..idol import cache
from ..idol import error
from ..idol import session
from ..idol.core import _decode_request_data_value, _pick_authkey_candidate

import fastapi
import pydantic


class LoginRequest(pydantic.BaseModel):
    login_key: str
    login_passwd: str
    devtoken: str | None = None


class LoginResponse(common.TimestampMixin):
    authorize_token: str
    user_id: int
    review_version: str = ""
    idfa_enabled: bool = False
    skip_login_news: bool = False


class AuthkeyRequest(pydantic.BaseModel):
    # CN 9.7.x request bodies are not perfectly stable across environments:
    # some builds send request_data={dummy_token:...}, some direct form fields,
    # and some camelCase names.  Normalize these shapes before normal Pydantic
    # validation so FastAPI does not turn a compatible client request into 422.
    model_config = pydantic.ConfigDict(populate_by_name=True, extra="allow")

    dummy_token: str = pydantic.Field(default="", alias="dummyToken")
    auth_data: str | None = pydantic.Field(default="", alias="authData")

    @pydantic.model_validator(mode="before")
    @classmethod
    def _normalize_cn_authkey(cls, data):
        if not isinstance(data, dict):
            return data
        data = dict(data)

        # Unwrap common containers used by SIF/CN compatibility middleware.
        for wrapper_key in ("request_data", "RequestData", "requestData", "data", "body"):
            wrapped = data.get(wrapper_key)
            if isinstance(wrapped, dict):
                merged = dict(wrapped)
                merged.update({k: v for k, v in data.items() if k not in merged})
                data = merged
                break

        # Accept both snake_case and camelCase spellings.
        if "dummy_token" not in data:
            for key in ("dummyToken", "dummy", "dummy_token_base64"):
                if key in data:
                    data["dummy_token"] = data[key]
                    break
        if "auth_data" not in data:
            for key in ("authData", "auth", "auth_data_base64"):
                if key in data:
                    data["auth_data"] = data[key]
                    break

        # Base64 sent through x-www-form-urlencoded can occasionally arrive with
        # spaces instead of plus signs.  Fix that here rather than failing later.
        for key in ("dummy_token", "auth_data"):
            value = data.get(key)
            if isinstance(value, str):
                data[key] = value.replace(" ", "+")

        data.setdefault("auth_data", "")
        return data


class AuthkeyResponse(pydantic.BaseModel):
    authorize_token: str
    dummy_token: str


class StartupResponse(pydantic.BaseModel):
    user_id: str


class LicenseInfo(pydantic.BaseModel):
    license_list: list
    licensed_info: list
    expired_info: list
    badge_flag: bool


class TopInfoResponse(common.TimestampMixin):
    friend_action_cnt: int
    friend_greet_cnt: int
    friend_variety_cnt: int
    friend_new_cnt: int
    present_cnt: int
    secret_box_badge_flag: bool
    server_datetime: str
    notice_friend_datetime: str
    notice_mail_datetime: str
    friends_approval_wait_cnt: int
    friends_request_cnt: int
    is_today_birthday: bool
    license_info: LicenseInfo
    using_buff_info: list
    is_klab_id_task_flag: bool
    klab_id_task_can_sync: bool
    has_unread_announce: bool
    exchange_badge_cnt: list[int]
    ad_flag: bool
    has_ad_reward: bool


class NotificationStatus(pydantic.BaseModel):
    push: bool
    lp: bool
    update_info: bool
    campaign: bool
    live: bool
    lbonus: bool
    event: bool
    secretbox: bool
    birthday: bool


class TopInfoOnceResponse(pydantic.BaseModel):
    new_achievement_cnt: int
    unaccomplished_achievement_cnt: int
    live_daily_reward_exist: bool
    training_energy: int
    training_energy_max: int
    notification: NotificationStatus
    open_arena: bool
    costume_status: bool
    open_accessory: bool
    arena_si_skill_unique_check: bool
    open_v98: bool


class StarterUnitListInfo(pydantic.BaseModel):
    unit_id: int
    is_rank_max: bool


class StarterUnitInitialSetInfo(pydantic.BaseModel):
    unit_initial_set_id: int
    unit_list: list[StarterUnitListInfo]
    center_unit_id: int


class StarterMemberCategory(pydantic.BaseModel):
    member_category: int
    unit_initial_set: list[StarterUnitInitialSetInfo]


class StarterUnitListResponse(pydantic.BaseModel):
    member_category_list: list[StarterMemberCategory]


class StarterUnitSelectRequest(pydantic.BaseModel):
    unit_initial_set_id: int


class StarterUnitSelectResponse(pydantic.BaseModel):
    unit_id: list[int]


@idol.register("login", "login", check_version=False, batchable=False)
async def login_login(context: idol.SchoolIdolAuthParams, request: LoginRequest) -> LoginResponse:
    """Login user"""

    assert context.token is not None
    # Decrypt credentials
    key = util.xorbytes(context.token.client_key[:16], context.token.server_key[:16])
    loginkey = util.decrypt_aes(key, base64.b64decode(request.login_key))
    passwd = util.decrypt_aes(key, base64.b64decode(request.login_passwd))

    # Log
    util.log("Login credentials decrypted", "login_key=<redacted>", "password=<redacted>")

    # Find user
    u = await user.find_by_key(context, str(loginkey, "UTF-8"))
    if u is None or (not u.check_passwd(str(passwd, "UTF-8"))):
        # This will send "Your data has been transfered succesfully" message to the SIF client.
        raise error.IdolError(error_code=407, status_code=600, detail="Login not found")

    # Login
    await session.invalidate_current(context)
    if u.locked:
        raise idol.error.locked()

    token = await session.encapsulate_token(context, context.token.server_key, context.token.client_key, u.id)
    await cache.clear(context, u.id)
    await onboarding.repair_v434_v437_completed_empty(context, u)
    return LoginResponse(authorize_token=token, user_id=u.id)


async def _recover_cn_authkey_request(context: idol.SchoolIdolParams, request: AuthkeyRequest) -> AuthkeyRequest:
    """Recover dummy_token from the raw HTTP request when validation used defaults.

    This is a defensive CN compatibility path.  Some Android stacks combine
    multipart/form-data, x-www-form-urlencoded, and request_data wrappers in a
    way that can leave the Pydantic object with an empty default even though the
    real payload is present in the raw form/body.
    """
    if request.dummy_token:
        return request

    raw = None
    try:
        form = await context.request.form()
        for key in ("request_data", "RequestData", "requestData", "data", "body"):
            value = form.get(key)
            if value is not None:
                raw = str(value)
                break
        if raw is None and form:
            raw = dict(form)
    except Exception:
        raw = None

    if raw is None:
        try:
            body = await context.request.body()
            raw = body if body else None
        except Exception:
            raw = None

    data = _decode_request_data_value(raw) if raw not in (None, "") else {}
    candidate = _pick_authkey_candidate(data)
    if candidate:
        return AuthkeyRequest.model_validate(candidate)
    return request


@idol.register("login", "authkey", check_version=False, batchable=False, xmc_verify=idol.XMCVerifyMode.NONE)
async def login_authkey(context: idol.SchoolIdolParams, request: AuthkeyRequest) -> AuthkeyResponse:
    """Generate authentication key."""

    request = await _recover_cn_authkey_request(context, request)
    dummy_token = (request.dummy_token or "").replace(" ", "+")
    auth_data = (request.auth_data or "").replace(" ", "+")

    # Decrypt client key.  Some CN client builds follow honoka-chan's observed
    # behavior and provide only dummy_token; auth_data is either absent or not
    # useful for the server-side session.  NPPS4 still requires the RSA-encrypted
    # client key because /login/login later uses it to decrypt login_key and
    # login_passwd, but auth_data itself can be safely ignored when absent.
    try:
        client_key, server_rsa_label = util.decrypt_rsa_any(base64.b64decode(dummy_token))
        context.server_rsa_label = server_rsa_label
    except Exception as e:
        raise fastapi.HTTPException(400, f"Bad client key: {e}") from None
    if not client_key:
        raise fastapi.HTTPException(400, "Bad client key")

    # Preserve original behavior for clients that do send auth_data, but do not
    # make CN startup fail if it is missing or malformed.  honoka-chan also
    # ignores this decrypted value.
    if auth_data:
        try:
            util.decrypt_aes(client_key[:16], base64.b64decode(auth_data))
        except Exception as e:
            util.log("Ignoring invalid login/authkey auth_data", e=e, severity=util.logging.DEBUG)

    # Create new token
    server_key = util.randbytes(32)
    token = await session.encapsulate_token(context, server_key, client_key)

    # Return response
    return AuthkeyResponse(
        authorize_token=token,
        dummy_token=str(base64.b64encode(server_key), "UTF-8"),
    )


@idol.register("login", "startUp", check_version=False, batchable=False)
async def login_startup(context: idol.SchoolIdolAuthParams, request: LoginRequest) -> StartupResponse:
    """Register new account."""

    assert context.token is not None
    key = util.xorbytes(context.token.client_key[:16], context.token.server_key[:16])
    loginkey = util.decrypt_aes(key, base64.b64decode(request.login_key))
    passwd = util.decrypt_aes(key, base64.b64decode(request.login_passwd))

    # Log
    util.log("Login credentials decrypted", "login_key=<redacted>", "password=<redacted>")

    # Create user
    u = await user.create(context, str(loginkey, "UTF-8"), str(passwd, "UTF-8"))
    await session.invalidate_current(context)
    return StartupResponse(user_id=str(u.id))


@idol.register("login", "topInfo")
async def login_topinfo(context: idol.SchoolIdolUserParams) -> TopInfoResponse:
    # TODO
    util.stub("login", "topInfo", context.raw_request_data)
    current_user = await user.get_current(context)
    return TopInfoResponse(
        friend_action_cnt=await friend.count_by_status(context, current_user, const.FRIEND_STATUS.APPROVAL_WAIT),
        friend_greet_cnt=await greet.count_unread_received(context, current_user),
        friend_variety_cnt=0,
        friend_new_cnt=await friend.count_by_status(context, current_user, const.FRIEND_STATUS.FRIEND),
        present_cnt=await reward.count_presentbox(context, current_user),
        secret_box_badge_flag=False,
        server_datetime=util.timestamp_to_datetime(),
        notice_friend_datetime=util.timestamp_to_datetime(86400),
        notice_mail_datetime=util.timestamp_to_datetime(86400),
        friends_approval_wait_cnt=await friend.count_by_status(context, current_user, const.FRIEND_STATUS.APPROVAL_WAIT),
        friends_request_cnt=await friend.count_by_status(context, current_user, const.FRIEND_STATUS.PENDING),
        is_today_birthday=False,
        license_info=LicenseInfo(license_list=[], licensed_info=[], expired_info=[], badge_flag=False),
        using_buff_info=[],
        is_klab_id_task_flag=False,
        klab_id_task_can_sync=False,
        has_unread_announce=False,
        exchange_badge_cnt=[135, 41, 345],
        ad_flag=False,
        has_ad_reward=False,
    )


@idol.register("login", "topInfoOnce")
async def login_topinfoonce(context: idol.SchoolIdolUserParams) -> TopInfoOnceResponse:
    current_user = await user.get_current(context)
    # TODO
    util.stub("login", "topInfoOnce", context.raw_request_data)
    return TopInfoOnceResponse(
        new_achievement_cnt=0,
        unaccomplished_achievement_cnt=await achievement.get_achievement_count(context, current_user, False),
        live_daily_reward_exist=False,
        training_energy=current_user.training_energy,
        training_energy_max=current_user.training_energy_max,
        notification=NotificationStatus(
            push=True,
            lp=False,
            update_info=False,
            campaign=False,
            live=False,
            lbonus=False,
            event=True,
            secretbox=True,
            birthday=True,
        ),
        # Do not advertise menus whose client-visible route families are absent.
        # Arena has no implemented handlers; costume only has the boot-time list
        # endpoint but lacks status/dress-up/make operations.  Accessory stays
        # enabled because list, tab, wear and favorite mutations are real.
        open_arena=False,
        costume_status=False,
        open_accessory=True,
        arena_si_skill_unique_check=False,
        open_v98=True,
    )


TEMPLATE_DECK = [13, 9, 8, 23, 0, 24, 21, 20, 19]
INITIAL_UNIT_IDS = [
    # Unfortunately the game doesn't preload the R card asset anymore.
    # so this is not configurable.
    # Myus
    [1131, 1789, 378, 1997, 2085, 703, 367, 330, 1912],  # UR
    # range(49, 58),  # R
    # Aqua
    [1308, 1813, 1298, 2158, 1743, 2200, 2310, 2236, 1372],  # UR
    # range(788, 797),  # R
]


def _generate_deck_list(unit_id: int):
    template_copy = TEMPLATE_DECK.copy()
    template_copy[4] = unit_id
    return template_copy


@idol.register("login", "unitList")
async def login_unitlist(context: idol.SchoolIdolUserParams) -> StarterUnitListResponse:
    return StarterUnitListResponse(
        member_category_list=[
            StarterMemberCategory(
                member_category=catid,
                unit_initial_set=[
                    StarterUnitInitialSetInfo(
                        unit_initial_set_id=initial_id,
                        unit_list=[
                            StarterUnitListInfo(unit_id=uid, is_rank_max=uid == center_uid)
                            for uid in _generate_deck_list(center_uid)
                        ],
                        center_unit_id=center_uid,
                    )
                    for initial_id, center_uid in enumerate(unit_list, 1 + (catid - 1) * 9)
                ],
            )
            for catid, unit_list in enumerate(INITIAL_UNIT_IDS, 1)
        ]
    )


@idol.register("login", "unitSelect")
async def login_unitselect(
    context: idol.SchoolIdolUserParams, request: StarterUnitSelectRequest
) -> StarterUnitSelectResponse:
    if request.unit_initial_set_id not in range(1, 19):
        raise error.IdolError(detail="Out of range")

    target = request.unit_initial_set_id - 1
    unit_ids = _generate_deck_list(INITIAL_UNIT_IDS[target // 9][target % 9])
    current_user = await user.get_current(context)

    if not config.is_cn_compat():
        # Preserve upstream NPPS4 behavior for its native clients.
        if current_user.tutorial_state != 1:
            raise error.IdolError(detail="Invalid tutorial state")

        units: list[main.Unit] = []
        for uid in unit_ids:
            unit_object = await unit.add_unit_simple(context, current_user, uid, True)
            if unit_object is None:
                raise RuntimeError("unable to add units")
            units.append(unit_object)

        center = units[4]
        await unit.idolize(context, current_user, center)
        await unit.set_unit_center(context, current_user, center)
        deck, _ = await unit.load_unit_deck(context, current_user, 1, True)
        await unit.save_unit_deck(context, current_user, deck, [item.id for item in units])
        return StarterUnitSelectResponse(unit_id=unit_ids)

    snapshot = await onboarding.snapshot(context, current_user)
    onboarding.log_snapshot(
        f"unitSelect-before set={request.unit_initial_set_id}", current_user, snapshot
    )

    if current_user.tutorial_state == 0:
        # Accept a CN retry which reaches unitSelect before the preceding
        # progress response was committed, but still run NPPS4 phase 1.
        await tutorial.phase1(context, current_user)
        await context.db.main.flush()
    elif current_user.tutorial_state == -1:
        if onboarding.deck_matches_master_ids(snapshot, unit_ids):
            await onboarding.require_starter_postconditions(
                context, current_user, unit_ids, expected_tutorial_state=None
            )
            util.log(
                "CN unitSelect idempotent completed-account retry",
                f"user={current_user.id}",
                f"set={request.unit_initial_set_id}",
                severity=util.logging.WARNING,
            )
            return StarterUnitSelectResponse(unit_id=unit_ids)

        is_v437_empty = onboarding.is_v434_v437_completed_empty(
            current_user, snapshot
        )
        if not is_v437_empty:
            raise error.IdolError(detail="Invalid tutorial state")
        current_user.tutorial_state = 1
        await context.db.main.flush()
    elif current_user.tutorial_state in (2, 3):
        if onboarding.deck_matches_master_ids(snapshot, unit_ids):
            await onboarding.require_starter_postconditions(
                context, current_user, unit_ids, expected_tutorial_state=None
            )
            return StarterUnitSelectResponse(unit_id=unit_ids)
        raise error.IdolError(detail="Invalid tutorial state")
    elif current_user.tutorial_state != 1:
        raise error.IdolError(detail="Invalid tutorial state")

    await onboarding.ensure_starter_roster_and_deck(context, current_user, unit_ids)
    after = await onboarding.require_starter_postconditions(context, current_user, unit_ids)
    onboarding.log_snapshot(
        f"unitSelect-after set={request.unit_initial_set_id}", current_user, after
    )
    return StarterUnitSelectResponse(unit_id=unit_ids)

