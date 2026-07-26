import asyncio
import base64
import dataclasses
import pickle
import urllib.parse

import fastapi
import itsdangerous
import sqlalchemy

from . import database
from . import session
from .. import client_profile
from .. import idoltype
from .. import util
from ..config import config
from ..db import main

from typing import Annotated, Any, Callable, cast, overload, override


def _parse_client_version_header(client_version: str) -> tuple[int, int]:
    """Accept both NPPS4's two-part version and Android's three-part package version."""
    try:
        return util.parse_sif_version(client_version)
    except Exception as e:
        raise fastapi.HTTPException(422, detail=f"Invalid Client-Version: {client_version!r}: {e}") from None


class BasicSchoolIdolContext:
    """Context object used only to access the database function."""

    def __init__(
        self,
        lang: idoltype.Language | str = idoltype.Language.jp,
        profile: client_profile.ClientProfile | str | None = None,
    ):
        self.lang = idoltype.normalize_language(lang)
        self.profile = (
            config.get_default_profile()
            if profile is None
            else client_profile.ClientProfile.normalize(profile)
        )
        # FastAPI executes each request in its own task/context.  Keep the
        # profile selected for the complete request, including client_check()
        # calls which run between the two async-with database scopes.
        client_profile.set_current(self.profile)
        self.db = database.Database(self.profile)
        self.cache: dict[str, dict[Any, Any]] = {}
        # Which server RSA private key matched this client.  The authkey
        # endpoint auto-detects it, and later authenticated responses reuse it
        # so GL/JP clients and honoka-chan/CN clients can coexist.
        self.server_rsa_label: str | None = None

    def select_profile(self, profile: client_profile.ClientProfile | str) -> client_profile.ClientProfile:
        """Select the request profile before any profile-specific master access.

        The main account/session database is shared.  Authkey may therefore
        refine the temporary pre-login default after decrypting the client key,
        and authenticated requests may adopt the profile stored in their signed
        session token.  Updating ``Database.profile`` keeps all lazily-created
        master sessions in the same resolved profile.
        """
        normalized = client_profile.ClientProfile.normalize(profile)
        self.profile = normalized
        self.db.profile = normalized
        client_profile.set_current(normalized)
        return normalized

    async def __aenter__(self):
        mainsession = self.db.main
        if mainsession.bind.dialect.name == "sqlite":
            # HACK: Set busy timeout to 25s
            await mainsession.execute(sqlalchemy.text("PRAGMA busy_timeout=25000"))
            # HACK: Increase WAL page size to 100000
            await mainsession.execute(sqlalchemy.text("PRAGMA wal_autocheckpoint=100000"))
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.cache.clear()

        try:
            if exc_type is None:
                await self.db.commit()
            else:
                await self.db.rollback()
        except:
            await self.db.rollback()
            raise
        finally:
            await self.db.cleanup()

    def is_lang_jp(self):
        return self.lang == idoltype.Language.jp

    def is_lang_cn(self):
        return self.lang in (idoltype.Language.zh_cn, idoltype.Language.zh_tw)

    @overload
    def get_text(self, text_jp: str, text_en: str | None, text_cn: str | None = None) -> str: ...

    @overload
    def get_text(self, text_jp: str | None, text_en: str | None, text_cn: str | None = None) -> str | None: ...

    def get_text(self, text_jp: str | None, text_en: str | None, text_cn: str | None = None):
        if self.is_lang_jp():
            return text_jp
        if self.is_lang_cn():
            return text_cn if text_cn is not None else (text_jp if text_jp is not None else text_en)
        return text_en if text_en is not None else text_jp

    async def finalize(self):
        pass

    def get_cache(self, key: str, id: Any):
        if key in self.cache and id in self.cache[key]:
            return self.cache[key][id]
        return None

    def set_cache(self, key: str, id: Any, value: Any):
        if key in self.cache:
            k: dict[Any, Any] = self.cache[key]
        else:
            k = {}
            self.cache[key] = k
        k[id] = value

    def support_background_task(self) -> bool:
        return False

    def add_task[**P](self, func: Callable[P, Any], *args: P.args, **kwargs: P.kwargs):
        raise NotImplementedError("not implemented for basic context")


