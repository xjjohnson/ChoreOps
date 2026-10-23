"""Constants for Family Goals.

A family goal is a group goal: every assigned person's contribution is pooled
into one total, and everyone assigned is awarded together. Goals live in the
``challenges`` storage bucket and are paid through the challenge-completed
signal, so no other manager needs to know about them.

String values deliberately match the names the dashboards already read
(``family_total``, ``family_contributions`` and so on).
"""

from __future__ import annotations

from typing import Final

from .. import const as base

# ---------------------------------------------------------------------------
# Goal types
# ---------------------------------------------------------------------------
GOAL_TYPE_POINTS: Final = "family_points_total"
GOAL_TYPE_CHORES: Final = "family_chore_total"
# Everyone caught up for X days in a row (the target is a number of days).
GOAL_TYPE_CAUGHT_UP: Final = "family_caught_up_days"
# Everyone completes at least X chores (the smallest share counts).
GOAL_TYPE_EVERYONE: Final = "family_everyone_contributes"
# Chores the whole family completes in a single day (resets each day).
GOAL_TYPE_DAY: Final = "family_chores_in_day"
# Everyone completes at least one chore, X days in a row.
GOAL_TYPE_ACTIVE: Final = "family_active_days"

GOAL_TYPES: Final = frozenset(
    {
        GOAL_TYPE_POINTS,
        GOAL_TYPE_CHORES,
        GOAL_TYPE_CAUGHT_UP,
        GOAL_TYPE_EVERYONE,
        GOAL_TYPE_DAY,
        GOAL_TYPE_ACTIVE,
    }
)
# Goals whose total is a shared day streak rather than a sum of shares.
STREAK_GOAL_TYPES: Final = frozenset({GOAL_TYPE_CAUGHT_UP, GOAL_TYPE_ACTIVE})

GOAL_TYPE_OPTIONS: Final = [
    {"value": GOAL_TYPE_POINTS, "label": "Total Points Earned"},
    {"value": GOAL_TYPE_CHORES, "label": "Total Chores Completed"},
    {"value": GOAL_TYPE_CAUGHT_UP, "label": "Everyone Caught Up for X Days"},
    {"value": GOAL_TYPE_EVERYONE, "label": "Everyone Completes at Least X Chores"},
    {"value": GOAL_TYPE_DAY, "label": "X Chores Together in One Day"},
    {"value": GOAL_TYPE_ACTIVE, "label": "Everyone Completes a Chore for X Days"},
]

# ---------------------------------------------------------------------------
# Stored keys (same strings the Challenge record already uses where it has one)
# ---------------------------------------------------------------------------
DATA_ID: Final = base.DATA_CHALLENGE_INTERNAL_ID
DATA_NAME: Final = base.DATA_CHALLENGE_NAME
DATA_DESCRIPTION: Final = base.DATA_CHALLENGE_DESCRIPTION
DATA_LABELS: Final = base.DATA_CHALLENGE_LABELS
DATA_ICON: Final = base.DATA_CHALLENGE_ICON
DATA_ASSIGNED_USER_IDS: Final = base.DATA_CHALLENGE_ASSIGNED_USER_IDS
DATA_TYPE: Final = base.DATA_CHALLENGE_TYPE
DATA_SELECTED_CHORE_ID: Final = base.DATA_CHALLENGE_SELECTED_CHORE_ID
DATA_TARGET_VALUE: Final = base.DATA_CHALLENGE_TARGET_VALUE
DATA_REWARD_POINTS: Final = base.DATA_CHALLENGE_REWARD_POINTS
DATA_PROGRESS: Final = base.DATA_CHALLENGE_PROGRESS
DATA_AWARDED: Final = base.DATA_CHALLENGE_AWARDED

# Comma-separated level targets, for example "100:10, 250:25, 500:50".
DATA_LEVELS: Final = "levels"
# Reward multiplier for the top contributor of each level (1 = off).
DATA_TOP_MULTIPLIER: Final = "top_multiplier"
# Per-person all-time totals captured when a goal is restarted.
DATA_BASELINE: Final = "family_baseline"
DATA_STREAK_COUNT: Final = "family_streak_count"
DATA_STREAK_LAST_DAY: Final = "family_streak_last_day"
# Levels completed so far, and each person's total when the level began.
DATA_LEVEL: Final = "family_level"
DATA_LEVEL_START: Final = "family_level_start"
# Best one-day total the one-day goal has reached, and who/when.
DATA_RECORD: Final = "family_record"
DATA_RECORD_DAY: Final = "family_record_day"
DATA_RECORD_TOP: Final = "family_record_top"
# Version of what a points goal counts. 2 = award points left out; goals from
# before carry snapshots that still include them and are converted on start.
DATA_POINTS_BASIS: Final = "family_points_basis"
POINTS_BASIS_NO_AWARDS: Final = 2

