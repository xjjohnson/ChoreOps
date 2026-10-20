"""Family Goals: options-flow management and the sensors dashboards read."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest

from custom_components.choreops import const
from custom_components.choreops.family_goals import const as fg
from tests.helpers import SetupResult, setup_from_yaml
from tests.helpers.flow_test_helpers import FlowTestHelper


@pytest.fixture
async def scenario_minimal(
    hass: HomeAssistant,
    mock_hass_users: dict[str, Any],
) -> SetupResult:
    """One assignee and one approver."""
    return await setup_from_yaml(
        hass, mock_hass_users, "tests/scenarios/scenario_minimal.yaml"
    )


def _goal_form(assignee_id: str, **overrides: Any) -> dict[str, Any]:
    form: dict[str, Any] = {
        fg.DATA_NAME: "Movie night fund",
        fg.DATA_ASSIGNED_USER_IDS: [assignee_id],
        fg.DATA_TYPE: fg.GOAL_TYPE_POINTS,
        fg.DATA_TARGET_VALUE: 100,
        fg.DATA_LEVELS: "",
        fg.DATA_TOP_MULTIPLIER: 1,
        fg.DATA_REWARD_POINTS: 20,
    }
    form.update(overrides)
    return form


def _find(coordinator: Any, name: str) -> tuple[str, dict[str, Any]]:
    return next(
        (gid, goal)
        for gid, goal in coordinator.challenges_data.items()
        if goal[fg.DATA_NAME] == name
    )


async def test_add_family_goal_via_the_challenges_menu(
    hass: HomeAssistant, scenario_minimal: SetupResult
) -> None:
    """Manage Family Goals (the old Challenges slot) creates a pooled goal."""
    coordinator = scenario_minimal.coordinator
    assignee_id = next(iter(coordinator.assignees_data))

    result = await FlowTestHelper.add_entity_via_options_flow(
        hass,
        scenario_minimal.config_entry.entry_id,
        const.OPTIONS_FLOW_CHALLENGES,
        const.OPTIONS_FLOW_STEP_ADD_CHALLENGE,
        _goal_form(assignee_id, **{fg.DATA_LEVELS: "50:5, 100:10"}),
    )

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == const.OPTIONS_FLOW_STEP_INIT
    _gid, goal = _find(coordinator, "Movie night fund")
    assert goal[fg.DATA_TYPE] == fg.GOAL_TYPE_POINTS
    assert goal[fg.DATA_ASSIGNED_USER_IDS] == [assignee_id]
    # With levels, the first level becomes the base target.
    assert goal[fg.DATA_TARGET_VALUE] == 50.0
    # Goals do not touch the achievements bucket.
    assert not coordinator.achievements_data


@pytest.mark.parametrize(
    ("overrides", "field", "error"),
    [
        ({fg.DATA_LEVELS: "100, 50"}, fg.DATA_LEVELS, "family_goal_invalid_levels"),
        (
            {fg.DATA_ASSIGNED_USER_IDS: []},
            fg.DATA_ASSIGNED_USER_IDS,
            "family_goal_no_assignees",
        ),
    ],
)
async def test_add_family_goal_rejects_bad_input(
    hass: HomeAssistant,
    scenario_minimal: SetupResult,
    overrides: dict[str, Any],
    field: str,
    error: str,
) -> None:
    """Bad levels or an empty team keep the form open with an error."""
    coordinator = scenario_minimal.coordinator
    assignee_id = next(iter(coordinator.assignees_data))

    result = await FlowTestHelper.add_entity_via_options_flow(
        hass,
        scenario_minimal.config_entry.entry_id,
        const.OPTIONS_FLOW_CHALLENGES,
        const.OPTIONS_FLOW_STEP_ADD_CHALLENGE,
        _goal_form(assignee_id, **overrides),
    )

    assert result.get("step_id") == const.OPTIONS_FLOW_STEP_ADD_CHALLENGE
    assert result.get("errors", {}).get(field) == error
    assert not coordinator.challenges_data


async def test_duplicate_goal_name_is_rejected(
    hass: HomeAssistant, scenario_minimal: SetupResult
) -> None:
    """Two goals cannot share a name (the reset service finds goals by name)."""
    coordinator = scenario_minimal.coordinator
    assignee_id = next(iter(coordinator.assignees_data))
    coordinator.family_goal_manager.create_goal(
        {
            fg.DATA_NAME: "Movie night fund",
            fg.DATA_ASSIGNED_USER_IDS: [assignee_id],
            fg.DATA_TYPE: fg.GOAL_TYPE_POINTS,
            fg.DATA_TARGET_VALUE: 10,
        },
        immediate_persist=True,
    )

    result = await FlowTestHelper.add_entity_via_options_flow(
        hass,
        scenario_minimal.config_entry.entry_id,
        const.OPTIONS_FLOW_CHALLENGES,
        const.OPTIONS_FLOW_STEP_ADD_CHALLENGE,
        _goal_form(assignee_id),
    )

    assert result.get("errors", {}).get(fg.DATA_NAME) == "family_goal_name_duplicate"
    assert len(coordinator.challenges_data) == 1


async def test_edit_family_goal_keeps_its_progress(
    hass: HomeAssistant, scenario_minimal: SetupResult
) -> None:
    """Editing settings through the form never loses levels reached or awards."""
    coordinator = scenario_minimal.coordinator
    assignee_id = next(iter(coordinator.assignees_data))
    goal_id = coordinator.family_goal_manager.create_goal(
        {
            fg.DATA_NAME: "Movie night fund",
            fg.DATA_ASSIGNED_USER_IDS: [assignee_id],
            fg.DATA_TYPE: fg.GOAL_TYPE_POINTS,
            fg.DATA_TARGET_VALUE: 100,
        },
        immediate_persist=True,
    )
    goal = coordinator.challenges_data[goal_id]
    goal[fg.DATA_LEVEL] = 2
    goal[fg.DATA_BASELINE] = {assignee_id: 40.0}
    goal[fg.DATA_PROGRESS] = {assignee_id: {fg.DATA_AWARDED: True}}

    result = await FlowTestHelper.edit_entity_via_options_flow(
        hass,
        scenario_minimal.config_entry.entry_id,
        const.OPTIONS_FLOW_CHALLENGES,
        "Movie night fund",
        _goal_form(
            assignee_id, **{fg.DATA_TARGET_VALUE: 250, fg.DATA_REWARD_POINTS: 5}
        ),
    )

    assert result.get("step_id") == const.OPTIONS_FLOW_STEP_INIT
    updated = coordinator.challenges_data[goal_id]
    assert updated[fg.DATA_TARGET_VALUE] == 250.0
    assert updated[fg.DATA_REWARD_POINTS] == 5.0
    assert updated[fg.DATA_LEVEL] == 2
    assert updated[fg.DATA_BASELINE] == {assignee_id: 40.0}
    assert updated[fg.DATA_PROGRESS][assignee_id][fg.DATA_AWARDED] is True


async def test_delete_family_goal(
    hass: HomeAssistant, scenario_minimal: SetupResult
) -> None:
    """Deleting through the menu removes the goal."""
    coordinator = scenario_minimal.coordinator
    assignee_id = next(iter(coordinator.assignees_data))
    coordinator.family_goal_manager.create_goal(
        {
            fg.DATA_NAME: "Movie night fund",
            fg.DATA_ASSIGNED_USER_IDS: [assignee_id],
            fg.DATA_TYPE: fg.GOAL_TYPE_POINTS,
            fg.DATA_TARGET_VALUE: 100,
        },
        immediate_persist=True,
    )
    entry_id = scenario_minimal.config_entry.entry_id

    menu = await FlowTestHelper.navigate_to_entity_menu(
        hass, entry_id, const.OPTIONS_FLOW_CHALLENGES
    )
    result = await hass.config_entries.options.async_configure(
        menu["flow_id"],
        user_input={const.OPTIONS_FLOW_INPUT_MANAGE_ACTION: "delete"},
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={const.OPTIONS_FLOW_INPUT_ENTITY_NAME: "Movie night fund"},
    )
    assert result.get("step_id") == const.OPTIONS_FLOW_STEP_DELETE_CHALLENGE
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={}
    )

    assert result.get("step_id") == const.OPTIONS_FLOW_STEP_INIT
    assert not coordinator.challenges_data


def test_achievements_no_longer_offer_family_goal_types() -> None:
    """Family goals live in their own section; achievements are upstream's."""
    values = {option["value"] for option in const.ACHIEVEMENT_TYPE_OPTIONS}
    assert not values & fg.GOAL_TYPES


