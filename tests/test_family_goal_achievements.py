"""Tests for family goal achievements (one pooled total, everyone awarded together)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from custom_components.choreops import const
from tests.helpers import SetupResult, setup_from_yaml

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


def _create_family_goal(
    setup: SetupResult,
    *,
    goal_type: str,
    target: float,
    reward: float,
    assigned: list[str],
) -> str:
    """Create a family goal achievement and return its internal ID."""
    return setup.coordinator.gamification_manager.create_achievement(
        {
            const.DATA_ACHIEVEMENT_NAME: f"Family goal {goal_type} {target}",
            const.DATA_ACHIEVEMENT_ASSIGNED_USER_IDS: assigned,
            const.DATA_ACHIEVEMENT_TYPE: goal_type,
            const.DATA_ACHIEVEMENT_TARGET_VALUE: target,
            const.DATA_ACHIEVEMENT_REWARD_POINTS: reward,
        }
    )


def _awarded(setup: SetupResult, achievement_id: str, assignee_id: str) -> bool:
    """Return whether the assignee holds the achievement award."""
    achievement = setup.coordinator.achievements_data[achievement_id]
    progress = achievement.get(const.DATA_ACHIEVEMENT_PROGRESS, {})
    return bool(progress.get(assignee_id, {}).get(const.DATA_ACHIEVEMENT_AWARDED))


async def _earn_points(setup: SetupResult, assignee_id: str, amount: float) -> None:
    """Credit points through the economy manager (counts as points earned)."""
    await setup.coordinator.economy_manager.deposit(
        assignee_id=assignee_id,
        amount=amount,
        source=const.POINTS_SOURCE_MANUAL,
        item_name="family goal test",
    )


def _set_all_time_approved(setup: SetupResult, assignee_id: str, approved: int) -> None:
    """Set an assignee's all-time approved chore count (v43+ nested structure)."""
    assignee_data: Any = setup.coordinator.assignees_data[assignee_id]
    chore_periods = assignee_data.setdefault(const.DATA_USER_CHORE_PERIODS, {})
    chore_periods[const.DATA_USER_CHORE_DATA_PERIODS_ALL_TIME] = {
        const.PERIOD_ALL_TIME: {const.DATA_USER_CHORE_DATA_PERIOD_APPROVED: approved}
    }


