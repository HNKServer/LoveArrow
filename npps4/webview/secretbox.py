import base64
import dataclasses
import html
import json

import fastapi
import pydantic
import sqlalchemy

from .. import idol
from .. import util
from ..app import app
from ..config import config
from ..db import achievement
from ..system import achievement as achievement_system
from ..system import handover
from ..system import lila
from ..system import secretbox

from typing import Annotated


@app.webview.get("/secretbox/detail")
async def secretbox_detail(
    request: fastapi.Request,
    secretbox_id: Annotated[int, fastapi.Query()],
    profile: Annotated[str | None, fastapi.Query()] = None,
):
    async with idol.create_basic_context(request) as context:
        if profile is not None:
            try:
                context.select_profile(profile)
            except ValueError as exc:
                raise fastapi.HTTPException(status_code=400, detail="invalid client profile") from exc
        try:
            secretbox_data = await secretbox.get_secretbox_data(context, secretbox_id)
        except KeyError as exc:
            # A stale client page or manually edited URL must not expose a raw
            # server traceback inside the in-game webview.
            raise fastapi.HTTPException(status_code=404, detail="secretbox page is unavailable for this client profile") from exc
        rate_count = sum(secretbox_data.rarity_rates)
        rate_data = [
            (name, weight, weight / rate_count)
            for name, weight in zip(secretbox_data.rarity_names, secretbox_data.rarity_rates)
        ]

        cost_type_names = {
            1000: "Item / Scouting Ticket",
            3000: "G",
            3001: "Love Gem",
            3002: "Friend Pts",
        }
        button_data = []
        for index, button in enumerate(secretbox_data.buttons, 1):
            effective_rates = button.rate_modifier or secretbox_data.rarity_rates
            effective_total = sum(effective_rates)
            guarantee = None
            if button.guaranteed_rarity > 0 and button.guarantee_specific_rarity_amount > 0:
                rarity_index = button.guaranteed_rarity - 1
                if rarity_index < len(secretbox_data.rarity_names):
                    guarantee = (
                        button.guarantee_specific_rarity_amount,
                        secretbox_data.rarity_names[rarity_index],
                    )
            button_data.append(
                {
                    "index": index,
                    "button_type": int(button.button_type),
                    "unit_count": int(button.unit_count),
                    "costs": [
                        {
                            "type": int(cost.cost_type),
                            "type_name": cost_type_names.get(int(cost.cost_type), str(int(cost.cost_type))),
                            "item_id": cost.cost_item_id,
                            "amount": int(cost.cost_amount),
                        }
                        for cost in button.costs
                    ],
                    "guarantee": guarantee,
                    "rates": [
                        (name, weight, weight / effective_total)
                        for name, weight in zip(secretbox_data.rarity_names, effective_rates)
                    ],
                }
            )
        return app.templates.TemplateResponse(
            request,
            "secretbox_detail.html",
            {
                "secretbox_id": secretbox_id,
                "secretbox_name": context.get_text(secretbox_data.name, secretbox_data.name_en),
                "rates": rate_data,
                "buttons": button_data,
            },
        )
