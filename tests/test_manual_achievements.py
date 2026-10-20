"""Tests for manual achievements: given by an approver, never automatic."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.exceptions import HomeAssistantError
import pytest

from custom_components.choreops import const
from custom_components.choreops.sensor import (
    AssigneeAchievementProgressSensor,
    SystemAchievementSensor,
)
from tests.helpers import SetupResult, setup_from_yaml

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


@pytest.fixture
async def scenario_full(
    hass: HomeAssistant,
    mock_hass_users: dict[str, Any],
) -> SetupResult:
    """Load full scenario: 3 assignees (Zoë, Max!, Lila)."""
    return await setup_from_yaml(
        hass,
        mock_hass_users,
        "tests/scenarios/scenario_full.yaml",
    )


def _make_achievement(setup: SetupResult, name: str, points: float) -> str:
    """Create a manual achievement and return its ID."""
    return setup.coordinator.gamification_manager.create_achievement(
        {
            const.DATA_ACHIEVEMENT_NAME: name,
            const.DATA_ACHIEVEMENT_REWARD_POINTS: points,
        }
    )


def _points(setup: SetupResult, assignee_id: str) -> float:
    return float(
        setup.coordinator.assignees_data[assignee_id].get(const.DATA_USER_POINTS, 0.0)
    )


def _entry(setup: SetupResult, achievement_id: str, assignee_id: str) -> dict[str, Any]:
    achievement = setup.coordinator.achievements_data[achievement_id]
    return dict(achievement[const.DATA_ACHIEVEMENT_PROGRESS][assignee_id])


async def test_award_pays_points_and_counts_each_time(
    hass: HomeAssistant, scenario_full: SetupResult
) -> None:
    """Every award pays the reward points and raises the person's count."""
    gm = scenario_full.coordinator.gamification_manager
    zoe = scenario_full.assignee_ids["Zoë"]
    achievement_id = _make_achievement(scenario_full, "Kitchen Hero", 20.0)
    before = _points(scenario_full, zoe)

    assert await gm.award_achievement(zoe, achievement_id) == 1
    await hass.async_block_till_done()
    assert _points(scenario_full, zoe) == pytest.approx(before + 20.0)

    assert await gm.award_achievement(zoe, achievement_id) == 2
    await hass.async_block_till_done()
    assert _points(scenario_full, zoe) == pytest.approx(before + 40.0)

    entry = _entry(scenario_full, achievement_id, zoe)
    assert entry[const.DATA_ACHIEVEMENT_AWARD_COUNT] == 2
    assert entry[const.DATA_ACHIEVEMENT_LAST_AWARDED]


async def test_award_without_points_pays_nothing(
    hass: HomeAssistant, scenario_full: SetupResult
) -> None:
    """An achievement with no reward points is recognition only."""
    gm = scenario_full.coordinator.gamification_manager
    max_ = scenario_full.assignee_ids["Max!"]
    achievement_id = _make_achievement(scenario_full, "Helped a Sibling", 0.0)
    before = _points(scenario_full, max_)

    await gm.award_achievement(max_, achievement_id)
    await hass.async_block_till_done()

    assert _points(scenario_full, max_) == pytest.approx(before)
    assert (
        _entry(scenario_full, achievement_id, max_)[const.DATA_ACHIEVEMENT_AWARD_COUNT]
        == 1
    )


async def test_award_is_never_automatic(
    hass: HomeAssistant, scenario_full: SetupResult
) -> None:
    """Earning points or finishing chores does not award a manual achievement."""
    coordinator = scenario_full.coordinator
    zoe = scenario_full.assignee_ids["Zoë"]
    achievement_id = _make_achievement(scenario_full, "Honor Roll", 50.0)

    await coordinator.economy_manager.deposit(
        assignee_id=zoe,
        amount=500.0,
        source=const.POINTS_SOURCE_MANUAL,
        item_name="test",
    )
    coordinator.gamification_manager.recalculate_all_badges()
    await hass.async_block_till_done()

    assert zoe not in coordinator.achievements_data[achievement_id].get(
        const.DATA_ACHIEVEMENT_PROGRESS, {}
    )