# Restart the goal every week (from Monday) or month, like a reset (points,
# chores and everyone-contributes goals only).
DATA_REPEAT: Final = "family_repeat"
REPEAT_NEVER: Final = "never"
REPEAT_WEEKLY: Final = "weekly"
REPEAT_MONTHLY: Final = "monthly"
REPEAT_OPTIONS: Final = (REPEAT_NEVER, REPEAT_WEEKLY, REPEAT_MONTHLY)
REPEAT_GOAL_TYPES: Final = frozenset(
    {GOAL_TYPE_POINTS, GOAL_TYPE_CHORES, GOAL_TYPE_EVERYONE}
)
# Total Chores Completed: also count every chore carrying one of these labels.
DATA_CHORE_LABELS: Final = "family_chore_labels"
# Optional last day (ISO date) progress counts; frozen after it.
DATA_END_DATE: Final = "family_end_date"
# Who is told when a level is reached.
DATA_NOTIFY: Final = "family_notify"
NOTIFY_EVERYONE: Final = "everyone"
NOTIFY_ASSIGNEES: Final = "assignees"
NOTIFY_APPROVERS: Final = "approvers"
NOTIFY_OFF: Final = "off"
NOTIFY_OPTIONS: Final = (
    NOTIFY_EVERYONE,
    NOTIFY_ASSIGNEES,
    NOTIFY_APPROVERS,
    NOTIFY_OFF,
)

# Runtime: the day the current run began (creation, reset or repeat), the
# start of the current repeat period, each share frozen when the finish date
# passed, and the finish date a reset already moved past.
DATA_STARTED: Final = "family_started"
DATA_PERIOD_START: Final = "family_period_start"
DATA_FROZEN: Final = "family_frozen"
DATA_END_CLEARED: Final = "family_end_cleared"
DATA_COMPLETED: Final = "family_completed_shares"

# Runtime state that must survive an edit of the goal's settings.
RUNTIME_KEYS: Final = (
    DATA_BASELINE,
    DATA_STREAK_COUNT,
    DATA_STREAK_LAST_DAY,
    DATA_LEVEL,
    DATA_LEVEL_START,
    DATA_RECORD,
    DATA_RECORD_DAY,
    DATA_RECORD_TOP,
    DATA_POINTS_BASIS,
    DATA_STARTED,
    DATA_PERIOD_START,
    DATA_FROZEN,
    DATA_END_CLEARED,
    DATA_COMPLETED,
    DATA_PROGRESS,
)

# Per-person progress entry
PROGRESS_CURRENT_VALUE: Final = "current_value"

DEFAULT_TARGET: Final = 100.0

# ---------------------------------------------------------------------------
# Sensor attribute names
# ---------------------------------------------------------------------------
ATTR_PURPOSE_GOAL: Final = "purpose_family_goal"
ATTR_GOAL_NAME: Final = "achievement_name"  # kept: the dashboards read this name
ATTR_TOTAL: Final = "family_total"
ATTR_CONTRIBUTIONS: Final = "family_contributions"
ATTR_CAUGHT_UP_TODAY: Final = "family_caught_up_today"
ATTR_LEVEL: Final = "family_level"
ATTR_LEVELS: Final = "family_levels"
ATTR_LEVEL_CONTRIBUTIONS: Final = "family_level_contributions"
ATTR_LEVEL_REWARDS: Final = "family_level_rewards"
ATTR_NEXT_TARGET: Final = "family_next_target"
ATTR_NEXT_REWARD: Final = "family_next_reward"
ATTR_TOP_MULTIPLIER: Final = "family_top_multiplier"
ATTR_RECORD: Final = "family_record"
ATTR_RECORD_DAY: Final = "family_record_day"
ATTR_RECORD_TOP: Final = "family_record_top"
ATTR_REPEAT: Final = "family_repeat"
ATTR_END_DATE: Final = "family_end_date"  # Finish date or end of the repeat period
ATTR_DAYS_LEFT: Final = "family_days_left"  # Including today; None without an end
ATTR_PACE: Final = "family_pace"  # ahead / on_track / behind / "" (no pace)
ATTR_FINISHED: Final = "family_finished"  # Past the finish date: progress frozen
ATTR_PACE_EXPECTED: Final = "family_pace_expected"  # Even-pace total by now
# What the end date is: the finish date, or the end of this week or month
ATTR_DEADLINE: Final = "family_deadline"
DEADLINE_FINISH: Final = "finish"
DEADLINE_WEEK: Final = "week"
DEADLINE_MONTH: Final = "month"
PACE_AHEAD: Final = "ahead"
PACE_ON_TRACK: Final = "on_track"
PACE_BEHIND: Final = "behind"

# ---------------------------------------------------------------------------
# Services
# ---------------------------------------------------------------------------
SERVICE_RESET_FAMILY_GOAL: Final = "reset_family_goal"
SERVICE_FIELD_GOAL_NAME: Final = "goal_name"
ERROR_ACTION_RESET_FAMILY_GOAL: Final = "reset_family_goal"

# ---------------------------------------------------------------------------
# Wording (translations_custom/<lang>_notifications.json, "family_goal_words")
# ---------------------------------------------------------------------------
TRANS_SECTION_GOAL_WORDS: Final = "family_goal_words"
GOAL_WORD_LEVEL: Final = "level"  # {name}, {level}
GOAL_WORD_TOP_CONTRIBUTOR: Final = "top_contributor"  # {name}, {multiplier}
GOAL_WORD_DEFAULT_NAME: Final = "default_name"
GOAL_WORD_MIGRATED_NAME: Final = "migrated_name"  # {name}
