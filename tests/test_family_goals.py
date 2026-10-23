"""Tests for family goals (one pooled total, everyone awarded together)."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

import pytest

from custom_components.choreops import const
from custom_components.choreops.family_goals import builders, const as fg
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
    """Create a family goal and return its internal ID."""
    return setup.coordinator.family_goal_manager.create_goal(
        {
            fg.DATA_NAME: f"Family goal {goal_type} {target}",
            fg.DATA_ASSIGNED_USER_IDS: assigned,
            fg.DATA_TYPE: goal_type,
            fg.DATA_TARGET_VALUE: target,
            fg.DATA_REWARD_POINTS: reward,
        }
    )


def _awarded(setup: SetupResult, goal_id: str, assignee_id: str) -> bool:
    """Return whether the assignee holds the goal award."""
    goal = setup.coordinator.challenges_data[goal_id]
    progress = goal.get(fg.DATA_PROGRESS, {})
    return bool(progress.get(assignee_id, {}).get(fg.DATA_AWARDED))


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
    gm = scenario_full.coordinator.family_goal_manager
    zoe = scenario_full.assignee_ids["Zoë"]
    max_ = scenario_full.assignee_ids["Max!"]
    lila = scenario_full.assignee_ids["Lila"]
    goal_id = _create_family_goal(
        scenario_full,
        goal_type=fg.GOAL_TYPE_POINTS,
        target=100.0,
        reward=25.0,
        assigned=[zoe, max_, lila],
    )

    await _earn_points(scenario_full, zoe, 40.0)
    await _earn_points(scenario_full, max_, 30.0)
    await gm.evaluate_assignee(zoe)
    await gm.evaluate_assignee(max_)
    await hass.async_block_till_done()

    # 70 of 100 pooled: nobody has it yet, even though no one hit 100 alone.
    assert gm.get_total(goal_id) == pytest.approx(70.0)
    assert not any(_awarded(scenario_full, goal_id, a) for a in (zoe, max_, lila))

    # Lila's contribution crosses the shared line; Lila's eval awards EVERYONE.
    await _earn_points(scenario_full, lila, 35.0)
    await gm.evaluate_assignee(lila)
    await hass.async_block_till_done()

    assert gm.get_total(goal_id) >= 100.0
    assert all(_awarded(scenario_full, goal_id, a) for a in (zoe, max_, lila))


async def test_reward_paid_once_to_each_person(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """Everyone gets the full reward exactly once, even if re-evaluated."""
    coordinator = scenario_full.coordinator
    gm = coordinator.family_goal_manager
    zoe = scenario_full.assignee_ids["Zoë"]
    max_ = scenario_full.assignee_ids["Max!"]
    _create_family_goal(
        scenario_full,
        goal_type=fg.GOAL_TYPE_POINTS,
        target=50.0,
        reward=25.0,
        assigned=[zoe, max_],
    )

    await _earn_points(scenario_full, zoe, 30.0)
    await _earn_points(scenario_full, max_, 30.0)
    await gm.evaluate_assignee(zoe)
    await hass.async_block_till_done()

    zoe_balance = float(coordinator.assignees_data[zoe][const.DATA_USER_POINTS])
    max_balance = float(coordinator.assignees_data[max_][const.DATA_USER_POINTS])
    # 30 earned + 25 reward each.
    assert zoe_balance == pytest.approx(55.0)
    assert max_balance == pytest.approx(55.0)

    # Re-evaluating everyone must not pay out again.
    await gm.evaluate_assignee(zoe)
    await gm.evaluate_assignee(max_)
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
    gm = scenario_full.coordinator.family_goal_manager
    zoe = scenario_full.assignee_ids["Zoë"]
    max_ = scenario_full.assignee_ids["Max!"]
    lila = scenario_full.assignee_ids["Lila"]
    goal_id = _create_family_goal(
        scenario_full,
        goal_type=fg.GOAL_TYPE_POINTS,
        target=100.0,
        reward=0.0,
        assigned=[zoe, max_],
    )

    await _earn_points(scenario_full, lila, 500.0)
    await _earn_points(scenario_full, zoe, 10.0)
    await gm.evaluate_assignee(lila)
    await gm.evaluate_assignee(zoe)
    await hass.async_block_till_done()

    assert set(gm.get_contributions(goal_id)) == {zoe, max_}
    assert gm.get_total(goal_id) == pytest.approx(10.0)
    assert not _awarded(scenario_full, goal_id, lila)
    assert not any(_awarded(scenario_full, goal_id, a) for a in (zoe, max_))


async def test_chores_goal_sums_all_time_approved_chores(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """A chore-count family goal sums each person's all-time approved chores."""
    gm = scenario_full.coordinator.family_goal_manager
    zoe = scenario_full.assignee_ids["Zoë"]
    max_ = scenario_full.assignee_ids["Max!"]
    goal_id = _create_family_goal(
        scenario_full,
        goal_type=fg.GOAL_TYPE_CHORES,
        target=10.0,
        reward=5.0,
        assigned=[zoe, max_],
    )

    _set_all_time_approved(scenario_full, zoe, 6)
    _set_all_time_approved(scenario_full, max_, 3)
    await gm.evaluate_assignee(zoe)
    await hass.async_block_till_done()

    assert gm.get_total(goal_id) == pytest.approx(9.0)
    assert not any(_awarded(scenario_full, goal_id, a) for a in (zoe, max_))

    _set_all_time_approved(scenario_full, max_, 5)
    await gm.evaluate_assignee(max_)
    await hass.async_block_till_done()

    assert gm.get_total(goal_id) == pytest.approx(11.0)
    assert all(_awarded(scenario_full, goal_id, a) for a in (zoe, max_))


