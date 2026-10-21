"""Reward pool manager.

A pooled reward's cost is a shared target. Assigned users pay points into the
pool (deducted immediately); once it is full an approver confirms delivery,
which empties the pool so the family can save up again. Refunds return exactly
what each person paid.

This manager owns the whole feature. It talks to the economy and notification
managers through their public methods, so those files stay identical to upstream.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from homeassistant.exceptions import HomeAssistantError

from .. import const
from ..engines.economy_engine import InsufficientFundsError
from ..managers.base_manager import BaseManager
from ..utils.math_utils import round_points
from . import const as rp

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from ..coordinator import ChoreOpsDataCoordinator
    from ..type_defs import RewardData, UserData


class RewardPoolManager(BaseManager):
    """Contribute to, approve and refund family reward pools."""

    def __init__(
        self, hass: HomeAssistant, coordinator: ChoreOpsDataCoordinator
    ) -> None:
        """Initialize the manager."""
        super().__init__(hass, coordinator)
        self._locks: dict[str, asyncio.Lock] = {}

    async def async_setup(self) -> None:
        """Subscribe to the signals that move points or notify people."""
        self.listen(rp.SIGNAL_SUFFIX_REWARD_POOL_REFUNDED, self._on_refunded)
        self.listen(rp.SIGNAL_SUFFIX_REWARD_POOL_FILLED, self._on_filled)
        self.listen(rp.SIGNAL_SUFFIX_REWARD_POOL_APPROVED, self._on_approved)
        # A deleted reward takes its pool with it: give the points back
        self.listen(const.SIGNAL_SUFFIX_REWARD_DELETED, self._on_reward_deleted)

    def _get_lock(self, reward_id: str) -> asyncio.Lock:
        """Return the per-reward lock that serializes pool changes."""
        if reward_id not in self._locks:
            self._locks[reward_id] = asyncio.Lock()
        return self._locks[reward_id]

    def _grant(self, **kwargs: Any) -> None:
        """Record the reward as delivered to a contributor."""
        self.coordinator.reward_manager._grant_to_assignee(**kwargs)

    # =========================================================================
    # Public API: Family Pool
    # =========================================================================
    # A pooled reward's cost is a shared target. Assigned users pay points
    # into the pool (deducted immediately, before the pool records it); once
    # it is full an approver confirms delivery, which empties the pool so the
    # family can save up again. Refunds return exactly what each person paid.

    @staticmethod
    def get_pool_contributions(reward_info: RewardData) -> dict[str, float]:
        """Return the pool's points paid in, keyed by user ID.

        Args:
            reward_info: The reward record.

        Returns:
            Mapping of user_id to points contributed (empty when none).
        """
        return dict(reward_info.get(const.DATA_REWARD_POOL_CONTRIBUTIONS, {}))

    @classmethod
    def get_pool_total(cls, reward_info: RewardData) -> float:
        """Return the total points currently held in the reward's pool.

        Args:
            reward_info: The reward record.

        Returns:
            Sum of all contributions, rounded to storage precision.
        """
        return round_points(sum(cls.get_pool_contributions(reward_info).values()))

    def _get_pooled_reward_or_raise(self, reward_id: str) -> RewardData:
        """Return a pooled reward record, raising when missing or not pooled."""
        reward_info: RewardData | None = self.coordinator.rewards_data.get(reward_id)
        if not reward_info:
            raise HomeAssistantError(
                translation_domain=const.DOMAIN,
                translation_key=const.TRANS_KEY_ERROR_NOT_FOUND,
                translation_placeholders={
                    "entity_type": const.LABEL_REWARD,
                    "name": reward_id,
                },
            )
        if not reward_info.get(const.DATA_REWARD_POOLED, False):
            raise HomeAssistantError(
                translation_domain=const.DOMAIN,
                translation_key=rp.TRANS_KEY_ERROR_REWARD_NOT_POOLED,
                translation_placeholders={
                    "reward": reward_info[const.DATA_REWARD_NAME]
                },
            )
        return reward_info

    async def contribute_to_pool(
        self, assignee_id: str, reward_id: str, amount: float | None = None
    ) -> float:
        """Pay points from an assignee's balance into a pooled reward.

        The contribution is capped at what the pool still needs, so the pool
        never holds more than the reward's cost.

        Args:
            assignee_id: The contributing assignee's internal ID.
            reward_id: The pooled reward's internal ID.
            amount: Points to contribute. None contributes as much as the
                assignee can afford, up to what the pool still needs.

        Returns:
            The points actually contributed.

        Raises:
            HomeAssistantError: If the reward is not pooled, the pool is full,
                the assignee is not assigned, the amount is not positive, or
                the assignee cannot afford it.
        """
        async with self._get_lock(reward_id):
            return await self._contribute_to_pool_locked(assignee_id, reward_id, amount)

    async def _contribute_to_pool_locked(
        self, assignee_id: str, reward_id: str, amount: float | None
    ) -> float:
        """Internal contribution logic executed under the pool lock."""
        reward_info = self._get_pooled_reward_or_raise(reward_id)
        reward_name = reward_info[const.DATA_REWARD_NAME]

        assignee_info: UserData | None = self.coordinator.assignees_data.get(
            assignee_id
        )
        if not assignee_info:
            raise HomeAssistantError(
                translation_domain=const.DOMAIN,
                translation_key=const.TRANS_KEY_ERROR_NOT_FOUND,
                translation_placeholders={
                    "entity_type": const.LABEL_ASSIGNEE,
                    "name": assignee_id,
                },
            )
        assignee_name = assignee_info[const.DATA_USER_NAME]
        if assignee_id not in reward_info.get(const.DATA_REWARD_ASSIGNED_USER_IDS, []):
            raise HomeAssistantError(
                translation_domain=const.DOMAIN,
                translation_key=const.TRANS_KEY_ERROR_NOT_ASSIGNED,
                translation_placeholders={
                    "entity": reward_name,
                    "assignee": assignee_name,
                },
            )

        target = round_points(
            float(reward_info.get(const.DATA_REWARD_COST, const.DEFAULT_ZERO))
        )
        remaining = round_points(target - self.get_pool_total(reward_info))
        if remaining <= 0:
            raise HomeAssistantError(
                translation_domain=const.DOMAIN,
                translation_key=rp.TRANS_KEY_ERROR_REWARD_POOL_FULL,
                translation_placeholders={"reward": reward_name},
            )

        balance = round_points(float(assignee_info[const.DATA_USER_POINTS]))
        if amount is None:
            amount = min(balance, remaining)
        amount = round_points(min(float(amount), remaining))
        if amount <= 0:
            raise HomeAssistantError(
                translation_domain=const.DOMAIN,
                translation_key=rp.TRANS_KEY_ERROR_REWARD_POOL_INVALID_AMOUNT,
            )
        insufficient = HomeAssistantError(
            translation_domain=const.DOMAIN,
            translation_key=const.TRANS_KEY_ERROR_INSUFFICIENT_POINTS,
            translation_placeholders={
                "assignee": assignee_name,
                "current": str(balance),
                "required": str(amount),
            },
        )
        if balance < amount:
            raise insufficient

        # Take the points before recording the contribution, so the pool never
        # holds points that didn't leave a balance (for example two quick taps
        # on two different pools, which use different locks)
        try:
            await self.coordinator.economy_manager.withdraw(
                assignee_id=assignee_id,
                amount=amount,
                source=const.POINTS_SOURCE_REWARDS,
                reference_id=reward_id,
                item_name=reward_name,
                allow_negative=False,
            )
        except InsufficientFundsError as err:
            raise insufficient from err

        contributions = self.get_pool_contributions(reward_info)
        contributions[assignee_id] = round_points(
            contributions.get(assignee_id, const.DEFAULT_ZERO) + amount
        )
        reward_info[const.DATA_REWARD_POOL_CONTRIBUTIONS] = contributions
        pool_total = self.get_pool_total(reward_info)

        # Persist → Emit (per DEVELOPMENT_STANDARDS.md § 5.3)
        self.coordinator._persist_and_update()

        # Informational: the points were already withdrawn above
        self.emit(
            rp.SIGNAL_SUFFIX_REWARD_POOL_CONTRIBUTED,
            user_id=assignee_id,
            reward_id=reward_id,
            reward_name=reward_name,
            amount=amount,
            pool_total=pool_total,
        )
        if pool_total >= target:
            # NotificationManager asks approvers to confirm delivery
            self.emit(
                rp.SIGNAL_SUFFIX_REWARD_POOL_FILLED,
                reward_id=reward_id,
                reward_name=reward_name,
                pool_total=pool_total,
            )

        const.LOGGER.info(
            "Assignee '%s' paid %s points into pool for reward '%s' (%s of %s)",
            assignee_name,
            amount,
            reward_name,
            pool_total,
            target,
        )
        return amount

    async def approve_pool(self, approver_name: str, reward_id: str) -> None:
        """Confirm a full pool's reward was delivered and empty the pool.

        Contributions are already deducted, so no points move here unless the
        cost was lowered after the pool filled: the overfill is refunded in
        proportion to what each person paid.

        Args:
            approver_name: Name of the approving approver (for logging).
            reward_id: The pooled reward's internal ID.

        Raises:
            HomeAssistantError: If the reward is not pooled or the pool is not full.
        """
        async with self._get_lock(reward_id):
            reward_info = self._get_pooled_reward_or_raise(reward_id)
            reward_name = reward_info[const.DATA_REWARD_NAME]
            target = round_points(
                float(reward_info.get(const.DATA_REWARD_COST, const.DEFAULT_ZERO))
            )
            pool_total = self.get_pool_total(reward_info)
            if pool_total <= 0 or pool_total < target:
                raise HomeAssistantError(
                    translation_domain=const.DOMAIN,
                    translation_key=rp.TRANS_KEY_ERROR_REWARD_POOL_NOT_FULL,
                    translation_placeholders={
                        "reward": reward_name,
                        "total": str(pool_total),
                        "target": str(target),
                    },
                )

            contributions = self.get_pool_contributions(reward_info)
            refunds = self._split_overfill(
                contributions, round_points(pool_total - target)
            )
            for contributor_id in contributions:
                if contributor_id in self.coordinator.assignees_data:
                    self._grant(
                        assignee_id=contributor_id,
                        reward_id=reward_id,
                        cost_deducted=contributions[contributor_id]
                        - refunds.get(contributor_id, const.DEFAULT_ZERO),
                    )
            reward_info[const.DATA_REWARD_POOL_CONTRIBUTIONS] = {}

            # Persist → Emit (per DEVELOPMENT_STANDARDS.md § 5.3)
            self.coordinator._persist_and_update()

            if refunds:
                self.emit(
                    rp.SIGNAL_SUFFIX_REWARD_POOL_REFUNDED,
                    reward_id=reward_id,
                    reward_name=reward_name,
                    refunds=refunds,
                )
            self.emit(
                rp.SIGNAL_SUFFIX_REWARD_POOL_APPROVED,
                reward_id=reward_id,
                reward_name=reward_name,
                contributor_ids=list(contributions),
            )
            const.LOGGER.info(
                "Pool for reward '%s' approved by '%s' (%s points)",
                reward_name,
                approver_name,
                pool_total,
            )

    @staticmethod
    def _split_overfill(
        contributions: dict[str, float], overfill: float
    ) -> dict[str, float]:
        """Split an overfilled pool's excess across contributors by share.

        Args:
            contributions: Points paid in, keyed by user ID.
            overfill: Points held beyond the reward's cost.

        Returns:
            Refund per user ID (empty when there is no overfill). Rounding
            residue goes to the largest contributor so refunds sum exactly.
        """
        total = sum(contributions.values())
        if overfill <= 0 or total <= 0:
            return {}
        refunds = {
            user_id: round_points(overfill * paid / total)
            for user_id, paid in contributions.items()
        }
        largest = max(contributions, key=lambda user_id: contributions[user_id])
        refunds[largest] = round_points(
            refunds[largest] + overfill - sum(refunds.values())
        )
        return {user_id: amount for user_id, amount in refunds.items() if amount > 0}

    async def refund_pool(
        self, reward_id: str, user_id: str | None = None
    ) -> dict[str, float]:
        """Cancel a pool and return everyone's contribution, or just one person's.

        Works on any reward still holding pool points, so a pool can be
        refunded even after the reward was switched back to a normal reward.

        Args:
            reward_id: The reward's internal ID.
            user_id: When set, refund only this user's contribution and leave
                everyone else's points in the pool.

        Returns:
            Refund per user ID (empty when there was nothing to refund).

        Raises:
            HomeAssistantError: If the reward is not found.
        """
        async with self._get_lock(reward_id):
            reward_info: RewardData | None = self.coordinator.rewards_data.get(
                reward_id
            )
            if not reward_info:
                raise HomeAssistantError(
                    translation_domain=const.DOMAIN,
                    translation_key=const.TRANS_KEY_ERROR_NOT_FOUND,
                    translation_placeholders={
                        "entity_type": const.LABEL_REWARD,
                        "name": reward_id,
                    },
                )
            refunds = {
                user_id: amount
                for user_id, amount in self.get_pool_contributions(reward_info).items()
                if amount > 0
            }
            if user_id is not None:
                refunds = {
                    uid: amount for uid, amount in refunds.items() if uid == user_id
                }
            if not refunds:
                return {}
            if user_id is not None:
                remaining = self.get_pool_contributions(reward_info)
                remaining.pop(user_id, None)
                reward_info[const.DATA_REWARD_POOL_CONTRIBUTIONS] = remaining
            else:
                reward_info[const.DATA_REWARD_POOL_CONTRIBUTIONS] = {}

            # Persist → Emit (per DEVELOPMENT_STANDARDS.md § 5.3)
            self.coordinator._persist_and_update()

            # EconomyManager deposits each refund
            self.emit(
                rp.SIGNAL_SUFFIX_REWARD_POOL_REFUNDED,
                reward_id=reward_id,
                reward_name=reward_info[const.DATA_REWARD_NAME],
                refunds=refunds,
            )
            const.LOGGER.info(
                "Refunded pool for reward '%s' to %d contributors",
                reward_info[const.DATA_REWARD_NAME],
                len(refunds),
            )
            return refunds

    # =========================================================================
    # Signal handlers (points and notifications)
    # =========================================================================

    async def _on_refunded(self, payload: dict[str, Any]) -> None:
        """Return each contributor's points.

        Refunds use the rewards source, so statistics treat them as a reversal
        of points spent rather than points earned.
        """
        refunds: dict[str, float] = payload.get("refunds", {})
        for assignee_id, amount in refunds.items():
            if amount <= 0 or assignee_id not in self.coordinator.assignees_data:
                continue
            await self.coordinator.economy_manager.deposit(
                assignee_id=assignee_id,
                amount=amount,
                source=const.POINTS_SOURCE_REWARDS,
                reference_id=payload.get("reward_id"),
                item_name=payload.get("reward_name"),
            )

    async def _on_filled(self, payload: dict[str, Any]) -> None:
        """Ask approvers to deliver a reward whose pool is full."""
        await self.coordinator.notification_manager.broadcast_to_all_approvers(
            title_key=rp.TRANS_KEY_NOTIF_TITLE_REWARD_POOL_FULL_APPROVER,
            message_key=rp.TRANS_KEY_NOTIF_MESSAGE_REWARD_POOL_FULL_APPROVER,
            placeholders={
                "reward_name": str(payload.get("reward_name", "")),
                "points": str(payload.get("pool_total", 0)),
            },
        )

    async def _on_approved(self, payload: dict[str, Any]) -> None:
        """Tell every contributor the reward was delivered."""
        reward_id = payload.get("reward_id", "")
        reward_name = payload.get("reward_name", "")
        for assignee_id in payload.get("contributor_ids", []):
            if assignee_id not in self.coordinator.assignees_data:
                continue
            await self.coordinator.notification_manager.notify_assignee_translated(
                assignee_id,
                title_key=const.TRANS_KEY_NOTIF_TITLE_REWARD_APPROVED_ASSIGNEE,
                message_key=const.TRANS_KEY_NOTIF_MESSAGE_REWARD_APPROVED_ASSIGNEE,
                message_data={"reward_name": reward_name},
                extra_data={
                    const.DATA_USER_ID: assignee_id,
                    const.DATA_REWARD_ID: reward_id,
                },
            )

    async def _on_reward_deleted(self, payload: dict[str, Any]) -> None:
        """Refund whatever a deleted reward's pool was holding."""
        refunds = {
            user_id: amount
            for user_id, amount in (payload.get("pool_contributions") or {}).items()
            if amount > 0
        }
        if refunds:
            await self._on_refunded(
                {
                    "reward_id": payload.get("reward_id"),
                    "reward_name": payload.get("reward_name"),
                    "refunds": refunds,
                }
            )

    # =========================================================================
    # Helpers for sensors
    # =========================================================================

    def status_override(
        self, reward_info: RewardData, cost: float, assignee_points: float
    ) -> str | None:
        """Return the reward state for a pooled reward, or None if not pooled."""
        if not reward_info.get(const.DATA_REWARD_POOLED, False):
            return None
        if self.get_pool_total(reward_info) >= cost:
            return const.REWARD_STATE_REQUESTED
        if assignee_points > 0:
            return const.REWARD_STATE_AVAILABLE
        return const.REWARD_STATE_LOCKED

    def sensor_attributes(
        self, reward_info: RewardData, assignee_id: str
    ) -> dict[str, Any]:
        """Return the pool_* attributes for a reward status sensor."""
        attrs: dict[str, Any] = {
            rp.ATTR_REWARD_POOLED: bool(
                reward_info.get(const.DATA_REWARD_POOLED, False)
            )
        }
        if not attrs[rp.ATTR_REWARD_POOLED]:
            return attrs
        from ..helpers.entity_helpers import get_assignee_name_by_id

        target = round_points(
            float(reward_info.get(const.DATA_REWARD_COST, const.DEFAULT_ZERO))
        )
        total = self.get_pool_total(reward_info)
        contributions = self.get_pool_contributions(reward_info)
        attrs.update(
            {
                rp.ATTR_REWARD_POOL_TOTAL: total,
                rp.ATTR_REWARD_POOL_REMAINING: max(
                    round_points(target - total), const.DEFAULT_ZERO
                ),
                rp.ATTR_REWARD_POOL_FULL: total >= target,
                rp.ATTR_REWARD_POOL_CHIP_IN: reward_info.get(
                    const.DATA_REWARD_POOL_CHIP_IN, const.DEFAULT_ZERO
                ),
                rp.ATTR_REWARD_POOL_MY_CONTRIBUTION: contributions.get(
                    assignee_id, const.DEFAULT_ZERO
                ),
                rp.ATTR_REWARD_POOL_CONTRIBUTIONS: {
                    get_assignee_name_by_id(self.coordinator, user_id)
                    or user_id: amount
                    for user_id, amount in contributions.items()
                },
            }
        )
        return attrs
