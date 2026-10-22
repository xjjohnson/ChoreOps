"""Family pool settings fields on the reward form."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.helpers import selector
import voluptuous as vol

from .. import const
from . import const as rp


def match_parent_options(users: Mapping[str, Any]) -> list[selector.SelectOptionDict]:
    """Return the people a match can be paid from: approvers with a balance.

    Args:
        users: Assignee-capable user records keyed by ID (they hold balances).
    """
    options: list[selector.SelectOptionDict] = []
    for user_id, info in users.items():
        if isinstance(info, Mapping) and info.get(const.DATA_USER_CAN_APPROVE):
            options.append(
                selector.SelectOptionDict(
                    value=str(user_id),
                    label=str(info.get(const.DATA_USER_NAME, user_id)),
                )
            )
    return options


def schema_fields(
    users: Mapping[str, Any],
) -> dict[vol.Required | vol.Optional, Any]:
    """Return the pool settings fields for the reward form."""
    number = selector.NumberSelectorConfig(
        mode=selector.NumberSelectorMode.BOX, min=0, step=0.01
    )
    return {
        vol.Optional(
            rp.DATA_REWARD_POOL_MAX_SHARE, default=const.DEFAULT_ZERO
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(
                mode=selector.NumberSelectorMode.BOX,
                min=0,
                max=100,
                step=1,
                unit_of_measurement="%",
            )
        ),
        vol.Optional(
            rp.DATA_REWARD_POOL_MATCH_RATIO, default=const.DEFAULT_ZERO
        ): selector.NumberSelector(number),
        vol.Optional(
            rp.DATA_REWARD_POOL_MATCH_USER_IDS, default=[]
        ): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=match_parent_options(users),
                mode=selector.SelectSelectorMode.DROPDOWN,
                multiple=True,
            )
        ),
        vol.Optional(
            rp.DATA_REWARD_POOL_AFTER_DELIVERY, default=rp.AFTER_DELIVERY_RESTART
        ): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[rp.AFTER_DELIVERY_RESTART, rp.AFTER_DELIVERY_CLOSE],
                mode=selector.SelectSelectorMode.DROPDOWN,
                translation_key=rp.DATA_REWARD_POOL_AFTER_DELIVERY,
            )
        ),
    }
