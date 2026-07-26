from __future__ import annotations

import dataclasses
import importlib.resources as resources
import json
from typing import Any

from . import common
from .. import idol


@dataclasses.dataclass(frozen=True)
class ClientCatalogue:
    """IDs present in the exact supplied CN or GL client masters.

    The object contains only immutable client capability metadata, never user or
    inventory state.  It is cached in ``BasicSchoolIdolContext.cache`` for one
    request, using the same request-local mechanism as original NPPS4 master
    lookups, and is released when that request finishes.
    """

    profile: str
    unit_ids: frozenset[int]
    item_ids: frozenset[int]
    award_ids: frozenset[int]
    background_ids: frozenset[int]
    exchange_point_ids: frozenset[int]
    museum_ids: frozenset[int]
    accessory_ids: frozenset[int]
    special_accessory_pairs: tuple[tuple[int, int], ...]
    special_target_unit_ids: frozenset[int]
    unit_type_by_id: dict[int, int]
    thanks_festival_pools: dict[int, dict[int, tuple[int, ...]]]
    recovery_item_ids: frozenset[int]
    counts: dict[str, int]
    source_sha256: dict[str, str]


@common.context_cacheable("exact_client_catalogue")
async def for_context(
    context: idol.BasicSchoolIdolContext, profile: str, /
) -> ClientCatalogue:
    normalized = str(profile).lower()
    if normalized not in {"cn", "gl"}:
        raise ValueError(f"unsupported client profile: {profile}")
    text = (
        resources.files("npps4.assets.client_catalogue")
        .joinpath(f"{normalized}.json")
        .read_text(encoding="utf-8")
    )
    raw: dict[str, Any] = json.loads(text)
    return ClientCatalogue(
        profile=normalized,
        unit_ids=frozenset(int(value) for value in raw["unit_ids"]),
        item_ids=frozenset(int(value) for value in raw["item_ids"]),
        award_ids=frozenset(int(value) for value in raw["award_ids"]),
        background_ids=frozenset(int(value) for value in raw["background_ids"]),
        exchange_point_ids=frozenset(int(value) for value in raw["exchange_point_ids"]),
        museum_ids=frozenset(int(value) for value in raw["museum_ids"]),
        accessory_ids=frozenset(int(value) for value in raw["accessory_ids"]),
        special_accessory_pairs=tuple(
            (int(pair[0]), int(pair[1])) for pair in raw.get("special_accessory_pairs", [])
        ),
        special_target_unit_ids=frozenset(
            int(value) for value in raw.get("special_target_unit_ids", [])
        ),
        unit_type_by_id={
            int(key): int(value) for key, value in raw.get("unit_type_by_id", {}).items()
        },
        thanks_festival_pools={
            int(category): {
                int(rarity): tuple(int(unit_id) for unit_id in unit_ids)
                for rarity, unit_ids in rarity_map.items()
            }
            for category, rarity_map in raw.get("thanks_festival_pools", {}).items()
        },
        recovery_item_ids=frozenset(
            int(value) for value in raw.get("recovery_item_ids", [])
        ),
        counts={str(key): int(value) for key, value in raw.get("counts", {}).items()},
        source_sha256={str(key): str(value) for key, value in raw.get("source_sha256", {}).items()},
    )


async def current(context: idol.BasicSchoolIdolContext) -> ClientCatalogue:
    return await for_context(context, context.profile.value)

@common.context_cacheable("known_unit_type_by_id")
async def known_unit_type_by_id(
    context: idol.BasicSchoolIdolContext, profile_marker: str, /
) -> dict[int, int]:
    """Known unit-to-character metadata across the supplied CN/GL sources.

    This is immutable master metadata cached only for the current request. It
    is used solely to keep a cross-profile fallback on the same character when
    the originally selected role card is region-exclusive. Capability checks
    still use the receiving profile's exact ``unit_ids`` set.
    """
    del profile_marker  # retained as the request-local cache key
    text = (
        resources.files("npps4.assets")
        .joinpath("known_unit_type_by_id.json")
        .read_text(encoding="utf-8")
    )
    return {int(key): int(value) for key, value in json.loads(text).items()}

