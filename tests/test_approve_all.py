"""Approve all: many approvals, one entity refresh, approver rights kept."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import patch

from homeassistant.components.button import DOMAIN as BUTTON_DOMAIN, SERVICE_PRESS
from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
import pytest

from custom_components.choreops import const
from custom_components.choreops.approve_all import SERVICE_APPROVE_ALL_PENDING
from tests.helpers import SetupResult, setup_from_yaml
from tests.helpers.workflows import get_chore_buttons, get_dashboard_helper

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


@pytest.fixture
async def scenario_full(
    hass: HomeAssistant,
    mock_hass_users: dict[str, Any],
) -> SetupResult:
    """Load full scenario: 3 assignees with chores."""
    return await setup_from_yaml(
        hass,
        mock_hass_users,
        "tests/scenarios/scenario_full.yaml",
    )


async def _claim_some(hass: HomeAssistant, count: int) -> list[tuple[str, str]]:
    """Claim chores for Zoë; return (chore sensor, approve button) pairs."""
    claimed: list[tuple[str, str]] = []
    for chore in get_dashboard_helper(hass, "zoe").get("chores", []):
        buttons = get_chore_buttons(hass, chore["eid"])
        try:
            await hass.services.async_call(
                BUTTON_DOMAIN,
                SERVICE_PRESS,
                {"entity_id": buttons["claim"]},
                blocking=True,
            )
        except HomeAssistantError:
            continue
        claimed.append((chore["eid"], buttons["approve"]))
        if len(claimed) == count:
            break
    await hass.async_block_till_done()
    return claimed


async def test_approve_all_approves_everything_with_one_refresh(
    hass: HomeAssistant,
    scenario_full: SetupResult,
    mock_hass_users: dict[str, Any],
) -> None:
    """Every pending item is approved, and entities refresh once."""
    claimed = await _claim_some(hass, 4)
    assert len(claimed) == 4

    with patch.object(
        DataUpdateCoordinator, "async_update_listeners", autospec=True
    ) as refresh:
        await hass.services.async_call(
            const.DOMAIN,
            SERVICE_APPROVE_ALL_PENDING,
            {"entity_id": [approve for _, approve in claimed]},
            blocking=True,
            context=Context(user_id=mock_hass_users["approver1"].id),
        )
    assert refresh.call_count == 1

    await hass.async_block_till_done()
    for chore_eid, _ in claimed:
        state = hass.states.get(chore_eid)
        assert state is not None
        # Approved, or completed for a shared chore everyone has finished
        assert state.state in (const.CHORE_STATE_APPROVED, const.CHORE_STATE_COMPLETED)


async def test_approve_all_keeps_approver_rights(
    hass: HomeAssistant,
    scenario_full: SetupResult,
    mock_hass_users: dict[str, Any],
) -> None:
    """An assignee can't approve their own chores through approve all."""
    claimed = await _claim_some(hass, 2)

    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            const.DOMAIN,
            SERVICE_APPROVE_ALL_PENDING,
            {"entity_id": [approve for _, approve in claimed]},
            blocking=True,
            context=Context(user_id=mock_hass_users["assignee1"].id),
        )
    assert err.value.translation_key == "approve_all_failed"
    for chore_eid, _ in claimed:
        state = hass.states.get(chore_eid)
        assert state is not None
        assert state.state == const.CHORE_STATE_CLAIMED


async def test_batched_updates_refresh_once_and_stay_immediate_outside(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """Refreshes wait inside a batch; outside one they run right away."""
    coordinator = scenario_full.coordinator
    with patch.object(
        DataUpdateCoordinator, "async_update_listeners", autospec=True
    ) as refresh:
        coordinator.async_update_listeners()
        assert refresh.call_count == 1
        async with coordinator.batched_updates():
            async with coordinator.batched_updates():
                coordinator.async_update_listeners()
                coordinator.async_update_listeners()
            assert refresh.call_count == 1
        assert refresh.call_count == 2


def test_dashboard_approve_all_buttons_use_the_batched_service() -> None:
    """Both "Approve all" buttons (everyone, and per person) use the service."""
    from pathlib import Path

    template = Path(
        "custom_components/choreops/dashboards/templates/admin-shared-family-hub-v1.yaml"
    ).read_text(encoding="utf-8")
    assert template.count("'service': 'choreops.approve_all_pending'") == 2
    assert "'data': {'entity_id': ns.all_ids}" in template
    assert "'data': {'entity_id': k_ids}" in template
