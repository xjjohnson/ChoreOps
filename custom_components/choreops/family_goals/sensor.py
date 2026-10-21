"""Sensors for Family Goals.

Attribute names match what the Home and OpsCenter cards already read, so the
dashboards keep working: ``family_total``, ``family_contributions`` and so on.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import PERCENTAGE

from .. import const as base
from ..entity import ChoreOpsCoordinatorEntity
from ..helpers.device_helpers import (
    create_assignee_device_info_from_coordinator,
    create_system_device_info,
)
from ..helpers.entity_helpers import (
    get_assignee_name_by_id,
    get_friendly_label,
    get_item_name_or_log_error,
    should_create_entity_for_user_assignee,
)
from . import const as fg

if TYPE_CHECKING:
    from ..coordinator import ChoreOpsConfigEntry, ChoreOpsDataCoordinator


def build_family_goal_sensors(
    coordinator: ChoreOpsDataCoordinator, entry: ChoreOpsConfigEntry
) -> list[SensorEntity]:
    """Return one system sensor per goal and one progress sensor per person."""
    entities: list[SensorEntity] = []
    for goal_id, goal in coordinator.challenges_data.items():
        name = get_item_name_or_log_error("family goal", goal_id, goal, fg.DATA_NAME)
        if not name:
            continue
        entities.append(FamilyGoalSensor(coordinator, entry, goal_id, name))
        for assignee_id in goal.get(fg.DATA_ASSIGNED_USER_IDS, []):
            assignee_name = get_assignee_name_by_id(coordinator, assignee_id)
            if not assignee_name or not should_create_entity_for_user_assignee(
                base.SENSOR_KC_UID_SUFFIX_CHALLENGE_PROGRESS_SENSOR,
                coordinator,
                assignee_id,
            ):
                continue
            entities.append(
                FamilyGoalProgressSensor(
                    coordinator, entry, assignee_id, assignee_name, goal_id, name
                )
            )
    return entities


def _percent(total: float, target: float) -> float:
    if target <= 0:
        return 0.0
    return min(100.0, round(total / target * 100, base.DATA_FLOAT_PRECISION))


class _FamilyGoalBase(ChoreOpsCoordinatorEntity, SensorEntity):
    """Shared state for the two goal sensors."""

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(
        self,
        coordinator: ChoreOpsDataCoordinator,
        entry: ChoreOpsConfigEntry,
        goal_id: str,
        goal_name: str,
    ) -> None:
        """Initialize the shared fields."""
        super().__init__(coordinator)
        self._entry = entry
        self._goal_id = goal_id
        self._goal_name = goal_name

    @property
    def _goal(self) -> dict[str, Any]:
        return cast(
            "dict[str, Any]", self.coordinator.challenges_data.get(self._goal_id, {})
        )

    @property
    def _manager(self) -> Any:
        return self.coordinator.family_goal_manager

    @property
    def native_value(self) -> float:
        """Return the pooled progress toward the current level, 0-100."""
        goal = self._goal
        target = float(self._manager.get_level_info(self._goal_id)["next_target"] or 0)
        if not target:
            target = float(goal.get(fg.DATA_TARGET_VALUE, 0) or 0)
        return _percent(float(self._manager.get_total(self._goal_id)), target)

    @property
    def icon(self) -> str | None:
        """Return the goal's custom icon, or None for the icons.json fallback."""
        return self._goal.get(fg.DATA_ICON) or None

    def _name_for(self, assignee_id: str) -> str:
        return get_assignee_name_by_id(self.coordinator, assignee_id) or assignee_id

    def _shared_attributes(self) -> dict[str, Any]:
        """Attributes both sensors show: the pooled picture of the goal."""
        goal = self._goal
        goal_type = goal.get(fg.DATA_TYPE)

        associated_chore = base.SENTINEL_EMPTY
        selected = goal.get(fg.DATA_SELECTED_CHORE_ID)
        chore = self.coordinator.chores_data.get(str(selected)) if selected else None
        if chore:
            associated_chore = chore.get(base.DATA_CHORE_NAME) or base.SENTINEL_EMPTY

        assigned_names = [
            name
            for assignee_id in goal.get(fg.DATA_ASSIGNED_USER_IDS, [])
            if (
                name := get_item_name_or_log_error(
                    "assignee",
                    assignee_id,
                    self.coordinator.assignees_data.get(assignee_id, {}),
                    base.DATA_USER_NAME,
                )
            )
        ]
        labels = [
            get_friendly_label(self.hass, label)
            for label in cast("list", goal.get(fg.DATA_LABELS, []))
        ]

        level_info = self._manager.get_level_info(self._goal_id)
        attributes: dict[str, Any] = {
            fg.ATTR_GOAL_NAME: self._goal_name,
            base.ATTR_DESCRIPTION: goal.get(fg.DATA_DESCRIPTION, base.SENTINEL_EMPTY),
            base.ATTR_ASSIGNED_USER_NAMES: assigned_names,
            base.ATTR_TYPE: goal_type,
            base.ATTR_ASSOCIATED_CHORE: associated_chore,
            base.ATTR_TARGET_VALUE: goal.get(fg.DATA_TARGET_VALUE),
            base.ATTR_REWARD_POINTS: goal.get(fg.DATA_REWARD_POINTS),
            base.ATTR_LABELS: labels,
            fg.ATTR_TOTAL: self._manager.get_total(self._goal_id),
            fg.ATTR_LEVEL: level_info["level"],
            fg.ATTR_LEVELS: level_info["levels"],
            fg.ATTR_NEXT_TARGET: level_info["next_target"],
            fg.ATTR_NEXT_REWARD: level_info["next_reward"],
            fg.ATTR_LEVEL_REWARDS: level_info["rewards"],
            fg.ATTR_TOP_MULTIPLIER: float(goal.get(fg.DATA_TOP_MULTIPLIER, 1.0)),
            fg.ATTR_LEVEL_CONTRIBUTIONS: {
                self._name_for(a_id): value
                for a_id, value in self._manager.get_level_contributions(
                    self._goal_id
                ).items()
            },
        }
        attributes.update(self._manager.get_day_record(self._goal_id))
        if goal_type == fg.GOAL_TYPE_CAUGHT_UP:
            attributes[fg.ATTR_CAUGHT_UP_TODAY] = self._manager.get_caught_up_status(
                self._goal_id
            )
        return attributes