async def test_goal_sensors_show_pooled_progress(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """The family total and per-person shares are exposed for dashboards."""
    gm = scenario_full.coordinator.family_goal_manager
    zoe = scenario_full.assignee_ids["Zoë"]
    max_ = scenario_full.assignee_ids["Max!"]
    goal_id = _create_family_goal(
        scenario_full,
        goal_type=fg.GOAL_TYPE_POINTS,
        target=200.0,
        reward=0.0,
        assigned=[zoe, max_],
    )

    await _earn_points(scenario_full, zoe, 60.0)
    await _earn_points(scenario_full, max_, 40.0)

    contributions = gm.get_contributions(goal_id)
    assert contributions[zoe] == pytest.approx(60.0)
    assert contributions[max_] == pytest.approx(40.0)
    assert gm.get_total(goal_id) == pytest.approx(100.0)


async def test_reset_restarts_points_goal_from_zero(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """Reset zeroes the pooled total, clears awards, and the goal can be earned again."""
    gm = scenario_full.coordinator.family_goal_manager
    zoe = scenario_full.assignee_ids["Zoë"]
    max_ = scenario_full.assignee_ids["Max!"]
    goal_id = _create_family_goal(
        scenario_full,
        goal_type=fg.GOAL_TYPE_POINTS,
        target=50.0,
        reward=10.0,
        assigned=[zoe, max_],
    )
    await _earn_points(scenario_full, zoe, 30.0)
    await _earn_points(scenario_full, max_, 30.0)
    await gm.evaluate_assignee(zoe)
    await hass.async_block_till_done()
    assert _awarded(scenario_full, goal_id, zoe)

    gm.reset_goal(goal_id)

    assert gm.get_total(goal_id) == pytest.approx(0.0)
    assert not _awarded(scenario_full, goal_id, zoe)
    assert not _awarded(scenario_full, goal_id, max_)

    # Only NEW points count now; the old 60 does not instantly re-award.
    await gm.evaluate_assignee(zoe)
    assert not _awarded(scenario_full, goal_id, zoe)
    await _earn_points(scenario_full, zoe, 25.0)
    await _earn_points(scenario_full, max_, 25.0)
    await gm.evaluate_assignee(zoe)
    await hass.async_block_till_done()
    # 50 new points + the 10-point award each person got when the goal re-fires.
    assert gm.get_total(goal_id) >= 50.0
    assert _awarded(scenario_full, goal_id, zoe)
    assert _awarded(scenario_full, goal_id, max_)


async def test_reset_service_restarts_goal_by_name(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """The reset_family_goal service looks the goal up by name and restarts it."""
    gm = scenario_full.coordinator.family_goal_manager
    zoe = scenario_full.assignee_ids["Zoë"]
    goal_id = _create_family_goal(
        scenario_full,
        goal_type=fg.GOAL_TYPE_POINTS,
        target=1000.0,
        reward=0.0,
        assigned=[zoe],
    )
    await _earn_points(scenario_full, zoe, 40.0)
    assert gm.get_total(goal_id) == pytest.approx(40.0)

    name = scenario_full.coordinator.challenges_data[goal_id][fg.DATA_NAME]
    await hass.services.async_call(
        const.DOMAIN,
        fg.SERVICE_RESET_FAMILY_GOAL,
        {fg.SERVICE_FIELD_GOAL_NAME: name},
        blocking=True,
    )
    assert gm.get_total(goal_id) == pytest.approx(0.0)


def _fake_snapshot(
    gm: Any, open_: int, done: int, *, overdue: bool = False, missed: bool = False
) -> None:
    """Force the per-person snapshot used by the caught-up streak."""
    gm._caught_up_snapshots = lambda *a, **k: {
        "p": {"open": open_, "done": done, "overdue": overdue, "missed": missed}
    }


async def test_caught_up_streak_counts_breaks_and_awards(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """Caught-up days accumulate once per day, a miss breaks it, target awards all."""
    gm = scenario_full.coordinator.family_goal_manager
    zoe = scenario_full.assignee_ids["Zoë"]
    max_ = scenario_full.assignee_ids["Max!"]
    goal_id = _create_family_goal(
        scenario_full,
        goal_type=fg.GOAL_TYPE_CAUGHT_UP,
        target=2.0,
        reward=5.0,
        assigned=[zoe, max_],
    )
    goal = scenario_full.coordinator.challenges_data[goal_id]

    # Chores still outstanding: day does not count.
    _fake_snapshot(gm, open_=1, done=2)
    await gm.evaluate_assignee(zoe)
    assert gm.get_total(goal_id) == 0

    # Everyone done: day 1, and re-evaluating the same day is idempotent.
    _fake_snapshot(gm, open_=0, done=3)
    await gm.evaluate_assignee(zoe)
    await gm.evaluate_assignee(max_)
    assert gm.get_total(goal_id) == 1

    # Pretend that was yesterday, then a missed chore breaks the streak.
    goal[fg.DATA_STREAK_LAST_DAY] = "2000-01-01"
    _fake_snapshot(gm, open_=1, done=2, missed=True)
    await gm.evaluate_assignee(zoe)
    assert gm.get_total(goal_id) == 0

    # Two good days in a row reach the target and award everyone.
    _fake_snapshot(gm, open_=0, done=3)
    await gm.evaluate_assignee(zoe)
    goal[fg.DATA_STREAK_LAST_DAY] = "2000-01-01"
    await gm.evaluate_assignee(zoe)
    await hass.async_block_till_done()
    assert gm.get_total(goal_id) == 2
    assert _awarded(scenario_full, goal_id, zoe)
    assert _awarded(scenario_full, goal_id, max_)

    # Reset starts the streak over.
    gm.reset_goal(goal_id)
    assert gm.get_total(goal_id) == 0
    assert not _awarded(scenario_full, goal_id, zoe)


async def test_caught_up_status_reads_real_chore_state(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """The unmocked snapshot path runs and reports every assigned person."""
    gm = scenario_full.coordinator.family_goal_manager
    zoe = scenario_full.assignee_ids["Zoë"]
    max_ = scenario_full.assignee_ids["Max!"]
    goal_id = _create_family_goal(
        scenario_full,
        goal_type=fg.GOAL_TYPE_CAUGHT_UP,
        target=3.0,
        reward=0.0,
        assigned=[zoe, max_],
    )
    status = gm.get_caught_up_status(goal_id)
    assert len(status) == 2
    for counts in status.values():
        assert set(counts) == {"open", "done", "overdue"}
        assert isinstance(counts["open"], int)
        assert isinstance(counts["overdue"], bool)
    await gm.evaluate_assignee(zoe)  # must not raise


def test_parse_levels() -> None:
    """Levels are target[:reward] items; targets increase, rewards are optional."""
    assert builders.parse_levels("100:10, 250, 500 : 50") == [
        (100.0, 10.0),
        (250.0, None),
        (500.0, 50.0),
    ]
    assert builders.parse_levels("") == []
    for bad in ("abc", "0, 5", "100, 100", "200, 100", "100:-5", "100:x"):
        with pytest.raises(ValueError):
            builders.parse_levels(bad)


async def test_each_level_pays_its_own_reward_and_stays_open(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """Each level pays its own reward (or the base one); only the last closes."""
    coordinator = scenario_full.coordinator
    gm = coordinator.family_goal_manager
    zoe = scenario_full.assignee_ids["Zoë"]
    max_ = scenario_full.assignee_ids["Max!"]
    goal_id = _create_family_goal(
        scenario_full,
        goal_type=fg.GOAL_TYPE_POINTS,
        target=1.0,
        reward=10.0,
        assigned=[zoe, max_],
    )
    # Level 1 pays its own 7, level 2 has no reward so pays the base 10.
    coordinator.challenges_data[goal_id][fg.DATA_LEVELS] = "50:7, 150"

    def balance(a: str) -> float:
        return float(coordinator.assignees_data[a][const.DATA_USER_POINTS])

    await _earn_points(scenario_full, zoe, 30.0)
    await _earn_points(scenario_full, max_, 30.0)
    await gm.evaluate_assignee(zoe)
    await hass.async_block_till_done()

    info = gm.get_level_info(goal_id)
    assert info["level"] == 1
    assert info["next_target"] == 150.0
    assert info["next_reward"] == 10.0
    assert not _awarded(scenario_full, goal_id, zoe)
    assert balance(max_) == pytest.approx(30.0 + 7.0)

    # Re-evaluating does not pay level 1 again.
    await gm.evaluate_assignee(zoe)
    await hass.async_block_till_done()
    assert balance(max_) == pytest.approx(37.0)

    await _earn_points(scenario_full, zoe, 100.0)
    await gm.evaluate_assignee(zoe)
    await hass.async_block_till_done()
    assert gm.get_level_info(goal_id)["level"] == 2
    assert _awarded(scenario_full, goal_id, zoe)
    assert _awarded(scenario_full, goal_id, max_)
    # Max: 30 earned + 7 (level 1) + 10 (level 2, base reward).
    assert balance(max_) == pytest.approx(47.0)

    gm.reset_goal(goal_id)
    assert gm.get_level_info(goal_id)["level"] == 0
    assert not _awarded(scenario_full, goal_id, zoe)


async def test_editing_goal_keeps_family_runtime_state(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """Saving the goal's settings must not wipe baseline, streak or level."""
    zoe = scenario_full.assignee_ids["Zoë"]
    goal_id = _create_family_goal(
        scenario_full,
        goal_type=fg.GOAL_TYPE_POINTS,
        target=100.0,
        reward=5.0,
        assigned=[zoe],
    )
    existing = scenario_full.coordinator.challenges_data[goal_id]
    existing[fg.DATA_BASELINE] = {zoe: 12.0}
    existing[fg.DATA_LEVEL] = 1

    rebuilt = builders.build_goal({fg.DATA_LEVELS: "40:5, 90"}, existing=existing)
    assert rebuilt[fg.DATA_BASELINE] == {zoe: 12.0}
    assert rebuilt[fg.DATA_LEVEL] == 1
    assert rebuilt[fg.DATA_TARGET_VALUE] == 40.0


async def test_top_contributor_of_each_level_gets_the_multiplier(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """Whoever added most DURING a level gets that level's reward multiplied."""
    coordinator = scenario_full.coordinator
    gm = coordinator.family_goal_manager
    zoe = scenario_full.assignee_ids["Zoë"]
    max_ = scenario_full.assignee_ids["Max!"]
    goal_id = _create_family_goal(
        scenario_full,
        goal_type=fg.GOAL_TYPE_POINTS,
        target=1.0,
        reward=10.0,
        assigned=[zoe, max_],
    )
    goal = coordinator.challenges_data[goal_id]
    goal[fg.DATA_LEVELS] = "50:10, 500:10"
    goal[fg.DATA_TOP_MULTIPLIER] = 2.0

    awards: list[tuple[str, int | None, float | None]] = []
    original = gm._award

    def recording(a: str, g: str, goal_data: Any, **kw: Any) -> None:
        awards.append((a, kw.get("level"), kw.get("reward")))
        original(a, g, goal_data, **kw)

    gm._award = recording  # type: ignore[method-assign]

    # Level 1: Zoë leads, so she gets 10 x 2; Max gets the plain 10.
    await _earn_points(scenario_full, zoe, 60.0)
    await _earn_points(scenario_full, max_, 30.0)
    await gm.evaluate_assignee(zoe)
    await hass.async_block_till_done()
    assert (zoe, 1, 20.0) in awards
    assert (max_, 1, 10.0) in awards

    # Level 2 counts only what was added since level 1: Max leads this time.
    await _earn_points(scenario_full, zoe, 20.0)
    await _earn_points(scenario_full, max_, 450.0)
    await gm.evaluate_assignee(zoe)
    await hass.async_block_till_done()
    assert gm.get_level_info(goal_id)["level"] == 2
    assert (max_, 2, 20.0) in awards
    assert (zoe, 2, 10.0) in awards


async def test_no_multiplier_when_off_or_nobody_contributed(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """Multiplier 1 (off) pays everyone the plain reward."""
    coordinator = scenario_full.coordinator
    gm = coordinator.family_goal_manager
    zoe = scenario_full.assignee_ids["Zoë"]
    max_ = scenario_full.assignee_ids["Max!"]
    goal_id = _create_family_goal(
        scenario_full,
        goal_type=fg.GOAL_TYPE_POINTS,
        target=50.0,
        reward=10.0,
        assigned=[zoe, max_],
    )
    await _earn_points(scenario_full, zoe, 60.0)
    await gm.evaluate_assignee(zoe)
    await hass.async_block_till_done()
    assert float(coordinator.assignees_data[zoe][const.DATA_USER_POINTS]) == (
        pytest.approx(70.0)
    )
    assert _awarded(scenario_full, goal_id, max_)


async def test_everyone_contributes_counts_the_smallest_share(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """The goal only advances as fast as the person who has done the least."""
    gm = scenario_full.coordinator.family_goal_manager
    zoe = scenario_full.assignee_ids["Zoë"]
    max_ = scenario_full.assignee_ids["Max!"]
    goal_id = _create_family_goal(
        scenario_full,
        goal_type=fg.GOAL_TYPE_EVERYONE,
        target=5.0,
        reward=7.0,
        assigned=[zoe, max_],
    )

    _set_all_time_approved(scenario_full, zoe, 20)
    _set_all_time_approved(scenario_full, max_, 2)
    await gm.evaluate_assignee(zoe)
    assert gm.get_total(goal_id) == 2
    assert not _awarded(scenario_full, goal_id, zoe)

    _set_all_time_approved(scenario_full, max_, 5)
    await gm.evaluate_assignee(zoe)
    await hass.async_block_till_done()
    assert _awarded(scenario_full, goal_id, zoe)
    assert _awarded(scenario_full, goal_id, max_)


async def test_chores_in_one_day_uses_todays_total_and_keeps_levels(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """Today's family total decides the level; every new day starts over."""
    gm = scenario_full.coordinator.family_goal_manager
    zoe = scenario_full.assignee_ids["Zoë"]
    max_ = scenario_full.assignee_ids["Max!"]
    goal_id = _create_family_goal(
        scenario_full,
        goal_type=fg.GOAL_TYPE_DAY,
        target=6.0,
        reward=3.0,
        assigned=[zoe, max_],
    )
    today = {zoe: 2, max_: 3}
    gm._approved_today = lambda assignee_id: today[assignee_id]

    await gm.evaluate_assignee(zoe)
    assert gm.get_total(goal_id) == 5
    assert not _awarded(scenario_full, goal_id, zoe)

    today[max_] = 4
    await gm.evaluate_assignee(zoe)
    await hass.async_block_till_done()
    assert _awarded(scenario_full, goal_id, zoe)
    assert _awarded(scenario_full, goal_id, max_)

    # The best day is remembered.
    record = gm.get_day_record(goal_id)
    assert record["family_record"] == 6
    assert record["family_record_top"] == [
        scenario_full.coordinator.assignees_data[max_][const.DATA_USER_NAME]
    ]

    # A new day starts the goal over: level and awards clear, ready to earn again.
    goal = scenario_full.coordinator.challenges_data[goal_id]
    goal[fg.DATA_STREAK_LAST_DAY] = "2000-01-01"
    today.update({zoe: 0, max_: 0})
    await gm.evaluate_assignee(zoe)
    assert gm.get_total(goal_id) == 0
    assert goal[fg.DATA_LEVEL] == 0
    assert not _awarded(scenario_full, goal_id, zoe)
    assert not _awarded(scenario_full, goal_id, max_)

    # Earning it again on the new day pays out again.
    today.update({zoe: 3, max_: 3})
    await gm.evaluate_assignee(zoe)
    await hass.async_block_till_done()
    assert _awarded(scenario_full, goal_id, zoe)
    assert _awarded(scenario_full, goal_id, max_)

    # A tying day does not replace the record; it survives the daily restart.
    assert gm.get_day_record(goal_id)["family_record"] == 6


async def test_resetting_one_day_goal_does_not_pay_todays_levels_again(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """A mid-day reset counts from the reset on; tomorrow counts in full."""
    coordinator = scenario_full.coordinator
    gm = coordinator.family_goal_manager
    zoe = scenario_full.assignee_ids["Zoë"]
    max_ = scenario_full.assignee_ids["Max!"]
    goal_id = _create_family_goal(
        scenario_full,
        goal_type=fg.GOAL_TYPE_DAY,
        target=6.0,
        reward=5.0,
        assigned=[zoe, max_],
    )
    goal = coordinator.challenges_data[goal_id]
    goal[fg.DATA_LEVELS] = "2, 4, 6"
    today = {zoe: 3, max_: 3}
    gm._approved_today = lambda assignee_id: today[assignee_id]

    def balance(a: str) -> float:
        return float(coordinator.assignees_data[a][const.DATA_USER_POINTS])

    await gm.evaluate_assignee(zoe)
    await hass.async_block_till_done()
    assert goal[fg.DATA_LEVEL] == 3
    paid = balance(zoe)

    gm.reset_goal(goal_id)
    await gm.evaluate_assignee(zoe)
    await hass.async_block_till_done()
    assert gm.get_total(goal_id) == 0
    assert goal[fg.DATA_LEVEL] == 0
    assert balance(zoe) == pytest.approx(paid)

    today[max_] = 5
    await gm.evaluate_assignee(zoe)
    await hass.async_block_till_done()
    assert gm.get_level_contributions(goal_id) == {zoe: 0.0, max_: 2.0}
    assert goal[fg.DATA_LEVEL] == 1

    # The next day counts every chore again.
    goal[fg.DATA_STARTED] = "2000-01-01"
    goal[fg.DATA_STREAK_LAST_DAY] = "2000-01-01"
    today.update({zoe: 1, max_: 2})
    await gm.evaluate_assignee(zoe)
    await hass.async_block_till_done()
    assert gm.get_total(goal_id) == 3


async def test_points_past_a_level_carry_into_the_next_level(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """A big jump past a level shows up in the next level's shares."""
    gm = scenario_full.coordinator.family_goal_manager
    zoe = scenario_full.assignee_ids["Zoë"]
    max_ = scenario_full.assignee_ids["Max!"]
    goal_id = _create_family_goal(
        scenario_full,
        goal_type=fg.GOAL_TYPE_POINTS,
        target=1.0,
        reward=5.0,
        assigned=[zoe, max_],
    )
    scenario_full.coordinator.challenges_data[goal_id][fg.DATA_LEVELS] = (
        "100, 200, 1000, 5000"
    )

    # One chore past two levels at once: 581 - 200 carries into level 3.
    await _earn_points(scenario_full, zoe, 581.0)
    await gm.evaluate_assignee(zoe)
    await hass.async_block_till_done()
    assert gm.get_level_info(goal_id)["level"] == 2
    assert gm.get_level_contributions(goal_id) == {
        zoe: pytest.approx(381.0),
        max_: pytest.approx(0.0),
    }

    # Shared overshoot is split by what each person added to the level.
    await _earn_points(scenario_full, max_, 300.0)
    await gm.evaluate_assignee(max_)
    await hass.async_block_till_done()
    await _earn_points(scenario_full, zoe, 319.0)
    await gm.evaluate_assignee(zoe)
    await hass.async_block_till_done()
    assert gm.get_level_info(goal_id)["level"] == 3
    # Level 3 took 381 + 300 + 319 = 1000 of 1200 total: 200 carries over.
    shares = gm.get_level_contributions(goal_id)
    assert shares[zoe] == pytest.approx(700.0 * 200.0 / 1000.0)
    assert shares[max_] == pytest.approx(300.0 * 200.0 / 1000.0)
    assert sum(shares.values()) == pytest.approx(gm.get_total(goal_id) - 1000.0)


async def test_finished_goal_shows_whole_goal_shares(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """Once every level is done, each person's share is their whole-goal total."""
    gm = scenario_full.coordinator.family_goal_manager
    zoe = scenario_full.assignee_ids["Zoë"]
    max_ = scenario_full.assignee_ids["Max!"]
    goal_id = _create_family_goal(
        scenario_full,
        goal_type=fg.GOAL_TYPE_POINTS,
        target=100.0,
        reward=5.0,
        assigned=[zoe, max_],
    )

    await _earn_points(scenario_full, zoe, 70.0)
    await _earn_points(scenario_full, max_, 40.0)
    await gm.evaluate_assignee(max_)
    await hass.async_block_till_done()
    assert gm.get_level_info(goal_id)["level"] == 1

    # Not 0 for everyone: the goal is complete, so its full shares show.
    assert gm.get_level_contributions(goal_id) == {
        zoe: pytest.approx(70.0),
        max_: pytest.approx(40.0),
    }


async def test_overview_target_is_the_current_level(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """The Parents reset card shows the level being worked toward, not level 1."""
    gm = scenario_full.coordinator.family_goal_manager
    zoe = scenario_full.assignee_ids["Zoë"]
    goal_id = _create_family_goal(
        scenario_full,
        goal_type=fg.GOAL_TYPE_POINTS,
        target=100.0,
        reward=5.0,
        assigned=[zoe],
    )
    scenario_full.coordinator.challenges_data[goal_id][fg.DATA_LEVELS] = (
        "100, 1000, 5000"
    )
    await _earn_points(scenario_full, zoe, 581.0)
    await gm.evaluate_assignee(zoe)
    await hass.async_block_till_done()

    (entry,) = [g for g in gm.get_overview() if g["name"].endswith("100.0")]
    assert entry["total"] == pytest.approx(581.0)
    assert entry["target"] == pytest.approx(1000.0)


async def test_active_streak_needs_everyone_every_day(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """A day counts when everyone did a chore; a skipped day voids the streak."""
    gm = scenario_full.coordinator.family_goal_manager
    zoe = scenario_full.assignee_ids["Zoë"]
    max_ = scenario_full.assignee_ids["Max!"]
    goal_id = _create_family_goal(
        scenario_full,
        goal_type=fg.GOAL_TYPE_ACTIVE,
        target=2.0,
        reward=4.0,
        assigned=[zoe, max_],
    )
    goal = scenario_full.coordinator.challenges_data[goal_id]
    today = {zoe: 1, max_: 0}
    gm._approved_today = lambda assignee_id: today[assignee_id]

    # One person has not done a chore yet: no credit.
    await gm.evaluate_assignee(zoe)
    assert gm.get_total(goal_id) == 0

    # Everyone did one: day 1, and the same day is not counted twice.
    today[max_] = 2
    await gm.evaluate_assignee(zoe)
    await gm.evaluate_assignee(max_)
    assert gm.get_total(goal_id) == 1

    # Streak last advanced long ago: it is void, today starts a new streak.
    goal[fg.DATA_STREAK_LAST_DAY] = "2000-01-01"
    await gm.evaluate_assignee(zoe)
    assert gm.get_total(goal_id) == 1

    # Yesterday counted, today counts: target reached, everyone awarded.
    from datetime import date, timedelta

    from custom_components.choreops.utils.dt_utils import dt_today_iso

    goal[fg.DATA_STREAK_LAST_DAY] = (
        date.fromisoformat(dt_today_iso()) - timedelta(days=1)
    ).isoformat()
    await gm.evaluate_assignee(zoe)
    await hass.async_block_till_done()
    assert gm.get_total(goal_id) == 2
    assert _awarded(scenario_full, goal_id, zoe)
    assert _awarded(scenario_full, goal_id, max_)


async def test_assignee_caught_up_streak_counts_breaks_and_tracks_best(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """A person's own caught-up streak counts once a day and breaks on overdue."""
    gm = scenario_full.coordinator.family_goal_manager
    zoe = scenario_full.assignee_ids["Zoë"]
    info = scenario_full.coordinator.assignees_data[zoe]

    def snap(open_: int, done: int, *, overdue=False, missed=False) -> None:
        gm._assignee_caught_up_snapshot = lambda *a, **k: {
            "open": open_,
            "done": done,
            "overdue": overdue,
            "missed": missed,
        }

    snap(1, 2)
    assert not gm._update_assignee_caught_up_streak(zoe)

    snap(0, 3)
    assert gm._update_assignee_caught_up_streak(zoe)
    assert not gm._update_assignee_caught_up_streak(zoe)  # once per day
    assert info[const.DATA_USER_CAUGHT_UP_STREAK]["count"] == 1

    info[const.DATA_USER_CAUGHT_UP_STREAK]["last_day"] = "2000-01-01"
    assert gm._update_assignee_caught_up_streak(zoe)
    assert info[const.DATA_USER_CAUGHT_UP_STREAK]["count"] == 2
    assert info[const.DATA_USER_CAUGHT_UP_STREAK]["best"] == 2

    info[const.DATA_USER_CAUGHT_UP_STREAK]["last_day"] = "2000-01-01"
    snap(1, 0, overdue=True)
    assert gm._update_assignee_caught_up_streak(zoe)
    assert info[const.DATA_USER_CAUGHT_UP_STREAK]["count"] == 0
    assert info[const.DATA_USER_CAUGHT_UP_STREAK]["best"] == 2

    # Neutral day (nothing due, nothing done) changes nothing.
    snap(0, 0)
    assert not gm._update_assignee_caught_up_streak(zoe)


async def test_legacy_family_achievement_migrates_to_goal(
    scenario_full: SetupResult,
) -> None:
    """A family achievement from an earlier version becomes a goal with its state."""
    zoe = scenario_full.assignee_ids["Zoë"]
    max_ = scenario_full.assignee_ids["Max!"]
    coordinator = scenario_full.coordinator
    coordinator._data.setdefault(const.DATA_ACHIEVEMENTS, {})["old1"] = {
        const.DATA_ACHIEVEMENT_INTERNAL_ID: "old1",
        const.DATA_ACHIEVEMENT_NAME: "Pizza Night",
        const.DATA_ACHIEVEMENT_LABELS: ["fun"],
        const.DATA_ACHIEVEMENT_ASSIGNED_USER_IDS: [zoe, max_],
        const.DATA_ACHIEVEMENT_TYPE: fg.GOAL_TYPE_POINTS,
        const.DATA_ACHIEVEMENT_TARGET_VALUE: 50.0,
        const.DATA_ACHIEVEMENT_REWARD_POINTS: 5.0,
        fg.DATA_LEVELS: "50:5, 100:10",
        fg.DATA_LEVEL: 1,
        fg.DATA_BASELINE: {zoe: 3.0},
        fg.DATA_PROGRESS: {zoe: {fg.DATA_AWARDED: True}},
    }
    coordinator._data[const.DATA_ACHIEVEMENTS]["keep"] = {
        const.DATA_ACHIEVEMENT_NAME: "Personal",
        const.DATA_ACHIEVEMENT_TYPE: "chore_total",
    }

    assert await coordinator.family_goal_manager.migrate_legacy_achievements() == 1

    assert "old1" not in coordinator.achievements_data
    assert "keep" in coordinator.achievements_data
    goal_id = coordinator.family_goal_manager.get_goal_id_by_name("Pizza Night")
    goal = coordinator.challenges_data[goal_id]
    assert goal[fg.DATA_TYPE] == fg.GOAL_TYPE_POINTS
    assert goal[fg.DATA_LABELS] == ["fun"]
    assert goal[fg.DATA_LEVEL] == 1
    assert goal[fg.DATA_BASELINE] == {zoe: 3.0}
    assert goal[fg.DATA_PROGRESS][zoe][fg.DATA_AWARDED] is True
    assert set(goal[fg.DATA_ASSIGNED_USER_IDS]) == {zoe, max_}
    # Running it again does nothing
    assert await coordinator.family_goal_manager.migrate_legacy_achievements() == 0


async def test_goals_survive_a_restart(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """Goals live in the challenges bucket; startup cleanup must not wipe them."""
    zoe = scenario_full.assignee_ids["Zoë"]
    entry = scenario_full.config_entry
    goal_id = _create_family_goal(
        scenario_full,
        goal_type=fg.GOAL_TYPE_POINTS,
        target=100.0,
        reward=5.0,
        assigned=[zoe],
    )
    scenario_full.coordinator._persist(immediate=True)

    for _ in range(2):
        await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        assert goal_id in entry.runtime_data.challenges_data

    sensors = [
        state
        for state in hass.states.async_all("sensor")
        if "family_contributions" in state.attributes
    ]
    assert sensors


async def test_points_goal_does_not_count_award_points(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """Goal payouts, achievement points and badge points don't feed a points goal.

    Otherwise a level's own payout would carry the goal toward the next level.
    """
    coordinator = scenario_full.coordinator
    gm = coordinator.family_goal_manager
    zoe = scenario_full.assignee_ids["Zoë"]
    max_ = scenario_full.assignee_ids["Max!"]
    goal_id = gm.create_goal(
        {
            fg.DATA_NAME: "Levelled points goal",
            fg.DATA_ASSIGNED_USER_IDS: [zoe, max_],
            fg.DATA_TYPE: fg.GOAL_TYPE_POINTS,
            fg.DATA_TARGET_VALUE: 300.0,
            fg.DATA_REWARD_POINTS: 50.0,
            fg.DATA_LEVELS: "100:50, 300:50",
        }
    )

    await _earn_points(scenario_full, zoe, 60.0)
    await _earn_points(scenario_full, max_, 40.0)
    await gm.evaluate_assignee(zoe)
    await hass.async_block_till_done()

    # Level 1 paid 50 to each person; the goal still only holds the 100 earned.
    assert gm.get_level_info(goal_id)["level"] == 1
    assert gm.get_total(goal_id) == pytest.approx(100.0)

    for source in (const.POINTS_SOURCE_ACHIEVEMENTS, const.POINTS_SOURCE_BADGES):
        await coordinator.economy_manager.deposit(
            assignee_id=zoe, amount=500.0, source=source
        )
    await gm.evaluate_assignee(zoe)
    await hass.async_block_till_done()

    assert gm.get_total(goal_id) == pytest.approx(100.0)
    assert gm.get_level_info(goal_id)["level"] == 1

    # Bonuses still count
    await coordinator.economy_manager.deposit(
        assignee_id=max_, amount=25.0, source=const.POINTS_SOURCE_BONUSES
    )
    assert gm.get_total(goal_id) == pytest.approx(125.0)


async def test_payout_names_come_from_translations(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """Level and top-contributor payout names use the translation file wording.

    A language without the goal wording falls back to English.
    """
    coordinator = scenario_full.coordinator
    gm = coordinator.family_goal_manager
    zoe = scenario_full.assignee_ids["Zoë"]
    max_ = scenario_full.assignee_ids["Max!"]
    max_info: Any = coordinator.assignees_data[max_]
    max_info[const.DATA_USER_DASHBOARD_LANGUAGE] = "xx"
    gm.create_goal(
        {
            fg.DATA_NAME: "Pizza Night",
            fg.DATA_ASSIGNED_USER_IDS: [zoe, max_],
            fg.DATA_TYPE: fg.GOAL_TYPE_POINTS,
            fg.DATA_TARGET_VALUE: 300.0,
            fg.DATA_REWARD_POINTS: 10.0,
            fg.DATA_LEVELS: "100:10, 300:20",
            fg.DATA_TOP_MULTIPLIER: 2.0,
        }
    )

    await _earn_points(scenario_full, zoe, 70.0)
    await _earn_points(scenario_full, max_, 30.0)
    await gm.evaluate_assignee(zoe)
    await hass.async_block_till_done()

    def last_goal_entry(assignee_id: str) -> dict[str, Any]:
        ledger: list[dict[str, Any]] = coordinator.assignees_data[assignee_id][
            const.DATA_USER_LEDGER
        ]
        return next(
            entry
            for entry in reversed(ledger)
            if entry[const.DATA_LEDGER_SOURCE] == const.POINTS_SOURCE_CHALLENGES
        )

    zoe_entry = last_goal_entry(zoe)
    assert zoe_entry[const.DATA_LEDGER_ITEM_NAME] == (
        "Pizza Night - Level 1 (Top contributor x2)"
    )
    assert zoe_entry[const.DATA_LEDGER_AMOUNT] == pytest.approx(20.0)
    assert last_goal_entry(max_)[const.DATA_LEDGER_ITEM_NAME] == "Pizza Night - Level 1"


def test_broken_goal_wording_falls_back_to_the_name() -> None:
    """A translation with a bad placeholder never blocks a payout."""
    from custom_components.choreops.family_goals.manager import _fill

    words = {fg.GOAL_WORD_LEVEL: "{name} - Stufe {stufe}"}
    assert _fill(words, fg.GOAL_WORD_LEVEL, name="Pizza", level=1) == "Pizza"
    assert _fill({}, fg.GOAL_WORD_LEVEL, name="Pizza", level=1) == "Pizza"


async def test_old_points_goal_snapshots_are_converted(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """Points goals saved before award points were left out keep working.

    Their level-start snapshot still included award points, so every share
    read 0 until a person out-earned all their past awards.
    """
    coordinator = scenario_full.coordinator
    gm = coordinator.family_goal_manager
    zoe = scenario_full.assignee_ids["Zoë"]
    max_ = scenario_full.assignee_ids["Max!"]
    goal_id = gm.create_goal(
        {
            fg.DATA_NAME: "Old points goal",
            fg.DATA_ASSIGNED_USER_IDS: [zoe, max_],
            fg.DATA_TYPE: fg.GOAL_TYPE_POINTS,
            fg.DATA_TARGET_VALUE: 300.0,
            fg.DATA_REWARD_POINTS: 50.0,
            fg.DATA_LEVELS: "100:50, 300:50",
        }
    )
    # Zoë already held 500 badge points before the goal's level began
    await coordinator.economy_manager.deposit(
        assignee_id=zoe, amount=500.0, source=const.POINTS_SOURCE_BADGES
    )
    await _earn_points(scenario_full, zoe, 60.0)
    await _earn_points(scenario_full, max_, 40.0)
    await gm.evaluate_assignee(zoe)
    await hass.async_block_till_done()
    assert gm.get_level_info(goal_id)["level"] == 1

    # What an older version saved: snapshots counting award points
    goal = coordinator.challenges_data[goal_id]
    goal[fg.DATA_LEVEL_START] = {zoe: 560.0, max_: 40.0}
    del goal[fg.DATA_POINTS_BASIS]

    await _earn_points(scenario_full, zoe, 30.0)
    assert gm.get_level_contributions(goal_id) == {zoe: 0.0, max_: 0.0}  # the bug

    assert gm.migrate_points_basis() == 1
    # Zoë's 30 since the level began counts; Max earned nothing since
    assert gm.get_level_contributions(goal_id) == {
        zoe: pytest.approx(30.0),
        max_: pytest.approx(0.0),
    }
    assert gm.get_total(goal_id) == pytest.approx(130.0)
    # Runs once
    assert gm.migrate_points_basis() == 0


# ---------------------------------------------------------------------------
# Goal settings: repeat, chore labels, finish date and pace, notifications
# ---------------------------------------------------------------------------

_TODAY = "custom_components.choreops.family_goals.manager.dt_today_iso"


async def test_weekly_goal_starts_over_each_monday(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """A repeating goal restarts at the new period like a reset; points are kept."""
    from unittest.mock import patch

    coordinator = scenario_full.coordinator
    gm = coordinator.family_goal_manager
    zoe = scenario_full.assignee_ids["Zoë"]
    goal_id = _create_family_goal(
        scenario_full,
        goal_type=fg.GOAL_TYPE_POINTS,
        target=100.0,
        reward=10.0,
        assigned=[zoe],
    )
    gm.update_goal(goal_id, {fg.DATA_REPEAT: fg.REPEAT_WEEKLY})
    goal = coordinator.challenges_data[goal_id]

    with patch(_TODAY, return_value="2026-10-21"):  # Wednesday
        await _earn_points(scenario_full, zoe, 100.0)
        await gm.evaluate_assignee(zoe)
        await hass.async_block_till_done()
        assert goal[fg.DATA_PERIOD_START] == "2026-10-19"
        assert _awarded(scenario_full, goal_id, zoe)
        schedule = gm.get_schedule(goal_id)
        assert schedule[fg.ATTR_END_DATE] == "2026-10-25"
        assert schedule[fg.ATTR_DAYS_LEFT] == 5
        assert schedule[fg.ATTR_DEADLINE] == fg.DEADLINE_WEEK
    balance = coordinator.assignees_data[zoe][const.DATA_USER_POINTS]

    with patch(_TODAY, return_value="2026-10-25"):  # Sunday, same week
        await gm.evaluate_assignee(zoe)
        assert gm.get_total(goal_id) == pytest.approx(100.0)

    with patch(_TODAY, return_value="2026-10-26"):  # Monday: a new week
        await gm.evaluate_assignee(zoe)
        await hass.async_block_till_done()
        assert goal[fg.DATA_PERIOD_START] == "2026-10-26"
        assert gm.get_total(goal_id) == 0
        assert not _awarded(scenario_full, goal_id, zoe)
        assert coordinator.assignees_data[zoe][const.DATA_USER_POINTS] == balance

    # Streak goals ignore the setting
    streak = {fg.DATA_TYPE: fg.GOAL_TYPE_ACTIVE, fg.DATA_REPEAT: fg.REPEAT_WEEKLY}
    assert gm._period_start(streak, date(2026, 10, 21)) is None
    monthly = {fg.DATA_TYPE: fg.GOAL_TYPE_CHORES, fg.DATA_REPEAT: fg.REPEAT_MONTHLY}
    start = gm._period_start(monthly, date(2026, 2, 14))
    assert start == date(2026, 2, 1)
    assert gm._period_end(monthly, start) == date(2026, 2, 28)


async def test_chores_goal_counts_chores_with_chosen_labels(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """Total Chores Completed counts the chosen chore plus every labelled chore."""
    coordinator = scenario_full.coordinator
    gm = coordinator.family_goal_manager
    chore_ids = list(coordinator.chores_data)
    labelled, other, selected = chore_ids[0], chore_ids[1], chore_ids[2]
    coordinator.chores_data[labelled][const.DATA_CHORE_LABELS] = ["kitchen"]
    coordinator.chores_data[other][const.DATA_CHORE_LABELS] = ["garden"]

    goal = {
        fg.DATA_TYPE: fg.GOAL_TYPE_CHORES,
        fg.DATA_SELECTED_CHORE_ID: selected,
        fg.DATA_CHORE_LABELS: ["kitchen"],
    }
    counted = gm._counted_chore_ids(goal)
    assert counted is not None
    assert selected in counted
    assert labelled in counted
    assert other not in counted
    assert gm._counted_chore_ids({fg.DATA_TYPE: fg.GOAL_TYPE_CHORES}) is None
    assert gm._counted_chore_ids({**goal, fg.DATA_TYPE: fg.GOAL_TYPE_POINTS}) is None
    goal[fg.DATA_CHORE_LABELS] = ["nothing-has-this"]
    goal[fg.DATA_SELECTED_CHORE_ID] = const.SENTINEL_EMPTY
    assert gm._counted_chore_ids(goal) == []


async def test_finish_date_freezes_progress_until_reset(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """After the finish date shares stop moving and nothing pays; a reset reopens."""
    from unittest.mock import patch

    gm = scenario_full.coordinator.family_goal_manager
    zoe = scenario_full.assignee_ids["Zoë"]
    goal_id = _create_family_goal(
        scenario_full,
        goal_type=fg.GOAL_TYPE_POINTS,
        target=50.0,
        reward=10.0,
        assigned=[zoe],
    )
    gm.update_goal(goal_id, {fg.DATA_END_DATE: "2026-10-20"})

    with patch(_TODAY, return_value="2026-10-20"):
        await _earn_points(scenario_full, zoe, 30.0)
        await gm.evaluate_assignee(zoe)
        assert gm.get_schedule(goal_id)[fg.ATTR_DAYS_LEFT] == 1
        assert not gm.get_schedule(goal_id)[fg.ATTR_FINISHED]

    with patch(_TODAY, return_value="2026-10-21"):
        await gm.evaluate_assignee(zoe)
        await _earn_points(scenario_full, zoe, 40.0)
        await gm.evaluate_assignee(zoe)
        await hass.async_block_till_done()
        assert gm.get_total(goal_id) == pytest.approx(30.0)
        assert not _awarded(scenario_full, goal_id, zoe)
        schedule = gm.get_schedule(goal_id)
        assert schedule[fg.ATTR_FINISHED]
        assert schedule[fg.ATTR_DAYS_LEFT] == 0

        gm.reset_goal(goal_id)
        assert not gm.get_schedule(goal_id)[fg.ATTR_FINISHED]
        assert gm.get_schedule(goal_id)[fg.ATTR_END_DATE] == ""
        await _earn_points(scenario_full, zoe, 50.0)
        await gm.evaluate_assignee(zoe)
        await hass.async_block_till_done()
        assert _awarded(scenario_full, goal_id, zoe)


async def test_pace_compares_total_with_an_even_pace(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """Behind, on track or ahead against an even pace to the finish date."""
    from unittest.mock import patch

    coordinator = scenario_full.coordinator
    gm = coordinator.family_goal_manager
    zoe = scenario_full.assignee_ids["Zoë"]
    goal_id = _create_family_goal(
        scenario_full,
        goal_type=fg.GOAL_TYPE_POINTS,
        target=100.0,
        reward=10.0,
        assigned=[zoe],
    )
    gm.update_goal(goal_id, {fg.DATA_END_DATE: "2026-10-10"})
    coordinator.challenges_data[goal_id][fg.DATA_STARTED] = "2026-10-01"

    with patch(_TODAY, return_value="2026-10-05"):
        # Day 5 of 10: an even pace has 45 by midday
        for total, pace in ((30.0, fg.PACE_BEHIND), (45.0, fg.PACE_ON_TRACK)):
            with patch.object(gm, "get_total", return_value=total):
                schedule = gm.get_schedule(goal_id)
            assert schedule[fg.ATTR_PACE] == pace
        with patch.object(gm, "get_total", return_value=60.0):
            assert gm.get_schedule(goal_id)[fg.ATTR_PACE] == fg.PACE_AHEAD
            assert gm.get_schedule(goal_id)[fg.ATTR_PACE_EXPECTED] == 45.0
        schedule = gm.get_schedule(goal_id)
        assert schedule[fg.ATTR_DAYS_LEFT] == 6
        assert schedule[fg.ATTR_DEADLINE] == fg.DEADLINE_FINISH

    # No deadline, no pace
    gm.update_goal(goal_id, {fg.DATA_END_DATE: ""})
    assert gm.get_schedule(goal_id)[fg.ATTR_PACE] == ""
    assert gm.get_schedule(goal_id)[fg.ATTR_DAYS_LEFT] is None


@pytest.mark.parametrize(
    ("notify", "to_person", "to_parents"),
    [
        (fg.NOTIFY_EVERYONE, True, True),
        (fg.NOTIFY_ASSIGNEES, True, False),
        (fg.NOTIFY_APPROVERS, False, True),
        (fg.NOTIFY_OFF, False, False),
    ],
)
async def test_level_up_notifications_follow_the_setting(
    hass: HomeAssistant,
    scenario_full: SetupResult,
    notify: str,
    to_person: bool,
    to_parents: bool,
) -> None:
    """The goal's setting picks who is told; the points are paid either way."""
    from unittest.mock import AsyncMock, patch

    coordinator = scenario_full.coordinator
    gm = coordinator.family_goal_manager
    zoe = scenario_full.assignee_ids["Zoë"]
    goal_id = _create_family_goal(
        scenario_full,
        goal_type=fg.GOAL_TYPE_POINTS,
        target=10.0,
        reward=5.0,
        assigned=[zoe],
    )
    gm.update_goal(goal_id, {fg.DATA_NOTIFY: notify})
    await _earn_points(scenario_full, zoe, 10.0)
    before = coordinator.assignees_data[zoe][const.DATA_USER_POINTS]

    nm = coordinator.notification_manager
    person, parents = AsyncMock(), AsyncMock()
    with (
        patch.object(nm, "notify_assignee_translated", person),
        patch.object(nm, "notify_approvers_translated", parents),
    ):
        await gm.evaluate_assignee(zoe)
        await hass.async_block_till_done()

    assert coordinator.assignees_data[zoe][const.DATA_USER_POINTS] == before + 5.0
    assert person.await_count == (1 if to_person else 0)
    assert parents.await_count == (1 if to_parents else 0)


def test_goal_settings_are_built_and_validated() -> None:
    """New settings get safe defaults; a bad finish date is reported."""
    goal = builders.build_goal(
        {
            fg.DATA_NAME: "Goal",
            fg.DATA_REPEAT: "fortnightly",
            fg.DATA_END_DATE: "2026-12-24",
        }
    )
    assert goal[fg.DATA_REPEAT] == fg.REPEAT_NEVER
    assert goal[fg.DATA_NOTIFY] == fg.NOTIFY_EVERYONE
    assert goal[fg.DATA_END_DATE] == "2026-12-24"
    assert goal[fg.DATA_CHORE_LABELS] == []
    # A cleared date on edit removes it
    edited = builders.build_goal({fg.DATA_END_DATE: ""}, existing=goal)
    assert edited[fg.DATA_END_DATE] == ""

    data = {
        fg.DATA_NAME: "Goal",
        fg.DATA_ASSIGNED_USER_IDS: ["a"],
        fg.DATA_TYPE: fg.GOAL_TYPE_POINTS,
        fg.DATA_END_DATE: "next week",
    }
    assert builders.validate_goal(data) == {
        fg.DATA_END_DATE: builders.ERR_INVALID_END_DATE
    }


async def test_chore_changes_during_an_evaluation_are_not_read_stale(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """A claim made while a goal evaluation waits sees the claimed state.

    Wording loads from disk the first time, which lets other work run in the
    middle of an evaluation. Cached chore statuses must not leak into it.
    """
    from unittest.mock import AsyncMock, patch

    from tests.helpers.workflows import find_chore, get_dashboard_helper

    coordinator = scenario_full.coordinator
    gm = coordinator.family_goal_manager
    chore_manager = coordinator.chore_manager
    zoe = scenario_full.assignee_ids["Zoë"]
    chore_id = scenario_full.chore_ids["Feed the cåts"]
    _create_family_goal(
        scenario_full,
        goal_type=fg.GOAL_TYPE_CAUGHT_UP,
        target=3.0,
        reward=0.0,
        assigned=[zoe],
    )
    before = chore_manager.get_chore_status_context(zoe, chore_id)
    assert before[const.CHORE_CTX_STATE] == const.CHORE_STATE_PENDING

    chore = find_chore(get_dashboard_helper(hass, "zoe"), "Feed the cåts")
    assert chore is not None
    real_words = gm._goal_words
    seen: list[str] = []

    async def words_with_a_claim_in_between(language: str | None) -> dict[str, str]:
        if not seen:
            with patch.object(
                coordinator.notification_manager, "notify_approvers", new=AsyncMock()
            ):
                await chore_manager.claim_chore(zoe, chore_id, "Zoë")
            context = chore_manager.get_chore_status_context(zoe, chore_id)
            seen.append(context[const.CHORE_CTX_STATE])
            # The chore sensor, rewritten by the claim, shows it too
            state = hass.states.get(chore["eid"])
            seen.append(state.state if state else "missing")
        return await real_words(language)

    with patch.object(gm, "_goal_words", side_effect=words_with_a_claim_in_between):
        gm._pending.add(zoe)
        await gm.drain_pending()

    assert seen == [const.CHORE_STATE_CLAIMED, const.CHORE_STATE_CLAIMED]


async def test_shares_count_again_after_points_and_chore_history_reset(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """A data reset lowers everyone's counts; goal snapshots follow them down.

    Otherwise each person's share in the current level reads 0 until they
    out-earn what they had before the reset.
    """
    coordinator = scenario_full.coordinator
    gm = coordinator.family_goal_manager
    zoe = scenario_full.assignee_ids["Zoë"]
    max_ = scenario_full.assignee_ids["Max!"]
    points_goal = gm.create_goal(
        {
            fg.DATA_NAME: "Points before reset",
            fg.DATA_ASSIGNED_USER_IDS: [zoe, max_],
            fg.DATA_TYPE: fg.GOAL_TYPE_POINTS,
            fg.DATA_TARGET_VALUE: 5000.0,
            fg.DATA_REWARD_POINTS: 5.0,
            fg.DATA_LEVELS: "100:5, 5000:5",
        }
    )
    chores_goal = _create_family_goal(
        scenario_full,
        goal_type=fg.GOAL_TYPE_CHORES,
        target=500.0,
        reward=5.0,
        assigned=[zoe, max_],
    )
    coordinator.challenges_data[chores_goal][fg.DATA_LEVELS] = "10:5, 500:5"

    await _earn_points(scenario_full, zoe, 300.0)
    await _earn_points(scenario_full, max_, 200.0)
    _set_all_time_approved(scenario_full, zoe, 40)
    _set_all_time_approved(scenario_full, max_, 30)
    await gm.evaluate_assignee(zoe)
    await hass.async_block_till_done()
    assert gm.get_level_info(points_goal)["level"] == 1
    assert gm.get_level_info(chores_goal)["level"] == 1

    await coordinator.system_manager._call_data_reset_managers(
        "global", None, None, None
    )
    # Earned straight after the reset, before the debounced re-check runs
    await _earn_points(scenario_full, zoe, 50.0)
    _set_all_time_approved(scenario_full, max_, 2)
    await gm.evaluate_assignee(zoe)
    await hass.async_block_till_done()

    assert gm.get_level_contributions(points_goal) == {
        zoe: pytest.approx(50.0),
        max_: pytest.approx(0.0),
    }
    assert gm.get_level_contributions(chores_goal) == {
        zoe: pytest.approx(0.0),
        max_: pytest.approx(2.0),
    }
    # Levels already reached and paid stay reached
    assert gm.get_level_info(points_goal)["level"] == 1


async def test_snapshot_above_current_count_is_lowered(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """Goals saved with snapshots above today's counts heal on the next check."""
    gm = scenario_full.coordinator.family_goal_manager
    zoe = scenario_full.assignee_ids["Zoë"]
    max_ = scenario_full.assignee_ids["Max!"]
    goal_id = _create_family_goal(
        scenario_full,
        goal_type=fg.GOAL_TYPE_CHORES,
        target=250.0,
        reward=5.0,
        assigned=[zoe, max_],
    )
    goal = scenario_full.coordinator.challenges_data[goal_id]
    goal[fg.DATA_LEVELS] = "10:5, 250:5"
    goal[fg.DATA_LEVEL] = 1
    goal[fg.DATA_LEVEL_START] = {zoe: 64.0, max_: 7.0}
    goal[fg.DATA_BASELINE] = {zoe: 90.0}
    _set_all_time_approved(scenario_full, zoe, 2)
    _set_all_time_approved(scenario_full, max_, 1)

    await gm.evaluate_assignee(zoe)
    await hass.async_block_till_done()
    assert goal[fg.DATA_BASELINE] == {zoe: 2.0}
    assert goal[fg.DATA_LEVEL_START] == {zoe: 0.0, max_: 1.0}

    _set_all_time_approved(scenario_full, zoe, 5)
    _set_all_time_approved(scenario_full, max_, 3)
    assert gm.get_level_contributions(goal_id) == {
        zoe: pytest.approx(3.0),
        max_: pytest.approx(2.0),
    }


async def test_many_level_ups_at_once_refresh_entities_once(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """Crossing many levels pays everyone with one entity refresh, not one each."""
    from unittest.mock import patch

    from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

    coordinator = scenario_full.coordinator
    gm = coordinator.family_goal_manager
    ids = list(scenario_full.assignee_ids.values())
    goal_id = _create_family_goal(
        scenario_full,
        goal_type=fg.GOAL_TYPE_DAY,
        target=1.0,
        reward=5.0,
        assigned=ids,
    )
    coordinator.challenges_data[goal_id][fg.DATA_LEVELS] = ", ".join(
        f"{level}:{5 * level}" for level in range(1, 21)
    )
    today = dict.fromkeys(ids, 0)
    gm._approved_today = lambda assignee_id: today[assignee_id]
    await gm.evaluate_assignee(ids[0])
    await hass.async_block_till_done()

    today[ids[0]] = 6
    with patch.object(
        DataUpdateCoordinator,
        "async_update_listeners",
        autospec=True,
        side_effect=DataUpdateCoordinator.async_update_listeners,
    ) as refresh:
        gm._pending.update(ids)
        await gm.drain_pending()
        await hass.async_block_till_done()
    assert refresh.call_count == 1
    assert coordinator.challenges_data[goal_id][fg.DATA_LEVEL] == 6
    ledger = coordinator.assignees_data[ids[1]][const.DATA_USER_LEDGER]
    assert sum(1 for e in ledger if e.get("reference_id") == goal_id) == 6
