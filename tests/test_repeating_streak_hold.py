"""A repeating streak badge shows as achieved all day and restarts at midnight."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from tests.test_badge_streak_midnight_reset import (
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

    # Completing the new day is day one of the next streak.
    await replay.complete_day(day_key(0))
    assert replay.days_cycle_count == 1
