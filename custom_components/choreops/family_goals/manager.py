"""Family Goal manager.

A family goal pools every assigned person's contribution into ONE total and
awards everyone assigned together. Goals are stored in the ``challenges``
bucket. Rewards are paid through the challenge-completed signal, which the
economy and notification managers already handle, so this manager needs no
hooks in them.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING, Any, cast

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.start import async_at_started

from .. import const as base
from ..helpers import entity_helpers as eh, translation_helpers as th
from ..helpers.entity_helpers import remove_entities_by_item_id
from ..managers.base_manager import BaseManager
from ..utils.dt_utils import dt_today_iso
from . import builders, const as fg

if TYPE_CHECKING:
    import asyncio

    from homeassistant.core import HomeAssistant

    from ..coordinator import ChoreOpsDataCoordinator

_DEBOUNCE_SECONDS: float = 2.0

# Points that goals pay out must not trigger another evaluation of themselves.
_OWN_POINT_SOURCES = {base.POINTS_SOURCE_CHALLENGES}

# Award points never count toward a points goal: only chores, bonuses and
# manual adds do.
_AWARD_POINT_SOURCES = (
    base.POINTS_SOURCE_CHALLENGES,
    base.POINTS_SOURCE_ACHIEVEMENTS,
    base.POINTS_SOURCE_BADGES,
)

_NO_CHORE = (
    base.SENTINEL_EMPTY,
    base.SENTINEL_NONE_TEXT,
    base.SENTINEL_NO_SELECTION,
)


def _fill(words: dict[str, str], key: str, **values: Any) -> str:
    """Fill a goal wording template, falling back to the plain goal name.

    A template that is missing or has a broken placeholder (a bad translation)
    never stops a payout; the goal name alone is used instead.
    """
    try:
        return words[key].format(**values)
    except (KeyError, IndexError, ValueError):
        return str(values.get("name", ""))


class FamilyGoalManager(BaseManager):
    """Evaluate, pay and manage family goals."""

    def __init__(
        self, hass: HomeAssistant, coordinator: ChoreOpsDataCoordinator
    ) -> None:
        """Initialize the manager."""
        super().__init__(hass, coordinator)
        self._pending: set[str] = set()
        self._timer: asyncio.TimerHandle | None = None
        self._is_unloading = False
        self._debounce_seconds = _DEBOUNCE_SECONDS

    # ------------------------------------------------------------------
    # Setup and triggers
    # ------------------------------------------------------------------

    async def async_setup(self) -> None:
        """Move legacy family achievements over, then subscribe to events."""
        await self.migrate_legacy_achievements()
        self.migrate_points_basis()
        for suffix in (
            base.SIGNAL_SUFFIX_STATS_UPDATED,
            base.SIGNAL_SUFFIX_CHORE_APPROVED,
            base.SIGNAL_SUFFIX_CHORE_DISAPPROVED,
            base.SIGNAL_SUFFIX_CHORE_STATUS_RESET,
            base.SIGNAL_SUFFIX_CHORE_OVERDUE,
            base.SIGNAL_SUFFIX_REWARD_APPROVED,
            base.SIGNAL_SUFFIX_BONUS_APPLIED,
            base.SIGNAL_SUFFIX_PENALTY_APPLIED,
        ):
            self.listen(suffix, self._on_assignee_event)
        self.listen(base.SIGNAL_SUFFIX_POINTS_CHANGED, self._on_points_changed)
        self.listen(base.SIGNAL_SUFFIX_MIDNIGHT_ROLLOVER, self._on_midnight_rollover)
        # A points or chore data reset lowers everyone's counts; re-check every
        # goal so its saved snapshots follow them down.
        for suffix in (
            base.SIGNAL_SUFFIX_CHORE_DATA_RESET_COMPLETE,
            base.SIGNAL_SUFFIX_POINTS_DATA_RESET_COMPLETE,
            base.SIGNAL_SUFFIX_CHALLENGE_DATA_RESET_COMPLETE,
        ):
            self.listen(suffix, self._on_data_reset)

        self.coordinator.config_entry.async_on_unload(self._cancel_timer)
        # A streak broken while HA was down is noticed once HA has started.
        self.coordinator.config_entry.async_on_unload(
            async_at_started(self.hass, lambda _hass: self._mark_all_pending())
        )

    async def migrate_legacy_achievements(self) -> int:
        """Convert family achievements from earlier versions into goals.

        Earlier versions stored family goals as achievements. Each one is moved
        into the goals bucket with its progress, levels, streaks and records
        intact, and its old achievement entities are removed. Runs on every
        start but only acts when legacy records exist.

        Returns:
            The number of achievements converted.
        """
        achievements = self.coordinator._data.get(base.DATA_ACHIEVEMENTS, {})
        legacy = {
            old_id: record
            for old_id, record in achievements.items()
            if isinstance(record, dict) and record.get(fg.DATA_TYPE) in fg.GOAL_TYPES
        }
        if not legacy:
            return 0

        words = await self._goal_words(self.hass.config.language)
        taken = {
            str(goal.get(fg.DATA_NAME, "")).strip().lower()
            for goal in self.goals.values()
        }
        for old_id, record in legacy.items():
            source = dict(record)
            source[fg.DATA_LABELS] = source.pop(
                base.DATA_ACHIEVEMENT_LABELS, source.get(fg.DATA_LABELS, [])
            )
            name = str(source.get(fg.DATA_NAME, "")).strip() or _fill(
                words, fg.GOAL_WORD_DEFAULT_NAME
            )
            if name.lower() in taken:
                name = _fill(words, fg.GOAL_WORD_MIGRATED_NAME, name=name)
            source[fg.DATA_NAME] = name
            taken.add(name.lower())

            goal = dict(builders.build_goal(source))
            for key in (*fg.RUNTIME_KEYS, fg.DATA_AWARDED):
                if key in record:
                    goal[key] = record[key]
            self.coordinator._data.setdefault(base.DATA_CHALLENGES, {})[
                str(goal[fg.DATA_ID])
            ] = goal

            del achievements[old_id]
            remove_entities_by_item_id(
                self.hass, self.coordinator.config_entry.entry_id, old_id
            )
            base.LOGGER.info("Migrated family achievement '%s' to a family goal", name)

        self.coordinator._persist(immediate=True)
        return len(legacy)

    def _cancel_timer(self) -> None:
        self._is_unloading = True
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _on_assignee_event(self, payload: dict[str, Any]) -> None:
        """Re-evaluate the person an event is about."""
        assignee_id = payload.get("user_id")
        if assignee_id:
            self._mark_pending(assignee_id)

    def _on_points_changed(self, payload: dict[str, Any]) -> None:
        """Re-evaluate on point changes, except the ones goals paid themselves."""
        if payload.get("source", "") in _OWN_POINT_SOURCES:
            return
        self._on_assignee_event(payload)

    def _on_data_reset(self, payload: dict[str, Any]) -> None:
        """Lower every goal's snapshots at once after history was cleared.

        Done before anyone earns again, so new progress is not taken for the
        old counts; then everyone is re-evaluated.
        """
        changed = False
        for goal in self.goals.values():
            if isinstance(goal, dict) and not self.is_finished(goal):
                changed = self._lower_snapshots(goal) or changed
        if changed:
            self.coordinator._persist_and_update()
        self._mark_all_pending()

    async def _on_midnight_rollover(self, payload: dict[str, Any]) -> None:
        """Re-evaluate everyone: streaks and one-day goals turn over at midnight."""
        self._mark_all_pending()
        await self.drain_pending()

    def _mark_all_pending(self) -> None:
        for assignee_id in self.coordinator.assignees_data:
            self._mark_pending(assignee_id)

    def _mark_pending(self, assignee_id: str) -> None:
        """Queue a person; a burst of events becomes one evaluation pass."""
        self._pending.add(assignee_id)
        if self._is_unloading:
            return
        self.hass.loop.call_soon_threadsafe(self._schedule)

    def _schedule(self) -> None:
        if self._is_unloading:
            return
        if self._timer:
            self._timer.cancel()
        self._timer = self.hass.loop.call_later(
            self._debounce_seconds,
            lambda: self.hass.add_job(self.drain_pending()),
        )

    async def drain_pending(self) -> None:
        """Evaluate everyone queued, now."""
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        queued = self._pending.copy()
        self._pending.clear()
        for assignee_id in queued:
            try:
                await self.evaluate_assignee(assignee_id)
            except Exception:
                base.LOGGER.exception(
                    "Error evaluating family goals for assignee %s", assignee_id
                )

    async def evaluate_assignee(self, assignee_id: str) -> None:
        """Re-check one person's streak and every goal they are part of."""
        # Only people assigned to a goal can move its total.
        goal_ids = [
            goal_id
            for goal_id, goal in self.goals.items()
            if assignee_id in goal.get(fg.DATA_ASSIGNED_USER_IDS, [])
            and self._levels(goal)
        ]
        # Wording is loaded up front: nothing below may await, so two
        # evaluations can never interleave and pay the same level twice, and
        # cached chore statuses never outlive a change made by other work.
        words: dict[str, dict[str, dict[str, str]]] = {}
        for goal_id in goal_ids:
            if (goal := self.goals.get(goal_id)) is not None:
                words[goal_id] = await self._words_by_assignee(goal)

        # Caught-up checks ask for every chore's status for everyone in a
        # goal; reuse those lookups within one person's evaluation
        with self.coordinator.chore_manager.status_cache():
            if self._update_assignee_caught_up_streak(assignee_id):
                self.coordinator._persist_and_update()
            for goal_id in goal_ids:
                # An edit during the await replaces the stored record; use the live one.
                goal = self.goals.get(goal_id)
                if goal is not None and goal_id in words:
                    self._evaluate_goal(goal_id, goal, words[goal_id])

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    @property
    def goals(self) -> dict[str, Any]:
        """All goals, keyed by internal ID (stored in the challenges bucket)."""
        return cast("dict[str, Any]", self.coordinator.challenges_data)

    def _not_found(self, goal_id: str) -> HomeAssistantError:
        return HomeAssistantError(
            translation_domain=base.DOMAIN,
            translation_key=base.TRANS_KEY_ERROR_NOT_FOUND,
            translation_placeholders={"entity_type": "family goal", "name": goal_id},
        )

    def create_goal(
        self,
        user_input: dict[str, Any],
        internal_id: str | None = None,
        *,
        immediate_persist: bool = False,
    ) -> str:
        """Create a goal and return its internal ID."""
        goal = dict(builders.build_goal(user_input))
        goal[fg.DATA_POINTS_BASIS] = fg.POINTS_BASIS_NO_AWARDS
        goal[fg.DATA_STARTED] = dt_today_iso()
        if internal_id:
            goal[fg.DATA_ID] = internal_id
        goal_id = str(goal[fg.DATA_ID])
        self.coordinator._data.setdefault(base.DATA_CHALLENGES, {})[goal_id] = goal
        self.coordinator._persist(immediate=immediate_persist)
        self.coordinator.async_update_listeners()
        self.emit(
            base.SIGNAL_SUFFIX_CHALLENGE_CREATED,
            challenge_id=goal_id,
            challenge_name=str(goal[fg.DATA_NAME]),
        )
        base.LOGGER.info(
            "Created family goal '%s' (ID: %s)", goal[fg.DATA_NAME], goal_id
        )
        return goal_id

    def update_goal(
        self,
        goal_id: str,
        updates: dict[str, Any],
        *,
        immediate_persist: bool = False,
    ) -> dict[str, Any]:
        """Update a goal's settings; progress and streaks are kept."""
        existing = self.goals.get(goal_id)
        if existing is None:
            raise self._not_found(goal_id)
        goal = dict(builders.build_goal(updates, existing=existing))
        goal[fg.DATA_ID] = goal_id
        if goal.get(fg.DATA_REPEAT) != existing.get(fg.DATA_REPEAT, fg.REPEAT_NEVER):
            # A new repeat setting starts counting periods from now, rather
            # than restarting the goal at once
            goal.pop(fg.DATA_PERIOD_START, None)
        # build_goal copies progress by value; keep the live object.
        goal[fg.DATA_PROGRESS] = existing.get(fg.DATA_PROGRESS, {})
        self.coordinator._data[base.DATA_CHALLENGES][goal_id] = goal
        self.coordinator._persist(immediate=immediate_persist)
        self.coordinator.async_update_listeners()
        # A new target or rule can finish a level now; check everyone.
        self._mark_all_pending()
        self.emit(
            base.SIGNAL_SUFFIX_CHALLENGE_UPDATED,
            challenge_id=goal_id,
            challenge_name=str(goal[fg.DATA_NAME]),
        )
        return goal

    def delete_goal(self, goal_id: str, *, immediate_persist: bool = False) -> None:
        """Delete a goal and its entities."""
        goal = self.goals.get(goal_id)
        if goal is None:
            raise self._not_found(goal_id)
        name = goal.get(fg.DATA_NAME, goal_id)
        del self.coordinator._data[base.DATA_CHALLENGES][goal_id]
        remove_entities_by_item_id(
            self.hass, self.coordinator.config_entry.entry_id, goal_id
        )
        self.coordinator._persist(immediate=immediate_persist)
        self.coordinator.async_update_listeners()
        self.emit(
            base.SIGNAL_SUFFIX_CHALLENGE_DELETED,
            challenge_id=goal_id,
            challenge_name=name,
        )
        base.LOGGER.info("Deleted family goal '%s' (ID: %s)", name, goal_id)

    def get_goal_id_by_name(self, name: str) -> str | None:
        """Return a goal's ID from its name, or None."""
        for goal_id, goal in self.goals.items():
            if goal.get(fg.DATA_NAME) == name:
                return str(goal_id)
        return None

    # ------------------------------------------------------------------
    # Contributions and totals
    # ------------------------------------------------------------------

    def _assigned_ids(self, goal: dict[str, Any]) -> list[str]:
        """Assigned people who still exist."""
        return [
            assignee_id
            for assignee_id in goal.get(fg.DATA_ASSIGNED_USER_IDS, [])
            if assignee_id in self.coordinator.assignees_data
        ]

    def _raw_contribution(self, assignee_id: str, goal: dict[str, Any]) -> float:
        """Return one person's all-time contribution to a goal."""
        assignee_data = self.coordinator.assignees_data.get(assignee_id)
        if not assignee_data:
            return 0.0

        goal_type = goal.get(fg.DATA_TYPE)

        if goal_type == fg.GOAL_TYPE_POINTS:
            point_periods = assignee_data.get(base.DATA_USER_POINT_PERIODS, {})
            earned = float(
                self.coordinator.stats.get_period_total(
                    point_periods,
                    base.PERIOD_ALL_TIME,
                    base.DATA_USER_POINT_PERIOD_POINTS_EARNED,
                    period_key_mapping={
                        base.PERIOD_ALL_TIME: base.DATA_USER_POINT_PERIODS_ALL_TIME
                    },
                )
            )
            # Award points (goal payouts, achievements, badges) are not effort
            # toward a goal, and a level's own payout must not carry the goal
            # toward its next level.
            return max(0.0, earned - self._award_points(assignee_data))

        if goal_type == fg.GOAL_TYPE_DAY:
            return float(self._approved_today(assignee_id))

        # Chores goal: optionally scoped to one chore and/or chores with chosen
        # labels, otherwise all chores.
        counted = self._counted_chore_ids(goal)
        if counted is not None:
            scoped = (
                self.coordinator.statistics_manager.get_badge_scoped_all_time_stats(
                    assignee_id, counted
                )
            )
            return float(scoped.get(base.DATA_USER_CHORE_DATA_PERIOD_APPROVED, 0))

        chore_periods = assignee_data.get(base.DATA_USER_CHORE_PERIODS, {})
        all_time_container = cast(
            "dict[str, Any]",
            chore_periods.get(base.DATA_USER_CHORE_DATA_PERIODS_ALL_TIME, {}),
        )
        bucket = cast(
            "dict[str, Any]", all_time_container.get(base.PERIOD_ALL_TIME, {})
        )
        return float(bucket.get(base.DATA_USER_CHORE_DATA_PERIOD_APPROVED, 0))

    def _counted_chore_ids(self, goal: dict[str, Any]) -> list[str] | None:
        """Return the chores a chores goal counts, or None for every chore.

        The selected chore plus every chore carrying one of the goal's chore
        labels. Only Total Chores Completed goals are scoped.
        """
        if goal.get(fg.DATA_TYPE) != fg.GOAL_TYPE_CHORES:
            return None
        selected = str(goal.get(fg.DATA_SELECTED_CHORE_ID, ""))
        labels = set(goal.get(fg.DATA_CHORE_LABELS) or [])
        if (not selected or selected in _NO_CHORE) and not labels:
            return None
        counted = [selected] if selected and selected not in _NO_CHORE else []
        if labels:
            counted.extend(
                str(chore_id)
                for chore_id, chore in self.coordinator.chores_data.items()
                if str(chore_id) != selected
                and labels.intersection(chore.get(base.DATA_CHORE_LABELS) or [])
            )
        return counted

    @staticmethod
    def _award_points(assignee_data: Any) -> float:
        """Return a person's all-time points from awards (goals, achievements, badges)."""
        point_periods = assignee_data.get(base.DATA_USER_POINT_PERIODS, {})
        all_time = cast(
            "dict[str, Any]",
            cast(
                "dict[str, Any]",
                point_periods.get(base.DATA_USER_POINT_PERIODS_ALL_TIME, {}),
            ).get(base.PERIOD_ALL_TIME, {}),
        )
        by_source = cast(
            "dict[str, Any]",
            all_time.get(base.DATA_USER_POINT_PERIOD_BY_SOURCE, {}),
        )
        return sum(
            max(0.0, float(by_source.get(source, 0.0) or 0.0))
            for source in _AWARD_POINT_SOURCES
        )

    @staticmethod
    def _award_points_since_last_payout(assignee_data: Any, goal_id: str) -> float:
        """Return award points a person got since this goal's latest payout to them.

        The latest payout marks when the current level began. Read from the
        point ledger, which only keeps recent history: when the payout has
        aged out, 0 is returned.
        """
        ledger = assignee_data.get(base.DATA_USER_LEDGER, [])
        if not isinstance(ledger, list):
            return 0.0
        start = None
        for index in range(len(ledger) - 1, -1, -1):
            entry = ledger[index]
            if (
                isinstance(entry, dict)
                and entry.get(base.DATA_LEDGER_SOURCE) == base.POINTS_SOURCE_CHALLENGES
                and entry.get(base.DATA_LEDGER_REFERENCE_ID) == goal_id
            ):
                start = index
                break
        if start is None:
            return 0.0
        return sum(
            max(0.0, float(entry.get(base.DATA_LEDGER_AMOUNT, 0.0) or 0.0))
            for entry in ledger[start:]
            if isinstance(entry, dict)
            and entry.get(base.DATA_LEDGER_SOURCE) in _AWARD_POINT_SOURCES
        )

    def migrate_points_basis(self) -> int:
        """Convert points goals saved before award points were left out.

        Their level-start and restart snapshots still include award points, so
        every share read as 0 until a person out-earned all their past awards.
        Each snapshot is shifted by the award points that existed when it was
        taken: shares carry on from where they were, minus any awards since the
        level began (found in the point ledger; when that history is gone,
        shares carry on unchanged). Runs once per goal.

        Returns:
            The number of goals converted.
        """
        converted = 0
        for goal_id, goal in self.goals.items():
            if not isinstance(goal, dict):
                continue
            if goal.get(fg.DATA_POINTS_BASIS) == fg.POINTS_BASIS_NO_AWARDS:
                continue
            goal[fg.DATA_POINTS_BASIS] = fg.POINTS_BASIS_NO_AWARDS
            converted += 1
            if goal.get(fg.DATA_TYPE) != fg.GOAL_TYPE_POINTS:
                continue
            level_start = dict(goal.get(fg.DATA_LEVEL_START, {}) or {})
            baseline = dict(goal.get(fg.DATA_BASELINE, {}) or {})
            for assignee_id, assignee_data in self.coordinator.assignees_data.items():
                awarded_now = self._award_points(assignee_data)
                # Restart baselines: the restart time is unknown, so the shift
                # keeps the progress since the restart as it was.
                old_base = float(baseline.get(assignee_id, 0.0))
                new_base = max(0.0, old_base - awarded_now)
                if assignee_id in baseline:
                    baseline[assignee_id] = new_base
                if assignee_id in level_start:
                    # Points earned when the level began, minus the awards held then.
                    awarded_then = awarded_now - self._award_points_since_last_payout(
                        assignee_data, str(goal_id)
                    )
                    earned_then = float(level_start[assignee_id]) + old_base
                    level_start[assignee_id] = max(
                        0.0, earned_then - max(0.0, awarded_then) - new_base
                    )
            goal[fg.DATA_LEVEL_START] = level_start
            if baseline:
                goal[fg.DATA_BASELINE] = baseline
            base.LOGGER.info(
                "Family goal '%s' converted to points without awards",
                goal.get(fg.DATA_NAME, goal_id),
            )
        if converted:
            self.coordinator._persist()
        return converted

    def _contribution(self, assignee_id: str, goal: dict[str, Any]) -> float:
        """Return one person's contribution since the goal was last restarted."""
        raw = self._raw_contribution(assignee_id, goal)
        baseline = goal.get(fg.DATA_BASELINE, {})
        if goal.get(fg.DATA_TYPE) == fg.GOAL_TYPE_DAY and (
            str(goal.get(fg.DATA_STARTED, "")) != dt_today_iso()
        ):
            # Already scoped to today; a restart baseline only counts on the
            # day it was taken, so tomorrow starts from zero.
            return raw
        return max(0.0, raw - float(baseline.get(assignee_id, 0.0)))

    def _lower_snapshots(self, goal: dict[str, Any]) -> bool:
        """Lower restart and level-start snapshots above a person's current count.

        Counts only go down when history is cleared (a points or chore data
        reset). A snapshot left above the new count would hide that person's
        progress until they caught up with it, so it is lowered to match and
        new progress counts at once.

        Returns:
            True when a snapshot changed.
        """
        if goal.get(fg.DATA_TYPE) in fg.STREAK_GOAL_TYPES:
            return False
        changed = False
        baseline = goal.get(fg.DATA_BASELINE)
        level_start = goal.get(fg.DATA_LEVEL_START)
        for assignee_id in self._assigned_ids(goal):
            if isinstance(baseline, dict) and assignee_id in baseline:
                raw = self._raw_contribution(assignee_id, goal)
                if float(baseline[assignee_id]) > raw:
                    baseline[assignee_id] = raw
                    changed = True
            if isinstance(level_start, dict) and assignee_id in level_start:
                share = self._contribution(assignee_id, goal)
                if float(level_start[assignee_id]) > share:
                    level_start[assignee_id] = share
                    changed = True
        return changed

    def get_contributions(self, goal_id: str) -> dict[str, float]:
        """Return each assigned person's contribution (read-only, for sensors)."""
        goal = self.goals.get(goal_id)
        if not goal or goal.get(fg.DATA_TYPE) in fg.STREAK_GOAL_TYPES:
            # Streak goals are a shared day count, not a sum of shares.
            return {}
        frozen = goal.get(fg.DATA_FROZEN)
        if isinstance(frozen, dict) and self.is_finished(goal):
            # Past the finish date: shares stay where they were on the day
            return {
                assignee_id: float(frozen.get(assignee_id, 0.0))
                for assignee_id in self._assigned_ids(goal)
            }
        return {
            assignee_id: self._contribution(assignee_id, goal)
            for assignee_id in self._assigned_ids(goal)
        }

    def get_total(self, goal_id: str) -> float:
        """Return the pooled total toward a goal.

        Points or chores pooled since the last restart, or the current day
        streak for the streak goals.
        """
        goal = self.goals.get(goal_id)
        goal_type = goal.get(fg.DATA_TYPE) if goal else None
        if goal and goal_type in fg.STREAK_GOAL_TYPES:
            return float(goal.get(fg.DATA_STREAK_COUNT, 0))
        shares = self.get_contributions(goal_id)
        if goal_type == fg.GOAL_TYPE_EVERYONE:
            # Only as strong as the smallest share.
            return min(shares.values(), default=0.0)
        return sum(shares.values())

    # ------------------------------------------------------------------
    # Levels
    # ------------------------------------------------------------------

    def _levels(self, goal: dict[str, Any]) -> list[tuple[float, float]]:
        """Return a goal's levels as (target, reward) pairs.

        A level with no reward of its own pays the goal's base reward. A goal
        with no levels entered has exactly one level: its target.
        """
        base_reward = float(goal.get(fg.DATA_REWARD_POINTS, 0.0))
        try:
            parsed = builders.parse_levels(goal.get(fg.DATA_LEVELS, ""))
        except ValueError:
            parsed = []
        if parsed:
            return [
                (target, base_reward if reward is None else reward)
                for target, reward in parsed
            ]
        target = float(goal.get(fg.DATA_TARGET_VALUE, 0.0))
        return [(target, base_reward)] if target > 0 else []

    def get_level_contributions(self, goal_id: str) -> dict[str, float]:
        """Return each person's contribution during the CURRENT level only."""
        goal = self.goals.get(goal_id)
        if not goal:
            return {}
        if goal.get(fg.DATA_TYPE) == fg.GOAL_TYPE_DAY:
            # One day's effort: today's counts are the level's shares.
            return self.get_contributions(goal_id)
        start = goal.get(fg.DATA_LEVEL_START, {})
        return {
            assignee_id: max(0.0, value - float(start.get(assignee_id, 0.0)))
            for assignee_id, value in self.get_contributions(goal_id).items()
        }

    def _next_level_start(
        self,
        goal_id: str,
        goal: dict[str, Any],
        level_shares: dict[str, float],
        overshoot: float,
    ) -> dict[str, float]:
        """Return the level-start snapshot for a level just begun.

        Points past the finished level's target carry into the new level, so a
        big jump does not leave everyone at 0. Each person carries the same
        fraction of what they added during the finished level.
        """
        shares = self.get_contributions(goal_id)
        level_total = sum(level_shares.values())
        if goal.get(fg.DATA_TYPE) == fg.GOAL_TYPE_EVERYONE or level_total <= 0:
            # Only as strong as the smallest share: there is no pooled extra.
            return shares
        carry = min(max(overshoot, 0.0), level_total) / level_total
        return {
            assignee_id: value - level_shares.get(assignee_id, 0.0) * carry
            for assignee_id, value in shares.items()
        }

    def get_level_info(self, goal_id: str) -> dict[str, Any]:
        """Return level progress for a goal (read-only, for sensors)."""
        empty: dict[str, Any] = {
            "level": 0,
            "levels": [],
            "rewards": [],
            "next_target": 0.0,
            "next_reward": 0.0,
        }
        goal = self.goals.get(goal_id)
        if not goal:
            return empty
        levels = self._levels(goal)
        reached = int(goal.get(fg.DATA_LEVEL, 0))
        if not levels:
            return {**empty, "level": reached}
        next_index = min(reached, len(levels) - 1)
        return {
            "level": reached,
            "levels": [target for target, _ in levels],
            "rewards": [reward for _, reward in levels],
            "next_target": levels[next_index][0],
            "next_reward": levels[next_index][1],
        }

    # ------------------------------------------------------------------
    # Caught-up and active day streaks
    # ------------------------------------------------------------------

    def _assignee_ids_with_chores(self, assignee_id: str) -> list[str]:
        return [
            str(chore_id)
            for chore_id in self.coordinator.assignees_data[assignee_id].get(
                base.DATA_USER_CHORE_DATA, {}
            )
            if chore_id in self.coordinator.chores_data
        ]

    def _approved_today(self, assignee_id: str) -> int:
        """Return how many chores this person had approved today."""
        today_stats = self.coordinator.statistics_manager.get_badge_scoped_today_stats(
            assignee_id,
            self._assignee_ids_with_chores(assignee_id),
            today_iso=dt_today_iso(),
        )
        return int(today_stats.get("today_approved", 0))

    def _assignee_caught_up_snapshot(
        self, assignee_id: str, last_day: str, today_iso: str
    ) -> dict[str, int | bool]:
        """Return one person's open/done chore counts for today.

        "Open" matches what the dashboard's "All Caught Up!" banner uses: chores
        actionable for the person today (the due-today summary) plus anything
        claimed but not yet approved. Overdue chores also block the day.
        """
        stats = self.coordinator.statistics_manager
        chore_manager = self.coordinator.chore_manager
        chore_ids = self._assignee_ids_with_chores(assignee_id)
        open_count = 0
        overdue_count = 0
        for chore_id in chore_ids:
            context = chore_manager.get_chore_status_context(assignee_id, chore_id)
            state = context.get(base.CHORE_CTX_STATE)
            if state == base.CHORE_STATE_OVERDUE:
                overdue_count += 1
            elif state == base.CHORE_STATE_CLAIMED or (
                chore_manager.chore_counts_toward_due_today_summary(
                    assignee_id,
                    chore_id,
                    status_context=context,
                    local_today_iso=today_iso,
                )
            ):
                open_count += 1
        today_stats = stats.get_badge_scoped_today_stats(
            assignee_id, chore_ids, today_iso=today_iso
        )
        return {
            "open": open_count,
            "done": int(today_stats.get("today_approved", 0)),
            "overdue": overdue_count > 0,
            "missed": stats.has_missed_occurrence_since_advance(
                chore_ids,
                last_update_day_iso=last_day,
                today_iso=today_iso,
            ),
        }

    def _caught_up_snapshots(
        self, goal: dict[str, Any], last_day: str, today_iso: str
    ) -> dict[str, dict[str, int | bool]]:
        return {
            assignee_id: self._assignee_caught_up_snapshot(
                assignee_id, last_day, today_iso
            )
            for assignee_id in self._assigned_ids(goal)
        }

    def _update_assignee_caught_up_streak(self, assignee_id: str) -> bool:
        """Advance or break one person's "All Caught Up" day streak.

        A day counts once everything due is approved, something was done, and
        nothing is overdue. Days with nothing due are neutral. An overdue or
        missed scheduled chore ends the streak. Safe to call repeatedly: a day
        is only counted once.

        Returns:
            True when stored streak state changed.
        """
        assignee_info = self.coordinator.assignees_data.get(assignee_id)
        if assignee_info is None:
            return False
        today_iso = dt_today_iso()
        streak: dict[str, Any] = (
            assignee_info.get(base.DATA_USER_CAUGHT_UP_STREAK) or {}
        )
        count = int(streak.get("count", 0))
        best = int(streak.get("best", 0))
        last_day = str(streak.get("last_day", ""))
        if last_day == today_iso:
            return False

        snap = self._assignee_caught_up_snapshot(assignee_id, last_day, today_iso)
        changed = False
        if count > 0 and (snap["missed"] or snap["overdue"]):
            count = 0
            changed = True
        if int(snap["done"]) > 0 and int(snap["open"]) == 0 and not snap["overdue"]:
            count += 1
            best = max(best, count)
            last_day = today_iso
            changed = True
        if changed:
            assignee_info[base.DATA_USER_CAUGHT_UP_STREAK] = {
                "count": count,
                "last_day": last_day,
                "best": best,
            }
        return changed

    def get_caught_up_status(self, goal_id: str) -> dict[str, dict[str, int | bool]]:
        """Return today's per-person caught-up progress, keyed by display name.

        For sensors, so a dashboard can show who is holding the day up. Each
        person gets ``open`` (still to do today), ``done`` (approved today) and
        ``overdue``; the dashboard turns them into words in its own language.
        """
        goal = self.goals.get(goal_id)
        if not goal:
            return {}
        last_day = str(goal.get(fg.DATA_STREAK_LAST_DAY, ""))
        snapshots = self._caught_up_snapshots(goal, last_day, dt_today_iso())
        names = {
            assignee_id: str(
                eh.get_assignee_name_by_id(self.coordinator, assignee_id) or assignee_id
            )
            for assignee_id in snapshots
        }
        return {
            names[assignee_id]: {
                "open": int(snap["open"]),
                "done": int(snap["done"]),
                "overdue": bool(snap["overdue"]),
            }
            for assignee_id, snap in snapshots.items()
        }

    def _update_active_streak(self, goal: dict[str, Any]) -> bool:
        """Advance or break the "everyone completes a chore" day streak.

        A day counts once every assigned person has had at least one chore
        approved. If a whole day passed without counting, the streak is void;
        that is noticed lazily on the next evaluation. Safe to call repeatedly.

        Returns:
            True when stored streak state changed.
        """
        today_iso = dt_today_iso()
        last_day = str(goal.get(fg.DATA_STREAK_LAST_DAY, ""))
        count = int(goal.get(fg.DATA_STREAK_COUNT, 0))
        if last_day == today_iso:
            return False

        changed = False
        yesterday_iso = (date.fromisoformat(today_iso) - timedelta(days=1)).isoformat()
        if count > 0 and last_day != yesterday_iso:
            count = 0
            changed = True

        assigned = self._assigned_ids(goal)
        if assigned and all(self._approved_today(a) >= 1 for a in assigned):
            count += 1
            goal[fg.DATA_STREAK_LAST_DAY] = today_iso
            changed = True
        if changed:
            goal[fg.DATA_STREAK_COUNT] = count
        return changed

    def _update_caught_up_streak(self, goal: dict[str, Any]) -> bool:
        """Advance or break the pooled "everyone caught up" streak.

        A day counts once every assigned person has finished everything that is
        due today and nobody has anything overdue. Days where nothing is owed
        are neutral, and a day still in progress changes nothing. A scheduled
        chore that passed unmet since the streak last advanced breaks it.

        Returns:
            True when stored streak state changed.
        """
        today_iso = dt_today_iso()
        last_day = str(goal.get(fg.DATA_STREAK_LAST_DAY, ""))
        count = int(goal.get(fg.DATA_STREAK_COUNT, 0))
        if last_day == today_iso:
            return False

        status = self._caught_up_snapshots(goal, last_day, today_iso)
        owed_total = sum(int(v["done"]) for v in status.values())
        all_done = all(int(v["open"]) == 0 for v in status.values())
        any_overdue = any(bool(v["overdue"]) for v in status.values())
        any_missed = count > 0 and any(bool(v["missed"]) for v in status.values())

        changed = False
        if any_missed and count != 0:
            count = 0
            changed = True
        if owed_total > 0 and all_done and not any_overdue:
            count += 1
            goal[fg.DATA_STREAK_LAST_DAY] = today_iso
            changed = True
        if changed:
            goal[fg.DATA_STREAK_COUNT] = count
        return changed

    # ------------------------------------------------------------------
    # One-day goal
    # ------------------------------------------------------------------

    def get_day_record(self, goal_id: str) -> dict[str, Any]:
        """Return the one-day goal's best day for sensors ({} for other goals)."""
        goal = self.goals.get(goal_id)
        if not goal or goal.get(fg.DATA_TYPE) != fg.GOAL_TYPE_DAY:
            return {}
        top_ids = [a for a in str(goal.get(fg.DATA_RECORD_TOP, "")).split(",") if a]
        return {
            fg.ATTR_RECORD: float(goal.get(fg.DATA_RECORD, 0.0)),
            fg.ATTR_RECORD_DAY: str(goal.get(fg.DATA_RECORD_DAY, "")),
            fg.ATTR_RECORD_TOP: [
                eh.get_assignee_name_by_id(self.coordinator, a) or a for a in top_ids
            ],
        }

    def _update_day_record(self, goal_id: str, goal: dict[str, Any]) -> bool:
        """Remember the best one-day total the one-day goal has reached.

        Survives the daily restart and a goal reset. Ties do not replace an
        older record.
        """
        shares = self.get_contributions(goal_id)
        total = sum(shares.values())
        if total <= float(goal.get(fg.DATA_RECORD, 0)):
            return False
        best = max(shares.values(), default=0.0)
        top_ids = sorted(a for a, v in shares.items() if v == best and best > 0)
        goal[fg.DATA_RECORD] = total
        goal[fg.DATA_RECORD_DAY] = dt_today_iso()
        goal[fg.DATA_RECORD_TOP] = ",".join(top_ids)
        return True

    def _restart_day_goal_if_new_day(self, goal: dict[str, Any]) -> bool:
        """Start the one-day goal over when a new day begins.

        Levels, awards and the level snapshot are cleared so the goal can be
        earned again today. Reward points already paid are untouched.
        """
        today_iso = dt_today_iso()
        if str(goal.get(fg.DATA_STREAK_LAST_DAY, "")) == today_iso:
            return False
        goal[fg.DATA_STREAK_LAST_DAY] = today_iso
        goal[fg.DATA_LEVEL] = 0
        goal[fg.DATA_LEVEL_START] = {}
        for entry in goal.setdefault(fg.DATA_PROGRESS, {}).values():
            if isinstance(entry, dict):
                entry[fg.DATA_AWARDED] = False
        return True

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def reset_goal(self, goal_id: str) -> None:
        """Restart a goal from zero.

        Points and chores goals remember each person's current all-time total
        as a baseline, so only future activity counts (for the one-day goal,
        only for the rest of today, so levels already paid today are not paid
        again). The streak goals clear
        their streak (today is not counted, tomorrow is day one). Everyone's
        award is cleared so the goal can be earned again; reward points already
        paid out are untouched.

        Raises:
            HomeAssistantError: The goal does not exist.
        """
        goal = self.goals.get(goal_id)
        if not goal:
            raise self._not_found(goal_id)
        self._restart(goal)
        base.LOGGER.info("Family goal %s restarted", goal_id)
        self.coordinator._persist_and_update()

    def _restart(self, goal: dict[str, Any]) -> None:
        """Start a goal over from zero (the reset, without saving).

        A finish date already passed stops applying, so the goal counts again.
        """
        today = dt_today_iso()
        if goal.get(fg.DATA_TYPE) in fg.STREAK_GOAL_TYPES:
            goal[fg.DATA_STREAK_COUNT] = 0
            goal[fg.DATA_STREAK_LAST_DAY] = today
        else:
            goal[fg.DATA_BASELINE] = {
                assignee_id: self._raw_contribution(assignee_id, goal)
                for assignee_id in self._assigned_ids(goal)
            }

        goal[fg.DATA_LEVEL] = 0
        goal[fg.DATA_LEVEL_START] = {}
        for entry in goal.setdefault(fg.DATA_PROGRESS, {}).values():
            if isinstance(entry, dict):
                entry_dict = cast("dict[str, Any]", entry)
                entry_dict[fg.DATA_AWARDED] = False
                entry_dict[fg.PROGRESS_CURRENT_VALUE] = base.DEFAULT_ZERO

        goal[fg.DATA_STARTED] = today
        period_start = self._period_start(goal, date.fromisoformat(today))
        if period_start is not None:
            goal[fg.DATA_PERIOD_START] = period_start.isoformat()
        goal.pop(fg.DATA_FROZEN, None)
        end = self._end_date(goal)
        if end is not None and end.isoformat() < today:
            goal[fg.DATA_END_CLEARED] = end.isoformat()

    # ------------------------------------------------------------------
    # Repeat, finish date and pace
    # ------------------------------------------------------------------

    @staticmethod
    def _period_start(goal: dict[str, Any], today: date) -> date | None:
        """Return the first day of the goal's current repeat period, or None."""
        if goal.get(fg.DATA_TYPE) not in fg.REPEAT_GOAL_TYPES:
            return None
        repeat = goal.get(fg.DATA_REPEAT)
        if repeat == fg.REPEAT_WEEKLY:
            return today - timedelta(days=today.weekday())
        if repeat == fg.REPEAT_MONTHLY:
            return today.replace(day=1)
        return None

    @staticmethod
    def _period_end(goal: dict[str, Any], start: date) -> date:
        """Return the last day of the repeat period that begins on `start`."""
        if goal.get(fg.DATA_REPEAT) == fg.REPEAT_WEEKLY:
            return start + timedelta(days=6)
        next_month = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        return next_month - timedelta(days=1)

    @staticmethod
    def _end_date(goal: dict[str, Any]) -> date | None:
        """Return the goal's finish date, or None."""
        try:
            return builders.parse_end_date(goal.get(fg.DATA_END_DATE))
        except ValueError:
            return None

    def is_finished(self, goal: dict[str, Any]) -> bool:
        """Return True once the finish date has passed (until a reset or repeat)."""
        end = self._end_date(goal)
        return (
            end is not None
            and end.isoformat() < dt_today_iso()
            and goal.get(fg.DATA_END_CLEARED) != end.isoformat()
        )

    def _update_run(self, goal_id: str, goal: dict[str, Any]) -> bool:
        """Start a new repeat period, or freeze the goal after its finish date.

        Returns:
            True when stored state changed.
        """
        today = date.fromisoformat(dt_today_iso())
        changed = False
        period_start = self._period_start(goal, today)
        if period_start is not None:
            stored = goal.get(fg.DATA_PERIOD_START)
            if not stored:
                # First period: count from now, restart when the next begins
                goal[fg.DATA_PERIOD_START] = period_start.isoformat()
                changed = True
            elif stored != period_start.isoformat():
                self._restart(goal)
                base.LOGGER.info("Family goal %s repeated for a new period", goal_id)
                changed = True
        if not goal.get(fg.DATA_STARTED):
            goal[fg.DATA_STARTED] = today.isoformat()
            changed = True

        finished = self.is_finished(goal)
        if finished and not isinstance(goal.get(fg.DATA_FROZEN), dict):
            goal[fg.DATA_FROZEN] = {
                assignee_id: self._contribution(assignee_id, goal)
                for assignee_id in self._assigned_ids(goal)
            }
            base.LOGGER.info("Family goal %s finished; progress frozen", goal_id)
            changed = True
        elif not finished and fg.DATA_FROZEN in goal:
            # The finish date was moved later: count again
            goal.pop(fg.DATA_FROZEN)
            changed = True
        return changed

    def get_schedule(self, goal_id: str) -> dict[str, Any]:
        """Return the goal's deadline, days left and pace (read-only, for sensors).

        The deadline is the finish date or the end of the repeat period,
        whichever comes first. Pace compares the total with an even pace from
        the run's start to the deadline toward the final level: ahead (10 %
        over), on track, or behind (10 % under). The streak and one-day goals
        get no pace.
        """
        goal = self.goals.get(goal_id)
        empty: dict[str, Any] = {
            fg.ATTR_REPEAT: fg.REPEAT_NEVER,
            fg.ATTR_END_DATE: "",
            fg.ATTR_DAYS_LEFT: None,
            fg.ATTR_PACE: "",
            fg.ATTR_FINISHED: False,
            fg.ATTR_PACE_EXPECTED: None,
            fg.ATTR_DEADLINE: "",
        }
        if not goal:
            return empty
        today = date.fromisoformat(dt_today_iso())
        period_start = self._period_start(goal, today)
        deadlines: list[date] = []
        end = self._end_date(goal)
        if end is not None and goal.get(fg.DATA_END_CLEARED) != end.isoformat():
            deadlines.append(end)
        if period_start is not None:
            deadlines.append(self._period_end(goal, period_start))
        finished = self.is_finished(goal)
        result = {
            **empty,
            fg.ATTR_REPEAT: fg.REPEAT_NEVER
            if period_start is None
            else str(goal.get(fg.DATA_REPEAT)),
            fg.ATTR_FINISHED: finished,
        }
        if not deadlines:
            return result
        deadline = min(deadlines)
        result[fg.ATTR_END_DATE] = deadline.isoformat()
        if end is not None and deadline == end:
            result[fg.ATTR_DEADLINE] = fg.DEADLINE_FINISH
        elif goal.get(fg.DATA_REPEAT) == fg.REPEAT_WEEKLY:
            result[fg.ATTR_DEADLINE] = fg.DEADLINE_WEEK
        else:
            result[fg.ATTR_DEADLINE] = fg.DEADLINE_MONTH
        result[fg.ATTR_DAYS_LEFT] = max(0, (deadline - today).days + 1)

        levels = self._levels(goal)
        try:
            started = date.fromisoformat(str(goal.get(fg.DATA_STARTED, ""))[:10])
        except ValueError:
            return result
        if period_start is not None:
            started = max(started, period_start)
        if (
            finished
            or not levels
            or goal.get(fg.DATA_TYPE) in (*fg.STREAK_GOAL_TYPES, fg.GOAL_TYPE_DAY)
            or not started <= today <= deadline
        ):
            return result
        target = levels[-1][0]
        total = self.get_total(goal_id)
        span = (deadline - started).days + 1
        # Half of today counts as gone: on day one nobody is already behind
        expected = target * ((today - started).days + 0.5) / span
        result[fg.ATTR_PACE_EXPECTED] = round(expected, 1)
        ratio = total / expected if expected > 0 else 1.0
        if total >= target or ratio >= 1.1:
            result[fg.ATTR_PACE] = fg.PACE_AHEAD
        elif ratio >= 0.9:
            result[fg.ATTR_PACE] = fg.PACE_ON_TRACK
        else:
            result[fg.ATTR_PACE] = fg.PACE_BEHIND
        return result

    # ------------------------------------------------------------------
    # Evaluation and awarding
    # ------------------------------------------------------------------

    def _evaluate_goal(
        self,
        goal_id: str,
        goal: dict[str, Any],
        words: dict[str, dict[str, str]],
    ) -> None:
        """Award a goal to everyone assigned once the pooled total is met.

        People who already hold the award are skipped, so this is safe to call
        repeatedly (it runs whenever any assigned person is re-evaluated).
        Never awaits; ``words`` is each person's wording, loaded beforehand.
        """
        levels = self._levels(goal)
        if not levels:
            return

        if self._update_run(goal_id, goal):
            self.coordinator._persist_and_update()
        if self.is_finished(goal):
            return

        if self._lower_snapshots(goal):
            self.coordinator._persist_and_update()

        goal_type = goal.get(fg.DATA_TYPE)
        if goal_type == fg.GOAL_TYPE_DAY and self._restart_day_goal_if_new_day(goal):
            self.coordinator._persist_and_update()
        if goal_type == fg.GOAL_TYPE_DAY and self._update_day_record(goal_id, goal):
            self.coordinator._persist_and_update()
        if (
            goal_type == fg.GOAL_TYPE_CAUGHT_UP and self._update_caught_up_streak(goal)
        ) or (goal_type == fg.GOAL_TYPE_ACTIVE and self._update_active_streak(goal)):
            self.coordinator._persist_and_update()

        total = self.get_total(goal_id)
        reached = int(goal.get(fg.DATA_LEVEL, 0))
        progress = goal.setdefault(fg.DATA_PROGRESS, {})
        multiplier = float(goal.get(fg.DATA_TOP_MULTIPLIER, 1.0))

        # More than one level can be crossed at once (for example after a bulk
        # point adjustment); each one is awarded in turn.
        while reached < len(levels) and total >= levels[reached][0]:
            reached += 1
            is_final = reached == len(levels)
            level_shown = reached if len(levels) > 1 else None

            # Top contributor(s) of the level just finished: the most added
            # since the level began. Ties share the bonus; nobody wins it with
            # zero contribution (and the streak goals have no shares at all).
            level_shares = self.get_level_contributions(goal_id)
            best = max(level_shares.values(), default=0.0)
            top_ids = (
                {a for a, v in level_shares.items() if v == best}
                if multiplier > 1 and best > 0
                else set()
            )
            goal[fg.DATA_LEVEL] = reached
            goal[fg.DATA_LEVEL_START] = self._next_level_start(
                goal_id, goal, level_shares, total - levels[reached - 1][0]
            )

            for assignee_id in self._assigned_ids(goal):
                entry = progress.get(assignee_id)
                if isinstance(entry, dict) and entry.get(fg.DATA_AWARDED):
                    continue
                is_top = assignee_id in top_ids
                reward = levels[reached - 1][1] * (multiplier if is_top else 1.0)
                base.LOGGER.info(
                    "Family goal %s level %s reached - awarding assignee %s%s",
                    goal_id,
                    reached,
                    assignee_id,
                    " (top contributor)" if is_top else "",
                )
                self._award(
                    assignee_id,
                    goal_id,
                    goal,
                    level=level_shown,
                    reward=reward,
                    name=self._payout_name(
                        words.get(assignee_id, {}),
                        goal,
                        level_shown,
                        multiplier if is_top else None,
                    ),
                    is_final=is_final,
                )

    async def _goal_words(self, language: str | None) -> dict[str, str]:
        """Return the goal wording for a language, filled in from English."""
        english = await th.load_notification_translation(self.hass, "en")
        words = dict(english.get(fg.TRANS_SECTION_GOAL_WORDS, {}))
        if language and language != "en":
            local = await th.load_notification_translation(self.hass, language)
            words.update(local.get(fg.TRANS_SECTION_GOAL_WORDS, {}))
        return {key: str(value) for key, value in words.items()}

    async def _words_by_assignee(
        self, goal: dict[str, Any]
    ) -> dict[str, dict[str, str]]:
        """Return each assigned person's goal wording, in their own language."""
        words: dict[str, dict[str, str]] = {}
        for assignee_id in self._assigned_ids(goal):
            assignee_info: dict[str, Any] = cast(
                "dict[str, Any]", self.coordinator.assignees_data.get(assignee_id, {})
            )
            language = str(
                assignee_info.get(base.DATA_USER_DASHBOARD_LANGUAGE)
                or self.hass.config.language
            )
            words[assignee_id] = await self._goal_words(language)
        return words

    @staticmethod
    def _payout_name(
        words: dict[str, str],
        goal: dict[str, Any],
        level: int | None,
        top_multiplier: float | None,
    ) -> str:
        """Return the ledger/notification name of a payout."""
        name = str(goal.get(fg.DATA_NAME, ""))
        if level is not None:
            name = _fill(words, fg.GOAL_WORD_LEVEL, name=name, level=level)
        if top_multiplier is not None:
            name = _fill(
                words,
                fg.GOAL_WORD_TOP_CONTRIBUTOR,
                name=name,
                multiplier=f"{top_multiplier:g}",
            )
        return name

    def _award(
        self,
        assignee_id: str,
        goal_id: str,
        goal: dict[str, Any],
        *,
        level: int | None,
        reward: float,
        name: str,
        is_final: bool,
    ) -> None:
        """Mark one person's award and pay it through the challenge signal."""
        # Payout handlers may change data; nothing cached may outlive them
        self.coordinator.chore_manager.clear_status_cache()
        entry = goal.setdefault(fg.DATA_PROGRESS, {}).setdefault(assignee_id, {})
        entry[fg.DATA_AWARDED] = is_final
        entry[fg.PROGRESS_CURRENT_VALUE] = goal.get(fg.DATA_TARGET_VALUE, 1)

        self.coordinator._persist_and_update()

        # EconomyManager deposits the points and NotificationManager notifies
        # the person and/or their approvers (as the goal's setting says); both
        # already listen for this signal.
        notify = goal.get(fg.DATA_NOTIFY, fg.NOTIFY_EVERYONE)
        self.emit(
            base.SIGNAL_SUFFIX_CHALLENGE_COMPLETED,
            user_id=assignee_id,
            challenge_id=goal_id,
            user_name=eh.get_assignee_name_by_id(self.coordinator, assignee_id) or "",
            challenge_name=name,
            challenge_points=reward,
            notify_assignee=notify in (fg.NOTIFY_EVERYONE, fg.NOTIFY_ASSIGNEES),
            notify_approvers=notify in (fg.NOTIFY_EVERYONE, fg.NOTIFY_APPROVERS),
        )

    # ------------------------------------------------------------------
    # Overview (OpsCenter reset card)
    # ------------------------------------------------------------------

    def get_overview(self) -> list[dict[str, Any]]:
        """Return every goal as name/type/total/target for the OpsCenter card.

        Read straight from storage so the card does not depend on per-person
        entity lookups. The target is the level being worked toward now.
        """
        overview: list[dict[str, Any]] = []
        for goal_id, goal in self.goals.items():
            name = str(goal.get(fg.DATA_NAME, "")).strip()
            if not name:
                continue
            overview.append(
                {
                    "name": name,
                    "type": str(goal.get(fg.DATA_TYPE, "")),
                    "total": round(float(self.get_total(goal_id)), 2),
                    "target": round(
                        float(
                            self.get_level_info(goal_id)["next_target"]
                            or goal.get(fg.DATA_TARGET_VALUE, 0)
                            or 0
                        ),
                        2,
                    ),
                }
            )
        overview.sort(key=lambda item: item["name"].lower())
        return overview
