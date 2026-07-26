import pydantic
import sqlalchemy

from .. import client_profile, idol
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
    if context.profile is not client_profile.ClientProfile.CN:
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
                main.MuseumUnlock.profile == context.profile.value,
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
        main.MuseumUnlock.profile == context.profile.value,
        main.MuseumUnlock.museum_contents_id == museum_contents_id,
    )
    if (await context.db.main.execute(q)).scalar() is not None:
        return False
    context.db.main.add(
        main.MuseumUnlock(
            user_id=user.id,
            profile=context.profile.value,
            museum_contents_id=museum_contents_id,
        )
    )
    await context.db.main.flush()
    return True


async def has(context: idol.BasicSchoolIdolContext, user: main.User, museum_contents_id: int):
    q = sqlalchemy.select(main.MuseumUnlock).where(
        main.MuseumUnlock.user_id == user.id,
        main.MuseumUnlock.profile == context.profile.value,
        main.MuseumUnlock.museum_contents_id == museum_contents_id,
    )
    return (await context.db.main.execute(q)).scalar() is not None


def _native_unlock_policy(context: idol.BasicSchoolIdolContext) -> str:
    policy = str(config.get_profile_download(context.profile).museum_unlock_policy or "normal").strip().lower()
    if policy not in {"normal", "all"}:
        return "normal"
    return policy


async def get_museum_info_data(context: idol.BasicSchoolIdolContext, user: main.User):
    await _cleanup_legacy_museum_transplant(context, user)
    rows = await _native_rows(context)
    row_by_id = {int(row[0]): row for row in rows}
    if _native_unlock_policy(context) == "all":
        # Only the active profile's native catalogue is exposed. CN and GL use
        # separate Master DB connections, so this is not a cross-region transplant.
        contents_id_list = sorted(row_by_id)
    else:
        q = sqlalchemy.select(main.MuseumUnlock.museum_contents_id).where(
            main.MuseumUnlock.user_id == user.id,
            main.MuseumUnlock.profile == context.profile.value,
        )
        requested = list((await context.db.main.execute(q)).scalars())
        contents_id_list = sorted({int(value) for value in requested if int(value) in row_by_id})
    parameter = MuseumParameterData()
    # Keep the native Museum/Album catalogue and unlock state fully functional.
    # The client receives the same contents_id_list, so unlocked gallery entries
    # remain viewable; only the permanent team-stat contribution is suppressed.
    if config.CONFIG_DATA.gameplay.museum_stat_bonus_enabled:
        for contents_id in contents_id_list:
            _, smile_buff, pure_buff, cool_buff = row_by_id[contents_id]
            parameter.smile += int(smile_buff or 0)
            parameter.pure += int(pure_buff or 0)
            parameter.cool += int(cool_buff or 0)
    return MuseumInfoData(parameter=parameter, contents_id_list=contents_id_list)
