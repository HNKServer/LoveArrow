from ..config import config

if not config.is_script_mode():
    from . import achievement
    from . import ad
    from . import album
    from . import announce
    from . import award
    from . import background
    from . import banner
    from . import challenge
    from . import common
    from . import costume
    from . import download
    from . import event
    from . import eventscenario
    from . import exchange
    from . import friend
    from . import gdpr
    from . import greet
    from . import handover
    from . import item
    from . import lbonus
    from . import live
    from . import liveicon
    from . import livese
    from . import login
    from . import marathon
    from . import multiunit
    from . import museum
    from . import navigation
    from . import notice
    from . import payment
    from . import personalnotice
    from . import profile
    from . import ranking
    from . import reward
    from . import scenario
    from . import secretbox
    from . import stamp
    from . import subscenario
    from . import tos
    from . import tutorial
    from . import unit
    from . import user
    # CN wrappers are enabled by default because they are not honoka-style stubs:
    # they only translate CN action names/shapes into NPPS4's own gameplay systems.
    if config.use_cn_wrappers():
        from . import cn_wrappers

    # Keep honoka-inspired fallback stubs opt-in. They are useful for locating
    # CN-only calls, but enabling them by default can mask missing real gameplay
    # implementations and make compatibility testing look healthier than it is.
    if config.use_cn_optional_stubs():
        from . import cn_optional_stubs
    from .. import sif2export  # HACK
