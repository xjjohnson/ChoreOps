"""A repeating streak badge shows as achieved all day and restarts at midnight."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from custom_components.choreops import const
from tests.test_badge_streak_midnight_reset import (
    ASSIGNEE_NAME,
    STREAK_THRESHOLD,
    PeriodicDayReplay,
    _add_periodic_badge,
    day_key,
    streak_scenario,  # noqa: F401  (pytest fixture)
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    import pytest

    from tests.helpers.setup import SetupResult


def _count_awards(monkeypatch: pytest.MonkeyPatch, setup: SetupResult) -> list[str]:
    """Record every award the gamification manager applies, first or repeat."""
    manager = setup.coordinator.gamification_manager
    awards: list[str] = []

    for name in ("_apply_periodic_first_award", "_apply_periodic_reaward"):
        original = getattr(manager, name)

        async def spy(
            *args: Any, _name: str = name, _original: Any = original, **kwargs: Any
        ) -> Any:
            awards.append(_name)
            return await _original(*args, **kwargs)

        monkeypatch.setattr(manager, name, spy)
    return awards


async def test_earned_streak_holds_until_the_next_day(
    hass: HomeAssistant,
    streak_scenario: SetupResult,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reaching the target keeps the achieved state today and zeroes it tomorrow."""
    badge_id = await _add_periodic_badge(hass, streak_scenario)
    awards = _count_awards(monkeypatch, streak_scenario)
    replay = PeriodicDayReplay(streak_scenario, badge_id)

    for offset in (-3, -2, -1):
        await replay.start_day(day_key(offset))
        await replay.complete_day(day_key(offset))

    # Tracking began the first day the badge was evaluated.
    assert replay._progress()[const.DATA_USER_BADGE_PROGRESS_TRACKED_SINCE] == day_key(
        -3
    )

    # Earned on the last day: the progress still shows the reached target.
    assert replay.earned is True
    assert len(awards) == 1
    assert replay.days_cycle_count == STREAK_THRESHOLD
    assert replay.criteria_met is True

    # More activity the same day neither restarts the streak nor re-awards it.
    await replay.complete_day(day_key(-1))
    assert replay.days_cycle_count == STREAK_THRESHOLD
    assert replay.criteria_met is True
    assert len(awards) == 1

    # The first evaluation of the next day (the midnight rollover) restarts it.
    await replay.start_day(day_key(0))
    assert replay.days_cycle_count == 0
    assert replay.criteria_met is False
    assert len(awards) == 1
    # The restarted streak is tracked from the new day.
    assert replay._progress()[const.DATA_USER_BADGE_PROGRESS_TRACKED_SINCE] == day_key(
        0
    )

    # Completing the new day is day one of the next streak.
    await replay.complete_day(day_key(0))
    assert replay.days_cycle_count == 1


async def test_minimum_chores_badge_reports_todays_count(
    hass: HomeAssistant,
    streak_scenario: SetupResult,  # noqa: F811
) -> None:
    """A "N chores a day" badge exposes today's approved count; others do not."""
    gamification = streak_scenario.coordinator.gamification_manager
    assignee_id = streak_scenario.assignee_ids[ASSIGNEE_NAME]

    assert gamification.get_badge_today_chore_count(assignee_id, "no-such") is None

    badge_id = await _add_periodic_badge(
        hass,
        streak_scenario,
        target_type=const.BADGE_TARGET_THRESHOLD_TYPE_DAYS_MIN_7_CHORES,
        threshold=1,
    )
    assert gamification.get_badge_today_chore_count(assignee_id, badge_id) == (0, 7)

    replay = PeriodicDayReplay(streak_scenario, badge_id)
    await replay.start_day(day_key(0))
    await replay.complete_day(day_key(0))
    done, required = gamification.get_badge_today_chore_count(assignee_id, badge_id)
    assert required == 7
    assert done >= 1
