import argparse

import sqlalchemy

import npps4.db.live
import npps4.idol
import npps4.scriptutils.user
import npps4.system.live


async def run_script(arg: list[str]):
    parser = argparse.ArgumentParser(__file__)
    group = parser.add_mutually_exclusive_group(required=True)
    npps4.scriptutils.user.register_args(group)
    args = parser.parse_args(arg)

    async with npps4.idol.BasicSchoolIdolContext(lang=npps4.idol.Language.en) as context:
        target_user = await npps4.scriptutils.user.from_args(context, args)
        q = (
            sqlalchemy.select(npps4.db.live.LiveSetting.live_track_id)
            .join(
                npps4.db.live.NormalLive,
                npps4.db.live.NormalLive.live_setting_id == npps4.db.live.LiveSetting.live_setting_id,
            )
            .distinct()
        )
        result = await context.db.live.execute(q)
        for live_track_id in result.scalars():
            await npps4.system.live.unlock_normal_live(context, target_user, live_track_id)


if __name__ == "__main__":
    import npps4.scriptutils.boot

    npps4.scriptutils.boot.start(run_script)