class SchoolIdolParams(BasicSchoolIdolContext):
    """Context object used for unauthenticated request."""

    def __init__(
        self,
        request: fastapi.Request,
        background_task: fastapi.BackgroundTasks,
        authorize: Annotated[str, fastapi.Header(alias="Authorize")],
        client_version: Annotated[str, fastapi.Header(alias="Client-Version")],
        lang: Annotated[str, fastapi.Header(alias="LANG")],
        platform_type: Annotated[idoltype.PlatformType, fastapi.Header(alias="Platform-Type")],
        request_data: bytes | None = fastapi.Form(default=None, exclude=True, include=False),
    ):
        authorize_parsed = dict(urllib.parse.parse_qsl(authorize))
        util.log(
            "Authorize header",
            f"consumerKey={authorize_parsed.get('consumerKey', '')}",
            f"nonce={authorize_parsed.get('nonce', '')}",
            f"token_present={bool(authorize_parsed.get('token'))}",
        )
        if authorize_parsed.get("consumerKey") != "lovelive_test":
            raise fastapi.HTTPException(422, detail="Invalid consumerKey")

        self.client_version = _parse_client_version_header(client_version)
        detected_profile = client_profile.detect(
            client_version=self.client_version,
            explicit_header=request.headers.get("X-NPPS4-Profile"),
            request_path=request.url.path,
            default=config.get_default_profile(),
        )
        if not config.profile_enabled(detected_profile):
            raise fastapi.HTTPException(503, detail=f"{detected_profile.value.upper()} client profile is disabled")

        try:
            self.nonce = int(authorize_parsed.get("nonce", 0))
        except ValueError:
            self.nonce = 0

        self.token_text = authorize_parsed.get("token")
        self.token: session.TokenData | None = None

        ts = util.time()
        try:
            self.timestamp = int(authorize_parsed.get("timeStamp", ts))
        except ValueError:
            self.timestamp = ts

        self.platform = platform_type
        self.x_message_code = request.headers.get("X-Message-Code")
        self.request = request
        self.bgtasks = background_task
        # Note: Due to how FastAPI works, the `request_data` form is retrieved TWICE!
        # One in here, retrieved as raw bytes, and the other one is in _get_request_data
        # as Pydantic model.
        #
        # CN/GL Android builds normally send a form field named `request_data`,
        # but some patched/embedded transports can preserve the raw body while
        # FastAPI's form dependency sees None.  Keep the best available bytes
        # so X-Message-Code verification and compatibility recovery don't turn
        # a valid request into an HTTP 422.
        if request_data is None:
            self.raw_request_data = b""
        elif isinstance(request_data, bytes):
            self.raw_request_data = request_data
        else:
            self.raw_request_data = str(request_data).encode("utf-8", "replace")

        super().__init__(lang, detected_profile)

    def support_background_task(self):
        return True

    def add_task[**P](self, func: Callable[P, Any], *args: P.args, **kwargs: P.kwargs):
        return self.bgtasks.add_task(func, *args, **kwargs)


class SchoolIdolAuthParams(SchoolIdolParams):
    """Context object used for initially authenticated request.

    Initially authenticated means there's no user associated with it.
    """

    def __init__(
        self,
        request: fastapi.Request,
        background_task: fastapi.BackgroundTasks,
        authorize: Annotated[str, fastapi.Header(alias="Authorize")],
        client_version: Annotated[str, fastapi.Header(alias="Client-Version")],
        lang: Annotated[str, fastapi.Header(alias="LANG")],
        platform_type: Annotated[idoltype.PlatformType, fastapi.Header(alias="Platform-Type")],
        request_data: bytes | None = fastapi.Form(default=None, exclude=True, include=False),
    ):
        super().__init__(request, background_task, authorize, client_version, lang, platform_type, request_data)
        self.token_async = None

    @override
    async def finalize(self):
        if self.token_text is not None:
            self.token = await session.decapsulate_token(self, self.token_text)
        if self.token is None:
            raise fastapi.HTTPException(403, detail="Invalid token")
        if not config.profile_enabled(self.token.profile):
            raise fastapi.HTTPException(503, detail=f"{self.token.profile.value.upper()} client profile is disabled")
        if self.token.profile != self.profile:
            util.log(
                "Client profile resolved from session",
                f"temporary={self.profile.value}",
                f"session={self.token.profile.value}",
                severity=util.logging.INFO,
            )
        self.select_profile(self.token.profile)
        self.server_rsa_label = self.token.server_rsa_label


