from __future__ import annotations

import dataclasses

from .. import idol
from ..config import config


@dataclasses.dataclass(frozen=True)
class ClientCapabilities:
    """Capabilities derived from the actual APK family, not the content version.

    The CN 9.7.1 client puts ``server_info.server_version`` (97.4.6 for the
    supplied archive set) into the SIF ``Client-Version`` header.  Consequently
    ``context.client_version`` is an API/content-version tuple in CN mode and
    must never be used as the Android application version for Lua/UI feature
    gates.
    """

    profile: str
    application_version: tuple[int, int]
    request_version: tuple[int, int]
    supports_sif2_transfer_banner: bool


def for_context(context: idol.BasicSchoolIdolContext) -> ClientCapabilities:
    if config.is_cn_compat():
        application_version = config.get_cn_application_version()
        return ClientCapabilities(
            profile="cn",
            application_version=application_version,
            request_version=context.client_version,
            # Both supplied CN 9.7.1 and community 9.11 Lua handler tables lack
            # banner type 18.  The current CN profile is tied to the supplied
            # 9.7.1 APK, so this is an APK-family fact, not a fallback response.
            supports_sif2_transfer_banner=False,
        )

    application_version = context.client_version
    return ClientCapabilities(
        profile="standard",
        application_version=application_version,
        request_version=context.client_version,
        supports_sif2_transfer_banner=application_version > (9, 11),
    )