async def test_goal_sensors_expose_what_the_cards_read(
    hass: HomeAssistant, scenario_minimal: SetupResult
) -> None:
    """Each goal gets a system sensor and one per person, with the card attributes."""
    from custom_components.choreops.family_goals.sensor import (
        FamilyGoalProgressSensor,
        FamilyGoalSensor,
        build_family_goal_sensors,
    )

    coordinator = scenario_minimal.coordinator
    entry = scenario_minimal.config_entry
    assignee_id = next(iter(coordinator.assignees_data))
    goal_id = coordinator.family_goal_manager.create_goal(
        {
            fg.DATA_NAME: "Movie night fund",
            fg.DATA_ASSIGNED_USER_IDS: [assignee_id],
            fg.DATA_TYPE: fg.GOAL_TYPE_POINTS,
            fg.DATA_TARGET_VALUE: 100,
            fg.DATA_LEVELS: "100:10, 250:25",
            fg.DATA_TOP_MULTIPLIER: 2.0,
        },
        immediate_persist=True,
    )

    sensors = build_family_goal_sensors(coordinator, entry)
    for sensor in sensors:
        sensor.hass = hass
    system = next(s for s in sensors if isinstance(s, FamilyGoalSensor))
    person = next(s for s in sensors if isinstance(s, FamilyGoalProgressSensor))
    assert system.unique_id == f"{entry.entry_id}_{goal_id}_challenge_status"
    assert person.unique_id == (
        f"{entry.entry_id}_{assignee_id}_{goal_id}_challenge_progress"
    )

    await coordinator.economy_manager.deposit(
        assignee_id=assignee_id,
        amount=40.0,
        source=const.POINTS_SOURCE_MANUAL,
        item_name="test",
    )
    assert system.native_value == pytest.approx(40.0)  # 40 of the first level's 100

    attrs = system.extra_state_attributes
    assert attrs[fg.ATTR_GOAL_NAME] == "Movie night fund"
    assert attrs[const.ATTR_TYPE] == fg.GOAL_TYPE_POINTS
    assert attrs[fg.ATTR_TOTAL] == pytest.approx(40.0)
    assert attrs[fg.ATTR_LEVELS] == [100.0, 250.0]
    assert attrs[fg.ATTR_NEXT_TARGET] == 100.0
    assert attrs[fg.ATTR_TOP_MULTIPLIER] == 2.0
    assert list(attrs[fg.ATTR_CONTRIBUTIONS].values()) == [pytest.approx(40.0)]

    person_attrs = person.extra_state_attributes
    assert person_attrs[const.ATTR_RAW_PROGRESS] == pytest.approx(40.0)
    assert person_attrs[const.ATTR_AWARDED] is False
    # The person sensor shows the same shared bar.
    assert person.native_value == pytest.approx(40.0)
