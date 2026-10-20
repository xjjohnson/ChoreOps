"""Build and validate Family Goal records."""

from __future__ import annotations

import re
from typing import Any
import uuid

from .. import const as base
from ..data_builders import EntityValidationError
from ..utils.math_utils import parse_points_value
from . import const as fg

# Error keys (translated under the options-flow errors).
ERR_NAME_REQUIRED = "family_goal_name_required"
ERR_NAME_DUPLICATE = "family_goal_name_duplicate"
ERR_NO_ASSIGNEES = "family_goal_no_assignees"
ERR_INVALID_TYPE = "family_goal_invalid_type"
ERR_INVALID_TARGET = "family_goal_invalid_target"
ERR_INVALID_LEVELS = "family_goal_invalid_levels"
ERR_INVALID_MULTIPLIER = "family_goal_invalid_top_multiplier"
ERR_INVALID_REWARD = "family_goal_invalid_reward_points"


def parse_levels(raw: Any) -> list[tuple[float, float | None]]:
    """Parse a goal's levels into (target, reward) pairs.

    Text looks like "100:10, 250:25, 500:50": each level is a target, optionally
    followed by a colon and the reward paid at that level. A level with no reward
    pays the goal's base reward (None here). Items can be separated by commas,
    semicolons or new lines. An already-parsed list of pairs is also accepted.

    Raises:
        ValueError: A target or reward is not a number, a target is not above
            zero, a reward is negative, or the targets do not strictly increase.
    """
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        items = [
            f"{item[0]}:{item[1]}" if isinstance(item, (list, tuple)) else str(item)
            for item in raw
        ]
    else:
        items = re.split(r"[,;\n]+", str(raw))

    levels: list[tuple[float, float | None]] = []
    previous = 0.0
    for item in items:
        text = item.strip()
        if not text:
            continue
        target_text, _, reward_text = re.sub(r"\s*[:=]\s*", ":", text).partition(":")
        target = float(target_text)
        reward = float(reward_text) if reward_text.strip() else None
        if target <= previous or (reward is not None and reward < 0):
            raise ValueError("levels must increase from above zero, rewards >= 0")
        previous = target
        levels.append((target, reward))
    return levels


def validate_goal(
    data: dict[str, Any],
    existing_goals: dict[str, Any] | None = None,
    *,
    current_goal_id: str | None = None,
) -> dict[str, str]:
    """Validate a goal. Returns {field: error_key}; empty means valid."""
    errors: dict[str, str] = {}

    name = data.get(fg.DATA_NAME, "")
    name = name.strip() if isinstance(name, str) else ""
    if not name:
        errors[fg.DATA_NAME] = ERR_NAME_REQUIRED
        return errors

    for goal_id, goal in (existing_goals or {}).items():
        if goal_id != current_goal_id and goal.get(fg.DATA_NAME) == name:
            errors[fg.DATA_NAME] = ERR_NAME_DUPLICATE
            return errors

    if not data.get(fg.DATA_ASSIGNED_USER_IDS):
        errors[fg.DATA_ASSIGNED_USER_IDS] = ERR_NO_ASSIGNEES
        return errors

    if data.get(fg.DATA_TYPE) not in fg.GOAL_TYPES:
        errors[fg.DATA_TYPE] = ERR_INVALID_TYPE
        return errors

    if data.get(fg.DATA_LEVELS):
        try:
            parse_levels(data[fg.DATA_LEVELS])
        except ValueError:
            errors[fg.DATA_LEVELS] = ERR_INVALID_LEVELS
            return errors
    elif fg.DATA_TARGET_VALUE in data:
        try:
            if float(data[fg.DATA_TARGET_VALUE]) <= 0:
                raise ValueError("target must be above zero")
        except (TypeError, ValueError):
            errors[fg.DATA_TARGET_VALUE] = ERR_INVALID_TARGET
            return errors

    if data.get(fg.DATA_TOP_MULTIPLIER) not in (None, ""):
        try:
            if float(data[fg.DATA_TOP_MULTIPLIER]) < 1:
                raise ValueError("multiplier must be at least 1")
        except (TypeError, ValueError):
            errors[fg.DATA_TOP_MULTIPLIER] = ERR_INVALID_MULTIPLIER
            return errors

    if fg.DATA_REWARD_POINTS in data:
        try:
            parse_points_value(
                data[fg.DATA_REWARD_POINTS], allow_negative=False, allow_zero=True
            )
        except ValueError:
            errors[fg.DATA_REWARD_POINTS] = ERR_INVALID_REWARD
            return errors

    return errors


def _as_list(value: Any) -> list[str]:
    """Return a list of strings from a list, a single value or nothing."""
    if value in (None, ""):
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value]
    return [str(value)]


def build_goal(
    user_input: dict[str, Any],
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a complete goal record for create (existing=None) or update.

    Runtime state (progress, levels reached, streaks, baselines, records) is
    carried over from `existing` so editing a goal's settings never loses it.

    Raises:
        EntityValidationError: The name is empty.
    """

    def get_field(key: str, default: Any) -> Any:
        if key in user_input:
            return user_input[key]
        if existing is not None:
            return existing.get(key, default)
        return default

    raw_name = get_field(fg.DATA_NAME, "")
    name = str(raw_name).strip() if raw_name else ""
    if not name:
        raise EntityValidationError(
            field=fg.DATA_NAME,
            translation_key=ERR_NAME_REQUIRED,
        )

    goal_id = (
        str(uuid.uuid4())
        if existing is None
        else existing.get(fg.DATA_ID, str(uuid.uuid4()))
    )
    goal: dict[str, Any] = {
        fg.DATA_ID: goal_id,
        fg.DATA_NAME: name,
        fg.DATA_DESCRIPTION: str(get_field(fg.DATA_DESCRIPTION, base.SENTINEL_EMPTY)),
        fg.DATA_LABELS: _as_list(get_field(fg.DATA_LABELS, [])),
        fg.DATA_ICON: str(get_field(fg.DATA_ICON, base.SENTINEL_EMPTY)),
        fg.DATA_ASSIGNED_USER_IDS: _as_list(get_field(fg.DATA_ASSIGNED_USER_IDS, [])),
        fg.DATA_TYPE: str(get_field(fg.DATA_TYPE, fg.GOAL_TYPE_CHORES)),
        fg.DATA_SELECTED_CHORE_ID: str(
            get_field(fg.DATA_SELECTED_CHORE_ID, base.SENTINEL_EMPTY)
        ),
        fg.DATA_TARGET_VALUE: float(get_field(fg.DATA_TARGET_VALUE, fg.DEFAULT_TARGET)),
        fg.DATA_LEVELS: str(get_field(fg.DATA_LEVELS, base.SENTINEL_EMPTY)).strip(),
        fg.DATA_TOP_MULTIPLIER: float(get_field(fg.DATA_TOP_MULTIPLIER, 1.0) or 1.0),
        fg.DATA_REWARD_POINTS: parse_points_value(
            get_field(fg.DATA_REWARD_POINTS, 0.0),
            allow_negative=False,
            allow_zero=True,
        ),
        fg.DATA_PROGRESS: dict(get_field(fg.DATA_PROGRESS, {})),
    }

    if existing:
        for key in fg.RUNTIME_KEYS:
            if key in existing and key != fg.DATA_PROGRESS:
                goal[key] = existing[key]

    # With explicit levels, the first level is the goal's base target.
    try:
        levels = parse_levels(goal[fg.DATA_LEVELS])
    except ValueError:
        levels = []
    if levels:
        goal[fg.DATA_TARGET_VALUE] = levels[0][0]

    return goal
