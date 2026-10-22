"""Fewer entity refreshes per action, with state still current afterwards."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import patch

from homeassistant.components.button import DOMAIN as BUTTON_DOMAIN, SERVICE_PRESS
from homeassistant.core import Context
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
import pytest

from custom_components.choreops import const
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


async def test_button_press_refreshes_once_and_state_is_current(
    hass: HomeAssistant,
    scenario_full: SetupResult,
    mock_hass_users: dict[str, Any],
) -> None:
    """A press refreshes entities once, before the service call returns."""
    chore = get_dashboard_helper(hass, "zoe")["chores"][0]
    buttons = get_chore_buttons(hass, chore["eid"])
    await hass.services.async_call(
        BUTTON_DOMAIN, SERVICE_PRESS, {"entity_id": buttons["claim"]}, blocking=True
    )
    await hass.async_block_till_done()

    with patch.object(
        DataUpdateCoordinator,
        "async_update_listeners",
        autospec=True,
        side_effect=DataUpdateCoordinator.async_update_listeners,
    ) as refresh:
        await hass.services.async_call(
            BUTTON_DOMAIN,
            SERVICE_PRESS,
            {"entity_id": buttons["approve"]},
            blocking=True,
            context=Context(user_id=mock_hass_users["approver1"].id),
        )
        # Read right away, as an automation's next step would
        state = hass.states.get(chore["eid"])
        assert refresh.call_count == 1
    assert state is not None
    assert state.state in (const.CHORE_STATE_APPROVED, const.CHORE_STATE_COMPLETED)


async def test_status_cache_reuses_lookups_and_hands_out_copies(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """Inside status_cache() a pair is computed once; outside, every time."""
    chore_manager = scenario_full.coordinator.chore_manager
    zoe = scenario_full.assignee_ids["Zoë"]
    chore_id = next(iter(scenario_full.coordinator.chores_data))
    real = chore_manager._build_chore_status_context
    with patch.object(
        chore_manager, "_build_chore_status_context", side_effect=real
    ) as build:
        with chore_manager.status_cache():
            first = chore_manager.get_chore_status_context(zoe, chore_id)
            first["state"] = "tampered"
            second = chore_manager.get_chore_status_context(zoe, chore_id)
            assert build.call_count == 1
            assert second["state"] != "tampered"
            chore_manager.clear_status_cache()
            chore_manager.get_chore_status_context(zoe, chore_id)
            assert build.call_count == 2
        chore_manager.get_chore_status_context(zoe, chore_id)
        chore_manager.get_chore_status_context(zoe, chore_id)
        assert build.call_count == 4


async def test_points_summary_is_reused_until_the_ledger_changes(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """The ledger walk runs again only after a new transaction."""
    from custom_components.choreops.sensor import AssigneeDashboardHelperSensor

    coordinator = scenario_full.coordinator
    zoe = scenario_full.assignee_ids["Zoë"]
    helper = next(
        entity
        for entity in hass.data["sensor"].entities
        if isinstance(entity, AssigneeDashboardHelperSensor)
        and entity._assignee_id == zoe
    )
    with patch.object(
        AssigneeDashboardHelperSensor,
        "_build_points_summary",
        side_effect=AssigneeDashboardHelperSensor._build_points_summary,
    ) as build:
        info = coordinator.assignees_data[zoe]
        before = helper._points_summary_for(info)
        helper._points_summary_for(info)
        assert build.call_count <= 1
        calls = build.call_count
        await coordinator.economy_manager.deposit(
            assignee_id=zoe, amount=7.0, source=const.POINTS_SOURCE_MANUAL
        )
        after = helper._points_summary_for(coordinator.assignees_data[zoe])
        assert build.call_count == calls + 1
    assert after["balance"] == pytest.approx(before["balance"] + 7.0)
    assert after["today"] == pytest.approx(before["today"] + 7.0)