class SchoolIdolUserParams(SchoolIdolAuthParams):
    """Context object used for fully authenticated request.

    Fully authenticated means there's user associated with it.
    """

    def __init__(
        self,
        request: fastapi.Request,
        background_task: fastapi.BackgroundTasks,
        authorize: Annotated[str, fastapi.Header(alias="Authorize")],
        client_version: Annotated[str, fastapi.Header(alias="Client-Version")],
        lang: Annotated[str, fastapi.Header(alias="LANG")],
        platform_type: Annotated[idoltype.PlatformType, fastapi.Header(alias="Platform-Type")],
        request_data: bytes | None = fastapi.Form(default=None, exclude=True, include=False),
    ):
        super().__init__(request, background_task, authorize, client_version, lang, platform_type, request_data)

    @override
    async def finalize(self):
        await super().finalize()
        assert self.token is not None
        if self.token.user_id == 0:
            raise fastapi.HTTPException(403, detail="Not logged in!")


TOKEN_SERIALIZER = itsdangerous.serializer.Serializer(config.get_secret_key(), serializer=pickle)
FIRST_STAGE_TOKEN_MAX_DURATION = 60
SALT_SIZE = 16
TOKEN_SIZE = 16


@dataclasses.dataclass(kw_only=True)
class TokenData:
    token: str
    client_key: bytes
    server_key: bytes
    user_id: int
    profile: client_profile.ClientProfile
    server_rsa_label: str | None = None


async def encapsulate_token(context: BasicSchoolIdolContext, server_key: bytes, client_key: bytes, user_id: int = 0):
    salt = util.randbytes(SALT_SIZE)
    token = util.randbytes(TOKEN_SIZE).hex()[:TOKEN_SIZE]
    session = main.Session(
        token=token,
        user_id=None if user_id == 0 else user_id,
        profile=context.profile.value,
        server_rsa_label=getattr(context, "server_rsa_label", None),
        client_key=client_key,
        server_key=server_key,
    )
    result = cast(bytes, TOKEN_SERIALIZER.dumps(token, salt))

    context.db.main.add(session)
    await context.db.main.flush()
    token_text = str(base64.urlsafe_b64encode(salt + result), "utf-8")
    return token_text


async def cleanup_session_table(context: BasicSchoolIdolContext, /):
    t = util.time()
    q = sqlalchemy.delete(main.Session).where(
        main.Session.user_id == None, main.Session.last_accessed < (t - FIRST_STAGE_TOKEN_MAX_DURATION)
    )
    await context.db.main.execute(q)

    # Delete tokens
    expiry_time = config.get_session_expiry_time()
    if expiry_time > 0:
        q = sqlalchemy.delete(main.Session).where(main.Session.last_accessed < (t - expiry_time))
        await context.db.main.execute(q)

    await context.db.main.flush()


_currently_cleaning = False


async def try_cleanup_tokens():
    global _currently_cleaning
    if not _currently_cleaning:
        _currently_cleaning = True
        await asyncio.sleep(5)
        async with BasicSchoolIdolContext() as context:
            await cleanup_session_table(context)
        _currently_cleaning = False


async def decapsulate_token(context: BasicSchoolIdolContext, token_data: str):
    encoded_data = base64.urlsafe_b64decode(token_data)
    salt, result = encoded_data[:SALT_SIZE], encoded_data[SALT_SIZE:]
    try:
        token: str = TOKEN_SERIALIZER.loads(result, salt)
    except itsdangerous.BadSignature:
        return None

    # Get token
    q = sqlalchemy.select(main.Session).where(main.Session.token == token)
    expiry_time = config.get_session_expiry_time()
    if expiry_time > 0:
        q = q.where(main.Session.last_accessed >= (util.time() - expiry_time))

    result = await context.db.main.execute(q)
    session = result.scalar()
    if session is None:
        return None

    session.last_accessed = util.time()
    try:
        profile = client_profile.ClientProfile.normalize(session.profile)
    except ValueError:
        return None
    if not config.profile_enabled(profile):
        return None
    return TokenData(
        token=session.token,
        client_key=session.client_key,
        server_key=session.server_key,
        user_id=session.user_id or 0,
        profile=profile,
        server_rsa_label=session.server_rsa_label,
    )


async def invalidate_current(context: SchoolIdolParams):
    # ``token_text`` is the serialized/salted wire token; Session.token stores
    # the internal random token.  v4.60 compared the two and therefore never
    # invalidated a session.
    if context.token is not None:
        q = sqlalchemy.delete(main.Session).where(main.Session.token == context.token.token)
        await context.db.main.execute(q)
        await context.db.main.flush()
