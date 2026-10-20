"""Options-flow steps for Family Goals.

Mixed into the options flow handler. The menu entry, the select-a-goal step
and the add/edit/delete step ids are the ones the Challenges section already
uses, so the main options flow only needs to inherit this mixin.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from homeassistant.helpers import selector
import voluptuous as vol

from .. import const as base
from ..data_builders import EntityValidationError
from ..helpers import flow_helpers as fh
from . import builders, const as fg

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigFlowResult

DOC_URL: str = base.DOC_URL_ACHIEVEMENTS_OVERVIEW


def build_goal_schema(
    assignees_dict: dict[str, str], chores_dict: dict[str, Any]
) -> vol.Schema:
    """Build the add/edit form. Values come from suggested values, not defaults."""
    assignee_options = [
        {"value": assignee_id, "label": assignee_name}
        for assignee_name, assignee_id in assignees_dict.items()
    ]
    chore_options = [{"value": base.SENTINEL_EMPTY, "label": base.LABEL_NONE}]
    for chore_id, chore in chores_dict.items():
        chore_options.append(
            {
                "value": chore_id,
                "label": chore.get(base.DATA_CHORE_NAME, f"Chore {chore_id[:6]}"),
            }
        )

    return vol.Schema(
        {
            vol.Required(fg.DATA_NAME): str,
            vol.Optional(fg.DATA_DESCRIPTION, default=""): str,
            vol.Optional(fg.DATA_LABELS, default=[]): selector.LabelSelector(
                selector.LabelSelectorConfig(multiple=True)
            ),
            vol.Optional(fg.DATA_ICON): selector.IconSelector(),
            vol.Required(
                fg.DATA_ASSIGNED_USER_IDS, default=[]
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=cast("list[selector.SelectOptionDict]", assignee_options),
                    translation_key=base.TRANS_KEY_FLOW_HELPERS_ASSIGNED_USER_IDS,
                    multiple=True,
                )
            ),
            vol.Required(
                fg.DATA_TYPE, default=fg.GOAL_TYPE_CHORES
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=cast(
                        "list[selector.SelectOptionDict]", fg.GOAL_TYPE_OPTIONS
                    ),
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            # Total Chores Completed only: count one chore instead of all chores.
            vol.Optional(
                fg.DATA_SELECTED_CHORE_ID, default=base.SENTINEL_EMPTY
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=cast("list[selector.SelectOptionDict]", chore_options),
                    mode=selector.SelectSelectorMode.DROPDOWN,
                    multiple=False,
                )
            ),
            vol.Required(
                fg.DATA_TARGET_VALUE, default=fg.DEFAULT_TARGET
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    mode=selector.NumberSelectorMode.BOX, min=0, step=0.1
                )
            ),
            # Optional level targets, e.g. "100:10, 250:25, 500:50".
            vol.Optional(fg.DATA_LEVELS, default=""): str,
            # Reward multiplier for each level's top contributor (1 = off).
            vol.Optional(fg.DATA_TOP_MULTIPLIER, default=1): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    mode=selector.NumberSelectorMode.BOX, min=1, step=0.1
                )
            ),
            vol.Required(fg.DATA_REWARD_POINTS, default=0): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    mode=selector.NumberSelectorMode.BOX, min=0, step=0.01
                )
            ),
        }
    )


def _clean_goal_input(
    user_input: dict[str, Any], assignees_dict: dict[str, str]
) -> dict[str, Any]:
    """Return form input ready for the builders."""
    data = dict(user_input)
    data[fg.DATA_ASSIGNED_USER_IDS] = fh.normalize_selected_user_ids(
        data.get(fg.DATA_ASSIGNED_USER_IDS, []), assignees_dict
    )
    return data


class FamilyGoalsOptionsMixin:
    """Add / edit / delete steps for family goals."""

    # Provided by the options flow handler this is mixed into.
    context: dict[str, Any]

    def _goal_assignees(self) -> dict[str, str]:
        coordinator = self._get_coordinator()  # type: ignore[attr-defined]
        return {
            data[base.DATA_USER_NAME]: assignee_id
            for assignee_id, data in coordinator.assignees_data.items()
        }

    async def async_step_add_challenge(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add a family goal."""
        coordinator = self._get_coordinator()  # type: ignore[attr-defined]
        errors: dict[str, str] = {}
        assignees_dict = self._goal_assignees()

        if user_input is not None:
            data = _clean_goal_input(user_input, assignees_dict)
            errors = builders.validate_goal(data, coordinator.challenges_data)
            if not errors:
                try:
                    coordinator.family_goal_manager.create_goal(
                        data, immediate_persist=True
                    )
                    self._mark_reload_needed()  # type: ignore[attr-defined]
                    return await self.async_step_init()  # type: ignore[attr-defined,no-any-return]
                except EntityValidationError as err:
                    errors[err.field] = err.translation_key

        schema = build_goal_schema(assignees_dict, coordinator.chores_data)
        if user_input:
            schema = self.add_suggested_values_to_schema(  # type: ignore[attr-defined]
                schema, _clean_goal_input(user_input, assignees_dict)
            )
        return self.async_show_form(  # type: ignore[attr-defined,no-any-return]
            step_id=base.OPTIONS_FLOW_STEP_ADD_CHALLENGE,
            data_schema=schema,
            errors=errors,
            description_placeholders={base.PLACEHOLDER_DOCUMENTATION_URL: DOC_URL},
        )

    async def async_step_edit_challenge(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit a family goal. Its progress and streaks are kept."""
        coordinator = self._get_coordinator()  # type: ignore[attr-defined]
        errors: dict[str, str] = {}
        goals = coordinator.challenges_data
        goal_id = cast("str | None", self.context.get(base.DATA_INTERNAL_ID))
        if not goal_id or goal_id not in goals:
            base.LOGGER.error("Edit Family Goal - Invalid Internal ID '%s'", goal_id)
            return self.async_abort(reason="invalid_challenge")  # type: ignore[attr-defined,no-any-return]

        goal = goals[goal_id]
        assignees_dict = self._goal_assignees()

        if user_input is not None:
            data = _clean_goal_input(user_input, assignees_dict)
            others = {gid: g for gid, g in goals.items() if gid != goal_id}
            errors = builders.validate_goal(data, others, current_goal_id=goal_id)
            if not errors:
                try:
                    coordinator.family_goal_manager.update_goal(
                        goal_id, data, immediate_persist=True
                    )
                    self._mark_reload_needed()  # type: ignore[attr-defined]
                    return await self.async_step_init()  # type: ignore[attr-defined,no-any-return]
                except EntityValidationError as err:
                    errors[err.field] = err.translation_key

        valid_assignee_ids = set(assignees_dict.values())
        suggested: dict[str, Any] = {
            fg.DATA_NAME: goal.get(fg.DATA_NAME),
            fg.DATA_DESCRIPTION: goal.get(fg.DATA_DESCRIPTION),
            fg.DATA_LABELS: goal.get(fg.DATA_LABELS, []),
            fg.DATA_ICON: goal.get(fg.DATA_ICON),
            fg.DATA_ASSIGNED_USER_IDS: [
                a
                for a in fh.normalize_selected_user_ids(
                    goal.get(fg.DATA_ASSIGNED_USER_IDS, []), assignees_dict
                )
                if a in valid_assignee_ids
            ],
            fg.DATA_TYPE: goal.get(fg.DATA_TYPE, fg.GOAL_TYPE_CHORES),
            fg.DATA_SELECTED_CHORE_ID: goal.get(
                fg.DATA_SELECTED_CHORE_ID, base.SENTINEL_EMPTY
            ),
            fg.DATA_TARGET_VALUE: goal.get(fg.DATA_TARGET_VALUE, fg.DEFAULT_TARGET),
            fg.DATA_LEVELS: goal.get(fg.DATA_LEVELS, base.SENTINEL_EMPTY),
            fg.DATA_TOP_MULTIPLIER: goal.get(fg.DATA_TOP_MULTIPLIER, 1),
            fg.DATA_REWARD_POINTS: goal.get(fg.DATA_REWARD_POINTS, 0),
        }
        if user_input:
            suggested.update(_clean_goal_input(user_input, assignees_dict))
        if (
            suggested[fg.DATA_SELECTED_CHORE_ID] != base.SENTINEL_EMPTY
            and suggested[fg.DATA_SELECTED_CHORE_ID] not in coordinator.chores_data
        ):
            suggested[fg.DATA_SELECTED_CHORE_ID] = base.SENTINEL_EMPTY

        schema = build_goal_schema(assignees_dict, coordinator.chores_data)
        schema = self.add_suggested_values_to_schema(schema, suggested)  # type: ignore[attr-defined]
        return self.async_show_form(  # type: ignore[attr-defined,no-any-return]
            step_id=base.OPTIONS_FLOW_STEP_EDIT_CHALLENGE,
            data_schema=schema,
            errors=errors,
            description_placeholders={base.PLACEHOLDER_DOCUMENTATION_URL: DOC_URL},
        )

    async def async_step_delete_challenge(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Delete a family goal."""
        coordinator = self._get_coordinator()  # type: ignore[attr-defined]
        goals = coordinator.challenges_data
        goal_id = self.context.get(base.DATA_INTERNAL_ID)
        if not goal_id or goal_id not in goals:
            base.LOGGER.error("Delete Family Goal - Invalid Internal ID '%s'", goal_id)
            return self.async_abort(reason="invalid_challenge")  # type: ignore[attr-defined,no-any-return]

        goal_name = goals[goal_id][fg.DATA_NAME]
        if user_input is not None:
            coordinator.family_goal_manager.delete_goal(
                str(goal_id), immediate_persist=True
            )
            return await self.async_step_init()  # type: ignore[attr-defined,no-any-return]

        return self.async_show_form(  # type: ignore[attr-defined,no-any-return]
            step_id=base.OPTIONS_FLOW_STEP_DELETE_CHALLENGE,
            data_schema=vol.Schema({}),
            description_placeholders={"challenge_name": goal_name},
        )
