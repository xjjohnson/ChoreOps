"""Saving a family goal in the options flow reloads only when it must."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import patch

from homeassistant.data_entry_flow import FlowResultType
import pytest

from custom_components.choreops import const
from custom_components.choreops.family_goals import const as fg
from tests.helpers import SetupResult, setup_from_yaml
from tests.helpers.flow_test_helpers import FlowTestHelper

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

MARK_RELOAD = (
    "custom_components.choreops.options_flow."
    "ChoreOpsOptionsFlowHandler._mark_reload_needed"
)


@pytest.fixture
async def scenario_full(
    hass: HomeAssistant,
    mock_hass_users: dict[str, Any],
) -> SetupResult:
    """Load full scenario: 3 assignees (Zoë, Max!, Lila), chores, rewards."""
    return await setup_from_yaml(
        hass,
        mock_hass_users,
        "tests/scenarios/scenario_full.yaml",
    )


def _form(name: str, assigned: list[str], target: float) -> dict[str, Any]:
    return {
        fg.DATA_NAME: name,
        fg.DATA_ASSIGNED_USER_IDS: assigned,
        fg.DATA_TYPE: fg.GOAL_TYPE_CHORES,
        fg.DATA_TARGET_VALUE: target,
        fg.DATA_REWARD_POINTS: 5,
    }


async def _edit(
    hass: HomeAssistant, setup: SetupResult, form: dict[str, Any]
) -> tuple[dict[str, Any], bool]:
    with patch(MARK_RELOAD) as mark_reload:
        result = await FlowTestHelper.edit_entity_via_options_flow(
            hass,
            setup.config_entry.entry_id,
            const.OPTIONS_FLOW_CHALLENGES,
            "Tidy week",
            form,
        )
    return dict(result), mark_reload.called


async def _goal(setup: SetupResult, assigned: list[str]) -> str:
    return setup.coordinator.family_goal_manager.create_goal(
        _form("Tidy week", assigned, 14)
    )


async def test_settings_edit_saves_without_reload(
    hass: HomeAssistant, scenario_full: SetupResult
) -> None:
    """A new target is saved without reloading the whole integration."""
    zoe = scenario_full.assignee_ids["Zoë"]
    max_ = scenario_full.assignee_ids["Max!"]
    goal_id = await _goal(scenario_full, [zoe, max_])

    result, reloaded = await _edit(
        hass, scenario_full, _form("Tidy week", [max_, zoe], 20)
    )

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == const.OPTIONS_FLOW_STEP_INIT
    assert not reloaded
    goal = scenario_full.coordinator.challenges_data[goal_id]
    assert goal[fg.DATA_TARGET_VALUE] == 20


async def test_lower_target_is_checked_without_reload(
    hass: HomeAssistant, scenario_full: SetupResult
) -> None:
    """Lowering the target below the total finishes the goal right away."""
    gm = scenario_full.coordinator.family_goal_manager
    zoe = scenario_full.assignee_ids["Zoë"]
    goal_id = await _goal(scenario_full, [zoe])
    gm.update_goal(goal_id, {fg.DATA_TARGET_VALUE: 14})
    await gm.drain_pending()

    with patch.object(gm, "_mark_pending") as mark_pending:
        gm.update_goal(goal_id, {fg.DATA_TARGET_VALUE: 1})
    assert {call.args[0] for call in mark_pending.call_args_list} == set(
        scenario_full.coordinator.assignees_data
    )


@pytest.mark.parametrize("change", ["rename", "people"])
async def test_name_or_people_change_still_reloads(
    hass: HomeAssistant, scenario_full: SetupResult, change: str
) -> None:
    """Sensors are named after the goal and made per person: those reload."""
    zoe = scenario_full.assignee_ids["Zoë"]
    max_ = scenario_full.assignee_ids["Max!"]
    await _goal(scenario_full, [zoe, max_])
    form = (
        _form("Tidy fortnight", [zoe, max_], 14)
        if change == "rename"
        else _form("Tidy week", [zoe], 14)
    )

    result, reloaded = await _edit(hass, scenario_full, form)

    assert result.get("step_id") == const.OPTIONS_FLOW_STEP_INIT
    assert reloaded
