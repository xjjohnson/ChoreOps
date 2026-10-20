"""Tests for family goals (one pooled total, everyone awarded together)."""

from __future__ import annotations

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
    assert all("still to do today" in text for text in status.values())
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

    assert coordinator.family_goal_manager.migrate_legacy_achievements() == 1

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
    assert coordinator.family_goal_manager.migrate_legacy_achievements() == 0