async def test_award_unknown_achievement_or_person_raises(
    scenario_full: SetupResult,
) -> None:
    """Bad IDs are reported, not silently ignored."""
    gm = scenario_full.coordinator.gamification_manager
    zoe = scenario_full.assignee_ids["Zoë"]
    achievement_id = _make_achievement(scenario_full, "Real One", 0.0)
    with pytest.raises(HomeAssistantError):
        await gm.award_achievement(zoe, "missing")
    with pytest.raises(HomeAssistantError):
        await gm.award_achievement("missing", achievement_id)


async def test_award_service_by_name(
    hass: HomeAssistant, scenario_full: SetupResult
) -> None:
    """The service finds people and achievements by name and returns the count."""
    zoe = scenario_full.assignee_ids["Zoë"]
    achievement_id = _make_achievement(scenario_full, "Above and Beyond", 10.0)

    response = await hass.services.async_call(
        const.DOMAIN,
        const.SERVICE_AWARD_ACHIEVEMENT,
        {"user_name": "Zoë", "achievement_name": "Above and Beyond"},
        blocking=True,
        return_response=True,
    )
    assert response == {"times_awarded": 1}
    assert (
        _entry(scenario_full, achievement_id, zoe)[const.DATA_ACHIEVEMENT_AWARD_COUNT]
        == 1
    )


async def test_legacy_awarded_flag_counts_as_one(
    hass: HomeAssistant, scenario_full: SetupResult
) -> None:
    """Awards made before counting existed read as one, and the next makes two."""
    coordinator = scenario_full.coordinator
    zoe = scenario_full.assignee_ids["Zoë"]
    achievement_id = _make_achievement(scenario_full, "Old Award", 0.0)
    coordinator.achievements_data[achievement_id][const.DATA_ACHIEVEMENT_PROGRESS] = {
        zoe: {const.DATA_ACHIEVEMENT_AWARDED: True}
    }

    sensor = AssigneeAchievementProgressSensor(
        coordinator,
        scenario_full.config_entry,
        zoe,
        "Zoë",
        achievement_id,
        "Old Award",
    )
    assert sensor.native_value == 1
    assert sensor.extra_state_attributes["awarded"] is True

    assert (
        await coordinator.gamification_manager.award_achievement(zoe, achievement_id)
        == 2
    )


async def test_sensors_expose_count_and_holders(
    hass: HomeAssistant, scenario_full: SetupResult
) -> None:
    """Person sensor shows their count; system sensor totals everyone."""
    coordinator = scenario_full.coordinator
    zoe = scenario_full.assignee_ids["Zoë"]
    max_ = scenario_full.assignee_ids["Max!"]
    achievement_id = _make_achievement(scenario_full, "Kitchen Hero", 5.0)
    gm = coordinator.gamification_manager
    await gm.award_achievement(zoe, achievement_id)
    await gm.award_achievement(zoe, achievement_id)
    await gm.award_achievement(max_, achievement_id)

    entry = scenario_full.config_entry
    person = AssigneeAchievementProgressSensor(
        coordinator, entry, zoe, "Zoë", achievement_id, "Kitchen Hero"
    )
    person.hass = hass
    assert person.native_value == 2
    attrs = person.extra_state_attributes
    assert attrs["award_count"] == 2
    assert attrs["awarded"] is True
    assert attrs[const.ATTR_REWARD_POINTS] == 5.0

    none_yet = AssigneeAchievementProgressSensor(
        coordinator,
        entry,
        scenario_full.assignee_ids["Lila"],
        "Lila",
        achievement_id,
        "Kitchen Hero",
    )
    none_yet.hass = hass
    assert none_yet.native_value == 0
    assert none_yet.extra_state_attributes["awarded"] is False

    system = SystemAchievementSensor(coordinator, entry, achievement_id, "Kitchen Hero")
    system.hass = hass
    assert system.native_value == 3
    assert system.extra_state_attributes["awarded_to"] == {"Zoë": 2, "Max!": 1}
