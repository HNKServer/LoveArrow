import pydantic

from .. import idol
from .. import util
from ..system import client_capabilities
from ..system import transfer_web
from ..system import secretbox
from ..system import user


class BannerInfo(pydantic.BaseModel):
    banner_type: int
    target_id: int
    asset_path: str
    webview_url: str | None = None
    is_registered: bool | None = None
    fixed_flag: bool
    back_side: bool
    banner_id: int
    start_date: str
    end_date: str


class BannerListResponse(pydantic.BaseModel):
    time_limit: str
    banner_list: list[BannerInfo]


def _banner_dates() -> tuple[str, str]:
    return util.timestamp_to_datetime(1476522000), util.timestamp_to_datetime(2147483647)


def _cn_webview_banner(
    *,
    banner_id: int,
    asset_path: str,
    webview_url: str,
    back_side: bool,
) -> BannerInfo:
    start, end = _banner_dates()
    return BannerInfo(
        banner_type=2,
        target_id=1,
        asset_path=asset_path,
        webview_url=webview_url,
        fixed_flag=False,
        back_side=back_side,
        banner_id=banner_id,
        start_date=start,
        end_date=end,
    )


async def _secretbox_banners(context: idol.BasicSchoolIdolContext) -> list[BannerInfo]:
    """Build home jumps from the same projected pages returned by secretbox/all."""
    start, end = _banner_dates()
    result: list[BannerInfo] = []
    seen_assets: set[str] = set()
    pages = sorted(
        await secretbox.get_visible_secretboxes(context),
        key=lambda item: (
            int(item.member_category),
            int(item.order),
            min(int(button.unit_count) for button in item.buttons),
            int(item.secretbox_id),
        ),
    )
    for page in pages:
        asset = secretbox.resolve_menu_asset(context, page).strip()
        # The official single and 10x blue-ticket pages intentionally share a
        # visual asset. Keep both pages in scouting, but use one home tile and
        # make its jump select the single-draw page (the least surprising entry).
        if not asset or asset in seen_assets:
            continue
        seen_assets.add(asset)
        result.append(
            BannerInfo(
                banner_type=1,
                target_id=int(page.secretbox_id),
                asset_path=asset,
                fixed_flag=False,
                back_side=False,
                banner_id=101000 + len(result) + 1,
                start_date=start,
                end_date=end,
            )
        )
    return result


@idol.register("banner", "bannerList", exclude_none=True)
async def banner_bannerlist(context: idol.SchoolIdolUserParams) -> BannerListResponse:
    current_user = await user.get_current(context)
    capabilities = client_capabilities.for_context(context)

    banner_list: list[BannerInfo] = []

    if capabilities.profile == "cn":
        token = transfer_web.make_token(current_user.id)
        # Front side: transfer first, followed by the real scouting pages.
        banner_list.append(
            _cn_webview_banner(
                banner_id=200101,
                # Use a stock CN WebView catalogue slot whose descriptor and
                # texture are delivered by the synthetic final full-data package.
                # This is a real KLab .imag + TEXB resource pair, not a raw PNG
                # masquerading as a native texture.
                asset_path="assets/image/webview/wv_ba_117.png",
                webview_url=f"/transfer?t={token}",
                back_side=False,
            )
        )
        banner_list.extend(await _secretbox_banners(context))
        # Back side: one valid WebView item.  Returning no back-side item made
        # the CN flip task enter an empty native render list and SIGTRAP.
        banner_list.append(
            _cn_webview_banner(
                # Match honoka-chan's CN back-side contract exactly: type 2,
                # wv_ba_01, /manga, back_side=true, banner_id=200001.  The
                # backend supplies the bundled official-comic thumbnail.
                banner_id=200001,
                asset_path="assets/image/webview/wv_ba_01.png",
                webview_url="/manga",
                back_side=True,
            )
        )
    else:
        start, end = _banner_dates()
        if capabilities.supports_sif2_transfer_banner:
            banner_list.append(
                BannerInfo(
                    banner_type=18,
                    target_id=1,
                    asset_path=(
                        "en/assets/image/handover/banner/banner_01.png"
                        if context.lang == idol.Language.en
                        else "assets/image/handover/banner/banner_01.png"
                    ),
                    is_registered=current_user.transfer_sha1 is not None,
                    fixed_flag=False,
                    back_side=False,
                    banner_id=1800002,
                    start_date=start,
                    end_date=end,
                )
            )
        banner_list.extend(await _secretbox_banners(context))
        banner_list.append(
            BannerInfo(
                banner_type=2,
                target_id=1,
                asset_path=(
                    "en/assets/image/webview/wv_ba_01.png"
                    if context.lang == idol.Language.en
                    else "assets/image/webview/wv_ba_01.png"
                ),
                webview_url="/manga",
                fixed_flag=False,
                back_side=True,
                banner_id=200001,
                start_date=start,
                end_date=end,
            )
        )

    util.log(
        "Banner capability decision",
        f"profile={capabilities.profile}",
        f"application_version={capabilities.application_version}",
        f"request_version={capabilities.request_version}",
        f"banner_types={[item.banner_type for item in banner_list]}",
        f"target_ids={[item.target_id for item in banner_list]}",
        f"asset_paths={[item.asset_path for item in banner_list]}",
        f"back_side={[item.back_side for item in banner_list]}",
        severity=util.logging.WARNING if capabilities.profile == "cn" else util.logging.INFO,
    )

    return BannerListResponse(
        time_limit=util.timestamp_to_datetime(2147483647),
        banner_list=banner_list,
    )
