"""Constants for reward pools (a family chips in points toward one reward).

Only what the pool package owns lives here. Data keys (``DATA_REWARD_POOLED`` ...)
and the reward form/service field names stay in the main ``const`` module because
the reward record and its forms are shared with upstream code.
"""

from typing import Final

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