async def test_points_goal_pools_everyone_and_awards_all_together(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """No one is awarded until the POOLED total hits the target, then all are."""
    gm = scenario_full.coordinator.gamification_manager
    zoe = scenario_full.assignee_ids["Zoë"]
    max_ = scenario_full.assignee_ids["Max!"]
    lila = scenario_full.assignee_ids["Lila"]
    goal_id = _create_family_goal(
        scenario_full,
        goal_type=const.ACHIEVEMENT_TYPE_FAMILY_POINTS,
        target=100.0,
        reward=25.0,
        assigned=[zoe, max_, lila],
    )

    await _earn_points(scenario_full, zoe, 40.0)
    await _earn_points(scenario_full, max_, 30.0)
    await gm._evaluate_assignee(zoe)
    await gm._evaluate_assignee(max_)
    await hass.async_block_till_done()

    # 70 of 100 pooled: nobody has it yet, even though no one hit 100 alone.
    assert gm.get_family_achievement_total(goal_id) == pytest.approx(70.0)
    assert not any(_awarded(scenario_full, goal_id, a) for a in (zoe, max_, lila))

    # Lila's contribution crosses the shared line; Lila's eval awards EVERYONE.
    await _earn_points(scenario_full, lila, 35.0)
    await gm._evaluate_assignee(lila)
    await hass.async_block_till_done()

    assert gm.get_family_achievement_total(goal_id) >= 100.0
    assert all(_awarded(scenario_full, goal_id, a) for a in (zoe, max_, lila))


async def test_reward_paid_once_to_each_person(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """Everyone gets the full reward exactly once, even if re-evaluated."""
    coordinator = scenario_full.coordinator
    gm = coordinator.gamification_manager
    zoe = scenario_full.assignee_ids["Zoë"]
    max_ = scenario_full.assignee_ids["Max!"]
    _create_family_goal(
        scenario_full,
        goal_type=const.ACHIEVEMENT_TYPE_FAMILY_POINTS,
        target=50.0,
        reward=25.0,
        assigned=[zoe, max_],
    )

    await _earn_points(scenario_full, zoe, 30.0)
    await _earn_points(scenario_full, max_, 30.0)
    await gm._evaluate_assignee(zoe)
    await hass.async_block_till_done()

    zoe_balance = float(coordinator.assignees_data[zoe][const.DATA_USER_POINTS])
    max_balance = float(coordinator.assignees_data[max_][const.DATA_USER_POINTS])
    # 30 earned + 25 reward each.
    assert zoe_balance == pytest.approx(55.0)
    assert max_balance == pytest.approx(55.0)

    # Re-evaluating everyone must not pay out again.
    await gm._evaluate_assignee(zoe)
    await gm._evaluate_assignee(max_)
    await hass.async_block_till_done()

    assert float(coordinator.assignees_data[zoe][const.DATA_USER_POINTS]) == (
        pytest.approx(zoe_balance)
    )
    assert float(coordinator.assignees_data[max_][const.DATA_USER_POINTS]) == (
        pytest.approx(max_balance)
    )


async def test_unassigned_people_do_not_contribute_or_win(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """Only assigned people count toward, and receive, the family goal."""
    gm = scenario_full.coordinator.gamification_manager
    zoe = scenario_full.assignee_ids["Zoë"]
    max_ = scenario_full.assignee_ids["Max!"]
    lila = scenario_full.assignee_ids["Lila"]
    goal_id = _create_family_goal(
        scenario_full,
        goal_type=const.ACHIEVEMENT_TYPE_FAMILY_POINTS,
        target=100.0,
        reward=0.0,
        assigned=[zoe, max_],
    )

    await _earn_points(scenario_full, lila, 500.0)
    await _earn_points(scenario_full, zoe, 10.0)
    await gm._evaluate_assignee(lila)
    await gm._evaluate_assignee(zoe)
    await hass.async_block_till_done()

    assert set(gm.get_family_contributions(goal_id)) == {zoe, max_}
    assert gm.get_family_achievement_total(goal_id) == pytest.approx(10.0)
    assert not _awarded(scenario_full, goal_id, lila)
    assert not any(_awarded(scenario_full, goal_id, a) for a in (zoe, max_))


async def test_chores_goal_sums_all_time_approved_chores(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """A chore-count family goal sums each person's all-time approved chores."""
    gm = scenario_full.coordinator.gamification_manager
    zoe = scenario_full.assignee_ids["Zoë"]
    max_ = scenario_full.assignee_ids["Max!"]
    goal_id = _create_family_goal(
        scenario_full,
        goal_type=const.ACHIEVEMENT_TYPE_FAMILY_CHORES,
        target=10.0,
        reward=5.0,
        assigned=[zoe, max_],
    )

    _set_all_time_approved(scenario_full, zoe, 6)
    _set_all_time_approved(scenario_full, max_, 3)
    await gm._evaluate_assignee(zoe)
    await hass.async_block_till_done()

    assert gm.get_family_achievement_total(goal_id) == pytest.approx(9.0)
    assert not any(_awarded(scenario_full, goal_id, a) for a in (zoe, max_))

    _set_all_time_approved(scenario_full, max_, 5)
    await gm._evaluate_assignee(max_)
    await hass.async_block_till_done()

    assert gm.get_family_achievement_total(goal_id) == pytest.approx(11.0)
    assert all(_awarded(scenario_full, goal_id, a) for a in (zoe, max_))


async def test_goal_sensors_show_pooled_progress(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """The family total and per-person shares are exposed for dashboards."""
    gm = scenario_full.coordinator.gamification_manager
    zoe = scenario_full.assignee_ids["Zoë"]
    max_ = scenario_full.assignee_ids["Max!"]
    goal_id = _create_family_goal(
        scenario_full,
        goal_type=const.ACHIEVEMENT_TYPE_FAMILY_POINTS,
        target=200.0,
        reward=0.0,
        assigned=[zoe, max_],
    )

    await _earn_points(scenario_full, zoe, 60.0)
    await _earn_points(scenario_full, max_, 40.0)

    contributions = gm.get_family_contributions(goal_id)
    assert contributions[zoe] == pytest.approx(60.0)
    assert contributions[max_] == pytest.approx(40.0)
    assert gm.get_family_achievement_total(goal_id) == pytest.approx(100.0)


async def test_reset_restarts_points_goal_from_zero(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """Reset zeroes the pooled total, clears awards, and the goal can be earned again."""
    gm = scenario_full.coordinator.gamification_manager
    zoe = scenario_full.assignee_ids["Zoë"]
    max_ = scenario_full.assignee_ids["Max!"]
    goal_id = _create_family_goal(
        scenario_full,
        goal_type=const.ACHIEVEMENT_TYPE_FAMILY_POINTS,
        target=50.0,
        reward=10.0,
        assigned=[zoe, max_],
    )
    await _earn_points(scenario_full, zoe, 30.0)
    await _earn_points(scenario_full, max_, 30.0)
    await gm._evaluate_assignee(zoe)
    await hass.async_block_till_done()
    assert _awarded(scenario_full, goal_id, zoe)

    gm.reset_family_goal(goal_id)

    assert gm.get_family_achievement_total(goal_id) == pytest.approx(0.0)
    assert not _awarded(scenario_full, goal_id, zoe)
    assert not _awarded(scenario_full, goal_id, max_)

    # Only NEW points count now; the old 60 does not instantly re-award.
    await gm._evaluate_assignee(zoe)
    assert not _awarded(scenario_full, goal_id, zoe)
    await _earn_points(scenario_full, zoe, 25.0)
    await _earn_points(scenario_full, max_, 25.0)
    await gm._evaluate_assignee(zoe)
    await hass.async_block_till_done()
    # 50 new points + the 10-point award each person got when the goal re-fires.
    assert gm.get_family_achievement_total(goal_id) >= 50.0
    assert _awarded(scenario_full, goal_id, zoe)
    assert _awarded(scenario_full, goal_id, max_)


async def test_reset_service_restarts_goal_by_name(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """The reset_family_goal service looks the goal up by name and restarts it."""
    gm = scenario_full.coordinator.gamification_manager
    zoe = scenario_full.assignee_ids["Zoë"]
    goal_id = _create_family_goal(
        scenario_full,
        goal_type=const.ACHIEVEMENT_TYPE_FAMILY_POINTS,
        target=1000.0,
        reward=0.0,
        assigned=[zoe],
    )
    await _earn_points(scenario_full, zoe, 40.0)
    assert gm.get_family_achievement_total(goal_id) == pytest.approx(40.0)

    name = scenario_full.coordinator.achievements_data[goal_id][
        const.DATA_ACHIEVEMENT_NAME
    ]
    await hass.services.async_call(
        const.DOMAIN,
        const.SERVICE_RESET_FAMILY_GOAL,
        {const.SERVICE_FIELD_ACHIEVEMENT_NAME: name},
        blocking=True,
    )
    assert gm.get_family_achievement_total(goal_id) == pytest.approx(0.0)


def _fake_snapshot(
    gm: Any, open_: int, done: int, *, overdue: bool = False, missed: bool = False
) -> None:
    """Force the per-person snapshot used by the caught-up streak."""
    gm._family_caught_up_snapshots = lambda *a, **k: {
        "p": {"open": open_, "done": done, "overdue": overdue, "missed": missed}
    }


async def test_caught_up_streak_counts_breaks_and_awards(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """Caught-up days accumulate once per day, a miss breaks it, target awards all."""
    gm = scenario_full.coordinator.gamification_manager
    zoe = scenario_full.assignee_ids["Zoë"]
    max_ = scenario_full.assignee_ids["Max!"]
    goal_id = _create_family_goal(
        scenario_full,
        goal_type=const.ACHIEVEMENT_TYPE_FAMILY_CAUGHT_UP,
        target=2.0,
        reward=5.0,
        assigned=[zoe, max_],
    )
    achievement = scenario_full.coordinator.achievements_data[goal_id]

    # Chores still outstanding: day does not count.
    _fake_snapshot(gm, open_=1, done=2)
    await gm._evaluate_assignee(zoe)
    assert gm.get_family_achievement_total(goal_id) == 0

    # Everyone done: day 1, and re-evaluating the same day is idempotent.
    _fake_snapshot(gm, open_=0, done=3)
    await gm._evaluate_assignee(zoe)
    await gm._evaluate_assignee(max_)
    assert gm.get_family_achievement_total(goal_id) == 1

    # Pretend that was yesterday, then a missed chore breaks the streak.
    achievement[const.DATA_ACHIEVEMENT_FAMILY_STREAK_LAST_DAY] = "2000-01-01"
    _fake_snapshot(gm, open_=1, done=2, missed=True)
    await gm._evaluate_assignee(zoe)
    assert gm.get_family_achievement_total(goal_id) == 0

    # Two good days in a row reach the target and award everyone.
    _fake_snapshot(gm, open_=0, done=3)
    await gm._evaluate_assignee(zoe)
    achievement[const.DATA_ACHIEVEMENT_FAMILY_STREAK_LAST_DAY] = "2000-01-01"
    await gm._evaluate_assignee(zoe)
    await hass.async_block_till_done()
    assert gm.get_family_achievement_total(goal_id) == 2
    assert _awarded(scenario_full, goal_id, zoe)
    assert _awarded(scenario_full, goal_id, max_)

    # Reset starts the streak over.
    gm.reset_family_goal(goal_id)
    assert gm.get_family_achievement_total(goal_id) == 0
    assert not _awarded(scenario_full, goal_id, zoe)


async def test_caught_up_status_reads_real_chore_state(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """The unmocked snapshot path runs and reports every assigned person."""
    gm = scenario_full.coordinator.gamification_manager
    zoe = scenario_full.assignee_ids["Zoë"]
    max_ = scenario_full.assignee_ids["Max!"]
    goal_id = _create_family_goal(
        scenario_full,
        goal_type=const.ACHIEVEMENT_TYPE_FAMILY_CAUGHT_UP,
        target=3.0,
        reward=0.0,
        assigned=[zoe, max_],
    )
    status = gm.get_family_caught_up_status(goal_id)
    assert len(status) == 2
    assert all("still to do today" in text for text in status.values())
    await gm._evaluate_assignee(zoe)  # must not raise
