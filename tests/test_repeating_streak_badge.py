"""Streak badges with no reset schedule repeat: earn it, streak restarts."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from custom_components.choreops import const
from custom_components.choreops.managers.gamification_manager import GamificationManager
from custom_components.choreops.utils.dt_utils import dt_today_iso

BADGE_ID = "badge-1"
ASSIGNEE_ID = "kid-1"


def _manager(target_type: str, frequency: str) -> tuple[GamificationManager, Any]:
    coordinator = MagicMock()
    progress: dict[str, Any] = {
        const.DATA_USER_BADGE_PROGRESS_DAYS_CYCLE_COUNT: 7,
        const.DATA_USER_BADGE_PROGRESS_OVERALL_PROGRESS: 1.0,
        const.DATA_USER_BADGE_PROGRESS_CRITERIA_MET: True,
        const.DATA_USER_BADGE_PROGRESS_LAST_UPDATE_DAY: "2000-01-01",
    }
    coordinator.assignees_data = {
        ASSIGNEE_ID: {const.DATA_USER_BADGE_PROGRESS: {BADGE_ID: progress}}
    }
    coordinator.badges_data = {
        BADGE_ID: {
            const.DATA_BADGE_TARGET: {const.DATA_BADGE_TARGET_TYPE: target_type},
            const.DATA_BADGE_RESET_SCHEDULE: {
                const.DATA_BADGE_RESET_SCHEDULE_RECURRING_FREQUENCY: frequency
            },
        }
    }
    coordinator._persist_and_update = MagicMock()
    return GamificationManager(MagicMock(), coordinator), progress


def test_streak_with_no_reset_is_repeating_and_restarts() -> None:
    """Streak + no reset repeats; restart zeroes the count and marks today counted."""
    manager, progress = _manager(
        const.BADGE_TARGET_THRESHOLD_TYPE_STREAK_SELECTED_CHORES, const.FREQUENCY_NONE
    )
    badge = manager.coordinator.badges_data[BADGE_ID]
    assert manager._is_repeating_streak_badge(badge)

    manager._restart_streak_after_award(ASSIGNEE_ID, BADGE_ID)

    assert progress[const.DATA_USER_BADGE_PROGRESS_DAYS_CYCLE_COUNT] == 0
    assert progress[const.DATA_USER_BADGE_PROGRESS_CRITERIA_MET] is False
    assert progress[const.DATA_USER_BADGE_PROGRESS_LAST_UPDATE_DAY] == dt_today_iso()


def test_recurring_or_non_streak_badges_do_not_repeat() -> None:
    """Weekly streaks and day-count badges keep their existing behavior."""
    weekly, _ = _manager(
        const.BADGE_TARGET_THRESHOLD_TYPE_STREAK_SELECTED_CHORES,
        const.FREQUENCY_WEEKLY,
    )
    assert not weekly._is_repeating_streak_badge(
        weekly.coordinator.badges_data[BADGE_ID]
    )

    days, _ = _manager(
        const.BADGE_TARGET_THRESHOLD_TYPE_DAYS_MIN_3_CHORES, const.FREQUENCY_NONE
    )
    assert not days._is_repeating_streak_badge(days.coordinator.badges_data[BADGE_ID])
