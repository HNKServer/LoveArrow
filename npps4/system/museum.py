import pydantic
import sqlalchemy

from .. import idol
from ..config import config
from ..db import main
from ..db import museum


class MuseumParameterData(pydantic.BaseModel):
    smile: int = 0
    pure: int = 0
    cool: int = 0


class MuseumInfoData(pydantic.BaseModel):
    parameter: MuseumParameterData
    contents_id_list: list[int]


class MuseumMixin(pydantic.BaseModel):
    museum_info: MuseumInfoData


async def _native_rows(context: idol.BasicSchoolIdolContext):
    q = sqlalchemy.select(
        museum.MuseumContents.museum_contents_id,
        museum.MuseumContents.smile_buff,
        museum.MuseumContents.pure_buff,
        museum.MuseumContents.cool_buff,
    )
    return (await context.db.museum.execute(q)).all()


async def _cleanup_legacy_museum_transplant(context: idol.BasicSchoolIdolContext, user: main.User) -> None:
    """Remove obsolete automatic cross-region Museum grants from old databases."""
    if not config.is_cn_compat():
        return
    grant_q = sqlalchemy.select(main.ContentAccessGrant).where(
        main.ContentAccessGrant.user_id == user.id,
        main.ContentAccessGrant.grant_key.like("cn_" + "museum_bridge:%"),
    )
    grants = list((await context.db.main.execute(grant_q)).scalars())
    native_ids = {int(row[0]) for row in await _native_rows(context)}
    if native_ids:
        # Preserve legitimate native-CN unlocks and remove only IDs which came
        # from the abandoned cross-region catalogue.
        await context.db.main.execute(
            sqlalchemy.delete(main.MuseumUnlock).where(
                main.MuseumUnlock.user_id == user.id,
                main.MuseumUnlock.museum_contents_id.not_in(native_ids),
            )
        )
    for grant in grants:
        await context.db.main.delete(grant)
    if grants or native_ids:
        await context.db.main.flush()


async def unlock(context: idol.BasicSchoolIdolContext, user: main.User, museum_contents_id: int):
    exists_q = sqlalchemy.select(museum.MuseumContents.museum_contents_id).where(
        museum.MuseumContents.museum_contents_id == museum_contents_id
    )
    if (await context.db.museum.execute(exists_q)).scalar_one_or_none() is None:
        raise ValueError("invalid museum contents id")
    q = sqlalchemy.select(main.MuseumUnlock).where(
        main.MuseumUnlock.user_id == user.id,
        main.MuseumUnlock.museum_contents_id == museum_contents_id,
    )
    if (await context.db.main.execute(q)).scalar() is not None:
        return False
    context.db.main.add(main.MuseumUnlock(user_id=user.id, museum_contents_id=museum_contents_id))
    await context.db.main.flush()
    return True


async def has(context: idol.BasicSchoolIdolContext, user: main.User, museum_contents_id: int):
    q = sqlalchemy.select(main.MuseumUnlock).where(
        main.MuseumUnlock.user_id == user.id,
        main.MuseumUnlock.museum_contents_id == museum_contents_id,
    )
    return (await context.db.main.execute(q)).scalar() is not None


def _native_unlock_policy() -> str:
    policy = str(config.CONFIG_DATA.download.cn_archive.museum_unlock_policy or "normal").strip().lower()
    if policy not in {"normal", "all"}:
        return "normal"
    return policy


async def get_museum_info_data(context: idol.BasicSchoolIdolContext, user: main.User):
    await _cleanup_legacy_museum_transplant(context, user)
    rows = await _native_rows(context)
    row_by_id = {int(row[0]): row for row in rows}
    if config.is_cn_compat() and _native_unlock_policy() == "all":
        # Deliberately limited to the stock CN master rows.  This restores the
        # useful all-unlock switch without reviving the abandoned 1360-row GL
        # catalogue transplant.
        contents_id_list = sorted(row_by_id)
    else:
        q = sqlalchemy.select(main.MuseumUnlock.museum_contents_id).where(main.MuseumUnlock.user_id == user.id)
        requested = list((await context.db.main.execute(q)).scalars())
        contents_id_list = sorted({int(value) for value in requested if int(value) in row_by_id})
    parameter = MuseumParameterData()
    for contents_id in contents_id_list:
        _, smile_buff, pure_buff, cool_buff = row_by_id[contents_id]
        parameter.smile += int(smile_buff or 0)
        parameter.pure += int(pure_buff or 0)
        parameter.cool += int(cool_buff or 0)
    return MuseumInfoData(parameter=parameter, contents_id_list=contents_id_list)
