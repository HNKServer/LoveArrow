import enum

import pydantic


class Language(str, enum.Enum):
    en = "en"
    jp = "jp"
    zh_cn = "zh_cn"
    zh_tw = "zh_tw"


def normalize_language(value: str | Language | None) -> Language:
    """Normalize client LANG header values across Global/JP/CN clients.

    Older SIF clients and regional builds are not perfectly consistent about
    casing and separators.  Keep FastAPI from rejecting the request before the
    compatibility layer can decide how to handle it.
    """
    if isinstance(value, Language):
        return value
    if value is None:
        return Language.en

    v = str(value).strip().replace("-", "_").lower()
    match v:
        case "jp" | "ja" | "ja_jp" | "japanese":
            return Language.jp
        case "cn" | "zh" | "zh_cn" | "zh_hans" | "zh_sg" | "sc" | "chs":
            return Language.zh_cn
        case "zh_tw" | "zh_hk" | "zh_hant" | "tc" | "cht":
            return Language.zh_tw
        case _:
            return Language.en


class PlatformType(enum.IntEnum):
    iOS = 1
    Android = 2


class XMCVerifyMode(enum.IntEnum):
    NONE = 0
    SHARED = 1
    CROSS = 2


class ReleaseInfoData(pydantic.BaseModel):
    id: int
    key: str


class ResponseData[_S: pydantic.BaseModel](pydantic.BaseModel):
    response_data: _S
    release_info: list[ReleaseInfoData] = pydantic.Field(default_factory=list)
    status_code: int = 200


class ErrorResponse(pydantic.BaseModel):
    error_code: int
    detail: str | None
