"""Family pool settings on the reward record.

The shared reward builder and validation call into this module, so the pool's
extra settings live with the pool code instead of in upstream files. The form
fields are in ``form.py`` (this module stays free of Home Assistant imports).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .. import const
from . import const as rp

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping


def suggested_values(reward: Mapping[str, Any]) -> dict[str, Any]:
    """Return a stored reward's pool settings as form values."""
    return {
        rp.DATA_REWARD_POOL_MAX_SHARE: reward.get(
            rp.DATA_REWARD_POOL_MAX_SHARE, const.DEFAULT_ZERO
        ),
        rp.DATA_REWARD_POOL_MATCH_RATIO: reward.get(
            rp.DATA_REWARD_POOL_MATCH_RATIO, const.DEFAULT_ZERO
        ),
        rp.DATA_REWARD_POOL_MATCH_USER_ID: reward.get(
            rp.DATA_REWARD_POOL_MATCH_USER_ID, const.SENTINEL_EMPTY
        ),
        rp.DATA_REWARD_POOL_AFTER_DELIVERY: reward.get(
            rp.DATA_REWARD_POOL_AFTER_DELIVERY, rp.AFTER_DELIVERY_RESTART
        ),
    }


def _number(value: Any) -> float:
    try:
        return max(0.0, float(value or 0))
    except (TypeError, ValueError):
        return 0.0


def build_settings(get_field: Callable[[str, Any], Any]) -> dict[str, Any]:
    """Return clean pool settings for a reward record.

    The closed flag is not carried over: saving the reward reopens a pool
    that closed after delivery.

    Args:
        get_field: Returns a field from the new input, else the stored reward.
    """
    after = get_field(rp.DATA_REWARD_POOL_AFTER_DELIVERY, rp.AFTER_DELIVERY_RESTART)
    return {
        rp.DATA_REWARD_POOL_MAX_SHARE: min(
            100.0, _number(get_field(rp.DATA_REWARD_POOL_MAX_SHARE, 0))
        ),
        rp.DATA_REWARD_POOL_MATCH_RATIO: _number(
            get_field(rp.DATA_REWARD_POOL_MATCH_RATIO, 0)
        ),
        rp.DATA_REWARD_POOL_MATCH_USER_ID: str(
            get_field(rp.DATA_REWARD_POOL_MATCH_USER_ID, const.SENTINEL_EMPTY) or ""
        ),
        rp.DATA_REWARD_POOL_AFTER_DELIVERY: (
            rp.AFTER_DELIVERY_CLOSE
            if after == rp.AFTER_DELIVERY_CLOSE
            else rp.AFTER_DELIVERY_RESTART
        ),
    }


def validate_settings(field: Callable[[str, Any], Any]) -> dict[str, str]:
    """Check the pool settings. Returns {form_field: error_key}."""
    try:
        max_share = float(field(rp.DATA_REWARD_POOL_MAX_SHARE, 0) or 0)
    except (TypeError, ValueError):
        max_share = -1.0
    if not 0 <= max_share <= 100:
        return {
            rp.DATA_REWARD_POOL_MAX_SHARE: (
                rp.TRANS_KEY_CFOF_REWARD_POOL_MAX_SHARE_INVALID
            )
        }
    if _number(field(rp.DATA_REWARD_POOL_MATCH_RATIO, 0)) > 0 and not field(
        rp.DATA_REWARD_POOL_MATCH_USER_ID, ""
    ):
        return {
            rp.DATA_REWARD_POOL_MATCH_USER_ID: (
                rp.TRANS_KEY_CFOF_REWARD_POOL_MATCH_NO_PARENT
            )
        }
    return {}
