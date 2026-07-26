"""Read-only audit of profile-exclusive scouting-ticket client resources.

The final clients contain many item rows which identify ticket-driven scouting
campaigns, especially the CN 100xx catalogue.  Those item rows prove that the
client can display/hold the tickets, but they do not contain the server-side
candidate pools, rates, selection workflow or banner/detail payload.  This
module therefore exposes the evidence to validation/admin code without
pretending that every ticket is a fully reconstructed Secretbox page.
"""
from __future__ import annotations

import dataclasses
import importlib.resources as resources
import json
from typing import Any

from . import common
from .. import idol


@dataclasses.dataclass(frozen=True)
class ExclusiveScoutingTicketCatalogue:
    profile: str
    source: str
    source_sha256: str
    comparison_profile: str
    items: tuple[dict[str, Any], ...]
    contract_note: str

    @property
    def item_ids(self) -> frozenset[int]:
        return frozenset(int(row["item_id"]) for row in self.items)


@common.context_cacheable("exclusive_scouting_ticket_catalogue")
async def for_context(
    context: idol.BasicSchoolIdolContext, profile: str, /
) -> ExclusiveScoutingTicketCatalogue:
    normalized = str(profile).lower()
    if normalized not in {"cn", "gl"}:
        raise ValueError(f"unsupported client profile: {profile}")
    raw = json.loads(
        resources.files("npps4.assets.scouting_ticket_catalogue")
        .joinpath(f"{normalized}_exclusive.json")
        .read_text(encoding="utf-8")
    )
    items = tuple(dict(row) for row in raw["items"])
    expected = int(raw["exclusive_scouting_like_item_count"])
    if len(items) != expected:
        raise RuntimeError(
            f"{normalized.upper()} scouting-ticket audit count mismatch: "
            f"{len(items)} != {expected}"
        )
    return ExclusiveScoutingTicketCatalogue(
        profile=normalized,
        source=str(raw["source"]),
        source_sha256=str(raw["source_sha256"]),
        comparison_profile=str(raw["comparison_profile"]),
        items=items,
        contract_note=str(raw["contract_note"]),
    )


async def current(context: idol.BasicSchoolIdolContext) -> ExclusiveScoutingTicketCatalogue:
    return await for_context(context, context.profile.value)