class FamilyGoalSensor(_FamilyGoalBase):
    """System-level sensor for one family goal."""

    _attr_translation_key = base.TRANS_KEY_SENSOR_CHALLENGE_STATE_SENSOR

    def __init__(
        self,
        coordinator: ChoreOpsDataCoordinator,
        entry: ChoreOpsConfigEntry,
        goal_id: str,
        goal_name: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, goal_id, goal_name)
        self._attr_unique_id = (
            f"{entry.entry_id}_{goal_id}{base.SENSOR_KC_UID_SUFFIX_CHALLENGE_SENSOR}"
        )
        self._attr_translation_placeholders = {
            base.TRANS_KEY_SENSOR_ATTR_CHALLENGE_NAME: goal_name,
        }
        self._attr_device_info = create_system_device_info(entry)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the pooled picture plus each person's share."""
        attributes = {
            base.ATTR_PURPOSE: base.TRANS_KEY_PURPOSE_CHALLENGE,
            **self._shared_attributes(),
        }
        progress = self._goal.get(fg.DATA_PROGRESS, {})
        attributes[base.ATTR_USERS_EARNED] = [
            self._name_for(a_id)
            for a_id, data in progress.items()
            if data.get(fg.DATA_AWARDED, False)
        ]
        attributes[fg.ATTR_CONTRIBUTIONS] = {
            self._name_for(a_id): value
            for a_id, value in self._manager.get_contributions(self._goal_id).items()
        }
        return attributes


class FamilyGoalProgressSensor(_FamilyGoalBase):
    """One person's view of a family goal: the shared bar plus their own share."""

    _attr_translation_key = base.TRANS_KEY_SENSOR_CHALLENGE_PROGRESS_SENSOR

    def __init__(
        self,
        coordinator: ChoreOpsDataCoordinator,
        entry: ChoreOpsConfigEntry,
        assignee_id: str,
        assignee_name: str,
        goal_id: str,
        goal_name: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, goal_id, goal_name)
        self._assignee_id = assignee_id
        self._assignee_name = assignee_name
        self._attr_unique_id = (
            f"{entry.entry_id}_{assignee_id}_{goal_id}"
            f"{base.SENSOR_KC_UID_SUFFIX_CHALLENGE_PROGRESS_SENSOR}"
        )
        self._attr_translation_placeholders = {
            base.TRANS_KEY_SENSOR_ATTR_ASSIGNEE_NAME: assignee_name,
            base.TRANS_KEY_SENSOR_ATTR_CHALLENGE_NAME: goal_name,
        }
        self._attr_device_info = create_assignee_device_info_from_coordinator(
            coordinator, assignee_id, assignee_name, entry
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the shared picture plus this person's own share."""
        goal = self._goal
        if goal.get(fg.DATA_TYPE) in fg.STREAK_GOAL_TYPES:
            # Shared streak: everyone sees the same day count.
            raw_progress = self._manager.get_total(self._goal_id)
        else:
            raw_progress = self._manager.get_contributions(self._goal_id).get(
                self._assignee_id, base.DEFAULT_ZERO
            )
        awarded = bool(
            goal.get(fg.DATA_PROGRESS, {})
            .get(self._assignee_id, {})
            .get(fg.DATA_AWARDED, False)
        )
        return {
            base.ATTR_PURPOSE: base.TRANS_KEY_PURPOSE_CHALLENGE_PROGRESS,
            base.ATTR_USER_NAME: self._assignee_name,
            **self._shared_attributes(),
            base.ATTR_RAW_PROGRESS: raw_progress,
            base.ATTR_AWARDED: awarded,
        }
