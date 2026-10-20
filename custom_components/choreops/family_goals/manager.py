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
from ..helpers import entity_helpers as eh
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

_NO_CHORE = (
    base.SENTINEL_EMPTY,
    base.SENTINEL_NONE_TEXT,
    base.SENTINEL_NO_SELECTION,
)


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
        """Subscribe to the events that can move a goal's total."""
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

        self.coordinator.config_entry.async_on_unload(self._cancel_timer)
        # A streak broken while HA was down is noticed once HA has started.
        self.coordinator.config_entry.async_on_unload(
            async_at_started(self.hass, lambda _hass: self._mark_all_pending())
        )

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
        if self._update_assignee_caught_up_streak(assignee_id):
            self.coordinator._persist_and_update()
        for goal_id, goal in list(self.goals.items()):
            # Only people assigned to a goal can move its total.
            if assignee_id in goal.get(fg.DATA_ASSIGNED_USER_IDS, []):
                await self._evaluate_goal(goal_id, goal)

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
        # build_goal copies progress by value; keep the live object.
        goal[fg.DATA_PROGRESS] = existing.get(fg.DATA_PROGRESS, {})
        self.coordinator._data[base.DATA_CHALLENGES][goal_id] = goal
        self.coordinator._persist(immediate=immediate_persist)
        self.coordinator.async_update_listeners()
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
            return float(
                self.coordinator.stats.get_period_total(
                    point_periods,
                    base.PERIOD_ALL_TIME,
                    base.DATA_USER_POINT_PERIOD_POINTS_EARNED,
                    period_key_mapping={
                        base.PERIOD_ALL_TIME: base.DATA_USER_POINT_PERIODS_ALL_TIME
                    },
                )
            )

        if goal_type == fg.GOAL_TYPE_DAY:
            return float(self._approved_today(assignee_id))

        # Chores goal: optionally scoped to one chore, otherwise all chores.
        selected = str(goal.get(fg.DATA_SELECTED_CHORE_ID, ""))
        if selected and selected not in _NO_CHORE:
            scoped = (
                self.coordinator.statistics_manager.get_badge_scoped_all_time_stats(
                    assignee_id, [selected]
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

    def _contribution(self, assignee_id: str, goal: dict[str, Any]) -> float:
        """Return one person's contribution since the goal was last restarted."""
        raw = self._raw_contribution(assignee_id, goal)
        if goal.get(fg.DATA_TYPE) == fg.GOAL_TYPE_DAY:
            # Already scoped to today; a restart baseline would zero tomorrow.
            return raw
        baseline = goal.get(fg.DATA_BASELINE, {})
        return max(0.0, raw - float(baseline.get(assignee_id, 0.0)))

    def get_contributions(self, goal_id: str) -> dict[str, float]:
        """Return each assigned person's contribution (read-only, for sensors)."""
        goal = self.goals.get(goal_id)
        if not goal or goal.get(fg.DATA_TYPE) in fg.STREAK_GOAL_TYPES:
            # Streak goals are a shared day count, not a sum of shares.
            return {}
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
        streak = assignee_info.get(base.DATA_USER_CAUGHT_UP_STREAK) or {}
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
            assignee_info[base.DATA_USER_CAUGHT_UP_STREAK] = {  # type: ignore[typeddict-unknown-key]
                "count": count,
                "last_day": last_day,
                "best": best,
            }
        return changed

    def get_caught_up_status(self, goal_id: str) -> dict[str, str]:
        """Return today's per-person caught-up progress as readable text.

        For sensors, so a dashboard can show who is holding the day up (for
        example "Lily: 2 still to do today, 1 done").
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
            names[assignee_id]: (
                f"{snap['open']} still to do today, {snap['done']} done"
                + (", overdue" if snap["overdue"] else "")
            )
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
        as a baseline, so only future activity counts. The streak goals clear
        their streak (today is not counted, tomorrow is day one). Everyone's
        award is cleared so the goal can be earned again; reward points already
        paid out are untouched.

        Raises:
            HomeAssistantError: The goal does not exist.
        """
        goal = self.goals.get(goal_id)
        if not goal:
            raise self._not_found(goal_id)

        if goal.get(fg.DATA_TYPE) in fg.STREAK_GOAL_TYPES:
            goal[fg.DATA_STREAK_COUNT] = 0
            goal[fg.DATA_STREAK_LAST_DAY] = dt_today_iso()
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

        base.LOGGER.info("Family goal %s restarted", goal_id)
        self.coordinator._persist_and_update()

    # ------------------------------------------------------------------
    # Evaluation and awarding
    # ------------------------------------------------------------------

    async def _evaluate_goal(self, goal_id: str, goal: dict[str, Any]) -> None:
        """Award a goal to everyone assigned once the pooled total is met.

        People who already hold the award are skipped, so this is safe to call
        repeatedly (it runs whenever any assigned person is re-evaluated).
        """
        levels = self._levels(goal)
        if not levels:
            return

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
            goal[fg.DATA_LEVEL_START] = self.get_contributions(goal_id)

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
                    level=reached if len(levels) > 1 else None,
                    reward=reward,
                    bonus_note=(f"(Top contributor x{multiplier:g})" if is_top else ""),
                    is_final=is_final,
                )

    def _award(
        self,
        assignee_id: str,
        goal_id: str,
        goal: dict[str, Any],
        *,
        level: int | None,
        reward: float,
        bonus_note: str,
        is_final: bool,
    ) -> None:
        """Mark one person's award and pay it through the challenge signal."""
        entry = goal.setdefault(fg.DATA_PROGRESS, {}).setdefault(assignee_id, {})
        entry[fg.DATA_AWARDED] = is_final
        entry[fg.PROGRESS_CURRENT_VALUE] = goal.get(fg.DATA_TARGET_VALUE, 1)

        name = str(goal.get(fg.DATA_NAME, ""))
        if level is not None:
            name = f"{name} - Level {level}"
        if bonus_note:
            name = f"{name} {bonus_note}"

        self.coordinator._persist_and_update()

        # EconomyManager deposits the points and NotificationManager notifies
        # the person and their approvers; both already listen for this signal.
        self.emit(
            base.SIGNAL_SUFFIX_CHALLENGE_COMPLETED,
            user_id=assignee_id,
            challenge_id=goal_id,
            user_name=eh.get_assignee_name_by_id(self.coordinator, assignee_id) or "",
            challenge_name=name,
            challenge_points=reward,
        )

    # ------------------------------------------------------------------
    # Overview (OpsCenter reset card)
    # ------------------------------------------------------------------

    def get_overview(self) -> list[dict[str, Any]]:
        """Return every goal as name/type/total/target for the OpsCenter card.

        Read straight from storage so the card does not depend on per-person
        entity lookups.
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
                    "target": round(float(goal.get(fg.DATA_TARGET_VALUE, 0) or 0), 2),
                }
            )
        overview.sort(key=lambda item: item["name"].lower())
        return overview
