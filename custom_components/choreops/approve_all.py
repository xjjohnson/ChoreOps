"""Approve many pending chores and rewards with one entity refresh.

The dashboards' "Approve all" used to press every approve button through
``button.press``. Each approval refreshes every ChoreOps entity several times,
so a few dozen approvals blocked Home Assistant for seconds. This service
presses the same buttons (each one still checks who is approving) inside one
batched update per integration instance.
"""

from __future__ import annotations

from contextlib import AsyncExitStack
from typing import TYPE_CHECKING

from homeassistant.components.button import DATA_COMPONENT as BUTTON_COMPONENT
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
import voluptuous as vol

from . import const

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant, ServiceCall

    from .button import ApproverChoreApproveButton, ApproverRewardApproveButton

SERVICE_APPROVE_ALL_PENDING = "approve_all_pending"
TRANS_KEY_ERROR_APPROVE_ALL_FAILED = "approve_all_failed"  # {failed} {total} {error}

APPROVE_ALL_SCHEMA = vol.Schema({vol.Required("entity_id"): cv.entity_ids})


def register_approve_all_service(hass: HomeAssistant) -> None:
    """Register the approve_all_pending service."""

    async def handle_approve_all(call: ServiceCall) -> None:
        # Imported here: the button platform loads after the services
        from .button import ApproverChoreApproveButton, ApproverRewardApproveButton

        approve_buttons = (ApproverChoreApproveButton, ApproverRewardApproveButton)
        component = hass.data.get(BUTTON_COMPONENT)
        buttons: list[ApproverChoreApproveButton | ApproverRewardApproveButton] = []
        for entity_id in call.data["entity_id"]:
            entity = component.get_entity(entity_id) if component else None
            if not isinstance(entity, approve_buttons):
                const.LOGGER.warning(
                    "Approve all: %s is not a ChoreOps approve button", entity_id
                )
                continue
            buttons.append(entity)

        errors: list[HomeAssistantError] = []
        async with AsyncExitStack() as stack:
            batched: set[int] = set()
            for button in buttons:
                coordinator = button.coordinator
                if id(coordinator) not in batched:
                    batched.add(id(coordinator))
                    await stack.enter_async_context(coordinator.batched_updates())
            for button in buttons:
                # Each button checks the caller's rights from its own context
                button.async_set_context(call.context)
                try:
                    await button.async_press()
                except HomeAssistantError as err:
                    errors.append(err)

        if errors:
            raise HomeAssistantError(
                translation_domain=const.DOMAIN,
                translation_key=TRANS_KEY_ERROR_APPROVE_ALL_FAILED,
                translation_placeholders={
                    "failed": str(len(errors)),
                    "total": str(len(buttons)),
                    "error": str(errors[0]),
                },
            )

    hass.services.async_register(
        const.DOMAIN,
        SERVICE_APPROVE_ALL_PENDING,
        handle_approve_all,
        schema=APPROVE_ALL_SCHEMA,
    )
