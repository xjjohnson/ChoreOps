"""Validation rules for family pool rewards.

Called from the shared reward validation, so the options flow and the
create/update reward services enforce the same rules.
"""

from __future__ import annotations

from typing import Any

from .. import const
from ..utils.math_utils import parse_points_value
from . import const as rp, settings


def _points(value: Any) -> float | None:
    """Return a points value as a float, or None when it can't be read."""
    try:
        return parse_points_value(value or 0, allow_negative=False, allow_zero=True)
    except ValueError:
        return None


def validate_pool_settings(
    data: dict[str, Any], existing: dict[str, Any] | None = None
) -> dict[str, str]:
    """Check a pooled reward's cost, chip-in amount and pool settings.

    A pool needs a target above zero, one chip-in can't be more than the
    whole target, the most one person may pay is 0-100 % and a match needs a
    parent to pay it. Fields missing from ``data`` (a partial update) fall back to
    the stored reward.

    Args:
        data: Reward data with DATA_* keys (may be a partial update).
        existing: The stored reward being updated, if any.

    Returns:
        Dict of errors: {error_field: translation_key}. Empty when valid or
        when the reward is not pooled.
    """
    stored = existing or {}

    def field(key: str, default: Any) -> Any:
        return data[key] if key in data else stored.get(key, default)

    if not field(const.DATA_REWARD_POOLED, False):
        return {}

    cost = _points(field(const.DATA_REWARD_COST, const.DEFAULT_ZERO))
    if cost is None:
        return {}  # The general cost check reports unreadable values
    if cost <= 0:
        return {const.CFOP_ERROR_REWARD_COST: rp.TRANS_KEY_CFOF_REWARD_POOL_COST_ZERO}

    chip_in = _points(field(const.DATA_REWARD_POOL_CHIP_IN, const.DEFAULT_ZERO))
    if chip_in is not None and chip_in > cost:
        return {
            const.CFOF_REWARDS_INPUT_POOL_CHIP_IN: (
                rp.TRANS_KEY_CFOF_REWARD_POOL_CHIP_IN_TOO_HIGH
            )
        }
    return settings.validate_settings(field)
