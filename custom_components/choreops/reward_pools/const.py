"""Constants for reward pools (a family chips in points toward one reward).

Only what the pool package owns lives here. Data keys (``DATA_REWARD_POOLED`` ...)
and the reward form/service field names stay in the main ``const`` module because
the reward record and its forms are shared with upstream code.
"""

from typing import Final

# Pool settings stored on the reward record (form fields use the same names)
# Most one person may pay in, as a percent of the cost (0 = no limit)
DATA_REWARD_POOL_MAX_SHARE: Final = "pool_max_share"
# A parent adds this many points for each point someone else pays in (0 = off)
DATA_REWARD_POOL_MATCH_RATIO: Final = "pool_match_ratio"
# The parents (users with a points balance) who share paying the match
DATA_REWARD_POOL_MATCH_USER_IDS: Final = "pool_match_user_ids"
# What happens once the reward is delivered: save up again, or close the pool
DATA_REWARD_POOL_AFTER_DELIVERY: Final = "pool_after_delivery"
AFTER_DELIVERY_RESTART: Final = "restart"
AFTER_DELIVERY_CLOSE: Final = "close"
# Runtime: a closed pool takes no chip-ins until the reward is edited and saved
DATA_REWARD_POOL_CLOSED: Final = "pool_closed"

POOL_SETTING_KEYS: Final = (
    DATA_REWARD_POOL_MAX_SHARE,
    DATA_REWARD_POOL_MATCH_RATIO,
    DATA_REWARD_POOL_MATCH_USER_IDS,
    DATA_REWARD_POOL_AFTER_DELIVERY,
)

# Events emitted by the pool manager
SIGNAL_SUFFIX_REWARD_POOL_CONTRIBUTED: Final = "reward_pool_contributed"
SIGNAL_SUFFIX_REWARD_POOL_FILLED: Final = "reward_pool_filled"
SIGNAL_SUFFIX_REWARD_POOL_APPROVED: Final = "reward_pool_approved"
SIGNAL_SUFFIX_REWARD_POOL_REFUNDED: Final = "reward_pool_refunded"

# Notification translation keys
TRANS_KEY_NOTIF_TITLE_REWARD_POOL_FULL_APPROVER: Final = (
    "notification_title_reward_pool_full_approver"
)
TRANS_KEY_NOTIF_MESSAGE_REWARD_POOL_FULL_APPROVER: Final = (
    "notification_message_reward_pool_full_approver"
)

# Error translation keys
TRANS_KEY_ERROR_REWARD_NOT_POOLED: Final = "reward_not_pooled"  # {reward}
TRANS_KEY_ERROR_REWARD_POOL_FULL: Final = "reward_pool_full"  # {reward}
TRANS_KEY_ERROR_REWARD_POOL_NOT_FULL: Final = (
    "reward_pool_not_full"  # {reward} has {total} of {target}
)
TRANS_KEY_ERROR_REWARD_POOL_INVALID_AMOUNT: Final = "reward_pool_invalid_amount"
TRANS_KEY_ERROR_REWARD_POOL_CLOSED: Final = "reward_pool_closed"  # {reward}
TRANS_KEY_ERROR_REWARD_POOL_SHARE_REACHED: Final = (
    "reward_pool_share_reached"  # {name} {reward} {limit}
)

# Reward form / service validation keys (options error and exceptions)
TRANS_KEY_CFOF_REWARD_POOL_COST_ZERO: Final = "reward_pool_cost_zero"
TRANS_KEY_CFOF_REWARD_POOL_CHIP_IN_TOO_HIGH: Final = "reward_pool_chip_in_too_high"
TRANS_KEY_CFOF_REWARD_POOL_MAX_SHARE_INVALID: Final = "reward_pool_max_share_invalid"
TRANS_KEY_CFOF_REWARD_POOL_MATCH_NO_PARENT: Final = "reward_pool_match_no_parent"

# Services
SERVICE_CONTRIBUTE_TO_REWARD_POOL: Final = "contribute_to_reward_pool"
SERVICE_APPROVE_REWARD_POOL: Final = "approve_reward_pool"
SERVICE_REFUND_REWARD_POOL: Final = "refund_reward_pool"

# Authorization error actions
ERROR_ACTION_CONTRIBUTE_REWARD_POOL: Final = "contribute_to_reward_pools"
ERROR_ACTION_MANAGE_REWARD_POOL: Final = "manage_reward_pools"

# Reward status sensor attributes (only present for pooled rewards)
ATTR_REWARD_POOLED: Final = "pooled"
ATTR_REWARD_POOL_TOTAL: Final = "pool_total"
ATTR_REWARD_POOL_REMAINING: Final = "pool_remaining"
ATTR_REWARD_POOL_CONTRIBUTIONS: Final = "pool_contributions"
ATTR_REWARD_POOL_MY_CONTRIBUTION: Final = "pool_my_contribution"
ATTR_REWARD_POOL_FULL: Final = "pool_full"
ATTR_REWARD_POOL_CHIP_IN: Final = "pool_chip_in"
ATTR_REWARD_POOL_CLOSED: Final = "pool_closed"
ATTR_REWARD_POOL_MAX_SHARE: Final = "pool_max_share"  # Points, 0 = no limit
ATTR_REWARD_POOL_MY_SHARE_LEFT: Final = "pool_my_share_left"  # None = no limit
ATTR_REWARD_POOL_MATCH_RATIO: Final = "pool_match_ratio"
ATTR_REWARD_POOL_MATCH_NAMES: Final = "pool_match_names"
# True when a match is set but none of its parents has points left to pay it
ATTR_REWARD_POOL_MATCH_OUT: Final = "pool_match_out"
