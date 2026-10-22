"""Services for family reward pools.

Registered from ``services.async_setup_services`` with one call. Shared service
helpers are imported lazily because ``services`` imports this module.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
import voluptuous as vol

from .. import const
from ..helpers.auth_helpers import (
    AUTH_ACTION_MANAGEMENT,
    AUTH_ACTION_PARTICIPATION,
    is_user_authorized_for_action,
)
from ..helpers.entity_helpers import get_item_id_or_raise
from . import const as rp

if TYPE_CHECKING:
    from ..coordinator import ChoreOpsDataCoordinator

POOL_SERVICE_NAMES: tuple[str, ...] = (
    rp.SERVICE_CONTRIBUTE_TO_REWARD_POOL,
    rp.SERVICE_APPROVE_REWARD_POOL,
    rp.SERVICE_REFUND_REWARD_POOL,
)


def register_pool_services(hass: HomeAssistant) -> None:
    """Register the contribute / approve / refund pool services."""
    from .. import services as svc  # Imported here: circular at import time

    with_target = svc._with_service_target_fields

    contribute_schema = vol.Schema(
        with_target(
            {
                vol.Required(const.SERVICE_FIELD_USER_NAME): cv.string,
                vol.Required(const.SERVICE_FIELD_REWARD_NAME): cv.string,
                vol.Optional(const.SERVICE_FIELD_POINTS_AMOUNT): vol.All(
                    vol.Coerce(float), vol.Range(min=0, min_included=False)
                ),
            }
        )
    )
    base = {
        vol.Optional(const.SERVICE_FIELD_APPROVER_NAME): cv.string,
        vol.Required(const.SERVICE_FIELD_REWARD_NAME): cv.string,
    }
    approve_schema = vol.Schema(with_target(base))
    refund_schema = vol.Schema(
        with_target({**base, vol.Optional(const.SERVICE_FIELD_USER_NAME): cv.string})
    )

    async def handle_contribute(call: ServiceCall) -> dict[str, Any] | None:
        """Pay points from a user's balance into a pooled reward."""
        entry_id = svc._resolve_target_entry_id(hass, dict(call.data))
        if not entry_id:
            const.LOGGER.warning(
                "Contribute To Reward Pool: %s",
                const.TRANS_KEY_ERROR_MSG_NO_ENTRY_FOUND,
            )
            return None

        coordinator = svc._get_coordinator_by_entry_id(hass, entry_id)
        assignee_id = get_item_id_or_raise(
            coordinator,
            const.ITEM_TYPE_USER,
            call.data[const.SERVICE_FIELD_USER_NAME],
            role=const.ROLE_ASSIGNEE,
        )
        reward_id = get_item_id_or_raise(
            coordinator,
            const.ITEM_TYPE_REWARD,
            call.data[const.SERVICE_FIELD_REWARD_NAME],
        )

        user_id = call.context.user_id
        if user_id and not await is_user_authorized_for_action(
            hass,
            user_id,
            AUTH_ACTION_PARTICIPATION,
            target_user_id=assignee_id,
        ):
            raise HomeAssistantError(
                translation_domain=const.DOMAIN,
                translation_key=const.TRANS_KEY_ERROR_NOT_AUTHORIZED_ACTION,
                translation_placeholders={
                    "action": rp.ERROR_ACTION_CONTRIBUTE_REWARD_POOL
                },
            )

        contributed = await coordinator.reward_pool_manager.contribute_to_pool(
            assignee_id,
            reward_id,
            call.data.get(const.SERVICE_FIELD_POINTS_AMOUNT),
        )
        return {const.SERVICE_FIELD_POINTS_AMOUNT: contributed}

    async def resolve_manager_call(
        call: ServiceCall, log_label: str
    ) -> tuple[ChoreOpsDataCoordinator, str] | None:
        """Resolve coordinator and reward for an approver pool action."""
        entry_id = svc._resolve_target_entry_id(hass, dict(call.data))
        if not entry_id:
            const.LOGGER.warning(
                "%s: %s", log_label, const.TRANS_KEY_ERROR_MSG_NO_ENTRY_FOUND
            )
            return None

        coordinator = svc._get_coordinator_by_entry_id(hass, entry_id)
        user_id = call.context.user_id
        if user_id and not await is_user_authorized_for_action(
            hass, user_id, AUTH_ACTION_MANAGEMENT
        ):
            raise HomeAssistantError(
                translation_domain=const.DOMAIN,
                translation_key=const.TRANS_KEY_ERROR_NOT_AUTHORIZED_ACTION,
                translation_placeholders={"action": rp.ERROR_ACTION_MANAGE_REWARD_POOL},
            )

        reward_id = get_item_id_or_raise(
            coordinator,
            const.ITEM_TYPE_REWARD,
            call.data[const.SERVICE_FIELD_REWARD_NAME],
        )
        return coordinator, reward_id

    async def handle_approve(call: ServiceCall) -> None:
        """Confirm a full family pool's reward was delivered."""
        resolved = await resolve_manager_call(call, "Approve Reward Pool")
        if resolved is None:
            return
        coordinator, reward_id = resolved
        approver_name = call.data.get(const.SERVICE_FIELD_APPROVER_NAME)
        if not approver_name and call.context.user_id:
            user_obj = await hass.auth.async_get_user(call.context.user_id)
            approver_name = user_obj.name if user_obj else None
        await coordinator.reward_pool_manager.approve_pool(
            approver_name or const.DISPLAY_UNKNOWN, reward_id
        )

    async def handle_refund(call: ServiceCall) -> None:
        """Cancel a family pool, or refund one person's share of it."""
        resolved = await resolve_manager_call(call, "Refund Reward Pool")
        if resolved is None:
            return
        coordinator, reward_id = resolved
        user_name = call.data.get(const.SERVICE_FIELD_USER_NAME)
        user_id = (
            get_item_id_or_raise(
                coordinator, const.ITEM_TYPE_USER, user_name, role=const.ROLE_ASSIGNEE
            )
            if user_name
            else None
        )
        await coordinator.reward_pool_manager.refund_pool(reward_id, user_id)

    hass.services.async_register(
        const.DOMAIN,
        rp.SERVICE_CONTRIBUTE_TO_REWARD_POOL,
        handle_contribute,
        schema=contribute_schema,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        const.DOMAIN,
        rp.SERVICE_APPROVE_REWARD_POOL,
        handle_approve,
        schema=approve_schema,
    )
    hass.services.async_register(
        const.DOMAIN,
        rp.SERVICE_REFUND_REWARD_POOL,
        handle_refund,
        schema=refund_schema,
    )
