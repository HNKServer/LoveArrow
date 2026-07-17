import fastapi

from . import error
from .core import register
from .session import BasicSchoolIdolContext, SchoolIdolParams, SchoolIdolAuthParams, SchoolIdolUserParams
from ..idoltype import Language, PlatformType, XMCVerifyMode, normalize_language


def create_basic_context(request: fastapi.Request):
    return BasicSchoolIdolContext(normalize_language(request.headers.get("LANG", "en")))
