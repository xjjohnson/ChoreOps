"""Data owned by Family Goals, Reward Pools and Achievements survives a restart."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from custom_components.choreops import const
from custom_components.choreops.family_goals import const as fg
from tests.helpers.setup import SetupResult, setup_from_yaml

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


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


async def test_goal_pool_and_achievement_data_survive_two_restarts(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """Progress, pool contributions and award counts are intact after restarts."""
    coordinator = scenario_full.coordinator
    entry = scenario_full.config_entry
    zoe = scenario_full.assignee_ids["Zoë"]
    max_ = scenario_full.assignee_ids["Max!"]

    goal_id = coordinator.family_goal_manager.create_goal(
        {
            fg.DATA_NAME: "Restart goal",
            fg.DATA_ASSIGNED_USER_IDS: [zoe, max_],
            fg.DATA_TYPE: fg.GOAL_TYPE_POINTS,
            fg.DATA_TARGET_VALUE: 500.0,
            fg.DATA_REWARD_POINTS: 5.0,
        }
    )
    await coordinator.economy_manager.deposit(
        assignee_id=zoe,
        amount=40.0,
        source=const.POINTS_SOURCE_MANUAL,
        item_name="restart test",
    )
    reward_id = scenario_full.reward_ids["Pick Next Movie"]
    coordinator.reward_manager.update_reward(
        reward_id, {const.DATA_REWARD_POOLED: True}
    )
    await coordinator.economy_manager.deposit(
        assignee_id=zoe,
        amount=50.0,
        source=const.POINTS_SOURCE_MANUAL,
        item_name="pool funds",
    )
    await coordinator.reward_pool_manager.contribute_to_pool(zoe, reward_id, 12.0)
    await hass.async_block_till_done()

    achievement_id = coordinator.gamification_manager.create_achievement(
        {
            const.DATA_ACHIEVEMENT_NAME: "Restart Hero",
            const.DATA_ACHIEVEMENT_REWARD_POINTS: 3.0,
        }
    )
    await coordinator.gamification_manager.award_achievement(zoe, achievement_id)
    await coordinator.gamification_manager.award_achievement(zoe, achievement_id)
    await hass.async_block_till_done()

    goal_total = coordinator.family_goal_manager.get_total(goal_id)
    assert goal_total >= 40.0
    coordinator._persist(immediate=True)

    for _ in range(2):
        await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        reloaded = entry.runtime_data

        assert reloaded.family_goal_manager.get_total(goal_id) == pytest.approx(
            goal_total
        )
        reward = reloaded.rewards_data[reward_id]
        assert reward[const.DATA_REWARD_POOL_CONTRIBUTIONS] == {zoe: 12.0}
        progress = reloaded.achievements_data[achievement_id][
            const.DATA_ACHIEVEMENT_PROGRESS
        ][zoe]
        assert progress[const.DATA_ACHIEVEMENT_AWARD_COUNT] == 2
