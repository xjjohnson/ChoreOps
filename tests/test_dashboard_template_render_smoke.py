"""Minimal render smoke tests for dashboard templates."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

import jinja2
import yaml

from custom_components.choreops import const
from custom_components.choreops.helpers import (
    dashboard_builder as builder,
    dashboard_helpers as dh,
)

TEMPLATES_ROOT = Path("custom_components/choreops/dashboards/templates")


def _read_template(name: str) -> str:
    """Read a vendored dashboard template file."""
    return (TEMPLATES_ROOT / name).read_text(encoding="utf-8")


def test_user_template_renders_without_parse_errors() -> None:
    """User template renders and parses into a dashboard dict."""
    template_str = _read_template("user-chores-essential-v1.yaml")
    context = dh.build_dashboard_context(
        "Zoe",
        assignee_id="user-123",
        integration_entry_id="entry-123",
        template_profile="user-chores-essential-v1",
        release_ref="0.0.1-beta.3",
        generated_at="2026-03-02T00:00:00+00:00",
    )

    rendered = builder.render_dashboard_template(template_str, dict(context))

    assert isinstance(rendered.get("views"), list)
    assert len(rendered["views"]) == 1
    assert rendered["views"][0]["title"] == "Zoe"
    assert rendered["views"][0]["path"] == "zoe"
    assert isinstance(rendered["views"][0].get("sections"), list)


def test_user_chores_lite_template_renders_without_parse_errors() -> None:
    """Chores Lite template renders and parses into a dashboard dict."""
    template_str = _read_template("user-chores-lite-v1.yaml")
    context = dh.build_dashboard_context(
        "Zoe",
        assignee_id="user-123",
        integration_entry_id="entry-123",
        template_profile="user-chores-lite-v1",
        release_ref="0.0.1-beta.3",
        generated_at="2026-03-18T00:00:00+00:00",
    )

    rendered = builder.render_dashboard_template(template_str, dict(context))

    assert isinstance(rendered.get("views"), list)
    assert len(rendered["views"]) == 1
    assert rendered["views"][0]["title"] == "Zoe"
    assert rendered["views"][0]["path"] == "zoe"
    assert isinstance(rendered["views"][0].get("sections"), list)


def test_admin_template_renders_without_parse_errors() -> None:
    """Admin template renders and parses into a dashboard dict."""
    template_str = _read_template("admin-shared-family-hub-v1.yaml")
    context = dh.build_admin_dashboard_context(
        integration_entry_id="entry-123",
        template_profile="admin-shared-family-hub-v1",
        release_ref="0.0.1-beta.3",
        generated_at="2026-03-02T00:00:00+00:00",
    )

    rendered = builder.render_dashboard_template(template_str, context)

    assert isinstance(rendered.get("views"), list)
    assert len(rendered["views"]) == 1
    assert rendered["views"][0]["title"] == "Parents"
    assert rendered["views"][0]["path"] == "admin"
    assert isinstance(rendered["views"][0].get("sections"), list)


def test_admin_peruser_template_renders_without_parse_errors() -> None:
    """Per-user admin template renders and parses into a dashboard dict."""
    template_str = _read_template("admin-peruser-v1.yaml")
    context = dh.build_dashboard_context(
        "Alice",
        assignee_id="user-alice",
        integration_entry_id="entry-123",
        template_profile="admin-peruser-v1",
        release_ref="0.0.1-beta.3",
        generated_at="2026-03-02T00:00:00+00:00",
    )

    rendered = builder.render_dashboard_template(template_str, dict(context))

    assert isinstance(rendered.get("views"), list)
    assert len(rendered["views"]) == 1
    assert rendered["views"][0]["title"] == "Alice OpsCenter"
    assert rendered["views"][0]["path"] == "admin-alice"
    assert isinstance(rendered["views"][0].get("sections"), list)


def _get_admin_peruser_filter_template(marker: str) -> str:
    """Return one rendered per-user admin auto-entities inner template by marker."""

    template_str = _read_template("admin-peruser-v1.yaml")
    context = dh.build_dashboard_context(
        "Alice",
        assignee_id="user-alice",
        integration_entry_id="entry-123",
        template_profile="admin-peruser-v1",
        release_ref="0.0.1-beta.3",
        generated_at="2026-03-09T00:00:00+00:00",
    )
    rendered = builder.render_dashboard_template(template_str, dict(context))

    return next(
        card["filter"]["template"]
        for section in rendered["views"][0]["sections"]
        for card in section.get("cards", [])
        if isinstance(card, dict)
        and isinstance(card.get("filter"), dict)
        and marker in str(card["filter"].get("template", ""))
    )


def test_admin_peruser_management_omits_selector_controls() -> None:
    """Per-user management should not expose shared-selector controls."""

    management_template = _get_admin_peruser_filter_template("===== MANAGEMENT =====")

    assert "select.select_option" not in management_template
    assert "clear_selection" not in management_template


@dataclass
class _MockState:
    """Minimal Home Assistant-like state object for template rendering tests."""

    entity_id: str
    state: str
    attributes: dict[str, object]
    name: str


class _MockStatesProxy:
    """Home Assistant-like states helper supporting call and item access."""

    def __init__(self, mock_states: dict[str, _MockState]) -> None:
        """Initialize the proxy with known mock states."""
        self._mock_states = mock_states

    def __call__(self, entity_id: str) -> str:
        """Return one entity state string."""
        if entity_id in self._mock_states:
            return self._mock_states[entity_id].state
        return "unknown"

    def __getitem__(self, entity_id: str) -> _MockState:
        """Return one entity state object."""
        return self._mock_states[entity_id]


def _build_runtime_template_env(
    mock_states: dict[str, _MockState],
) -> tuple[
    jinja2.Environment,
    Any,
    _MockStatesProxy,
    Any,
]:
    """Build a minimal runtime Jinja environment for admin filter templates."""

    def integration_entities(_domain: str) -> list[str]:
        return list(mock_states)

    def expand_filter(values: list[object]) -> list[_MockState]:
        expanded_states: list[_MockState] = []
        for value in values:
            if isinstance(value, _MockState):
                expanded_states.append(value)
            elif isinstance(value, str) and value in mock_states:
                expanded_states.append(mock_states[value])
        return expanded_states

    states = _MockStatesProxy(mock_states)

    def state_attr(entity_id: str, attr_name: str) -> object | None:
        if entity_id in mock_states:
            return mock_states[entity_id].attributes.get(attr_name)
        return None

    def regex_replace_filter(value: object, pattern: str, replacement: str = "") -> str:
        """Mirror Home Assistant's regex_replace filter for runtime template tests."""
        return re.sub(pattern, replacement, str(value))

    def bool_filter(value: object, default: bool = False) -> bool:
        """Mirror Home Assistant's bool filter for runtime template tests."""
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            return value.lower() in ("true", "yes", "1", "on")
        return default

    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    env.filters["expand"] = expand_filter
    env.filters["bool"] = bool_filter
    env.filters["combine"] = lambda value, *others, **_kw: {
        **value,
        **{k: v for o in others for k, v in o.items()},
    }
    env.tests["search"] = lambda value, pattern: (
        __import__("re").search(pattern, value) is not None
    )
    env.filters["regex_replace"] = regex_replace_filter
    env.tests["match"] = lambda value, pattern: (
        __import__("re").match(pattern, value) is not None
    )
    return env, integration_entities, states, state_attr


def _get_admin_filter_template(template_profile: str, marker: str) -> str:
    """Return one rendered admin auto-entities inner template by marker."""

    template_str = _read_template("admin-shared-family-hub-v1.yaml")
    context = dh.build_admin_dashboard_context(
        integration_entry_id="entry-123",
        template_profile=template_profile,
        release_ref="0.0.1-beta.3",
        generated_at="2026-03-09T00:00:00+00:00",
    )
    rendered = builder.render_dashboard_template(template_str, context)

    return next(
        card["filter"]["template"]
        for section in rendered["views"][0]["sections"]
        for card in section.get("cards", [])
        if isinstance(card, dict)
        and isinstance(card.get("filter"), dict)
        and marker in str(card["filter"].get("template", ""))
    )


def _base_admin_chore_management_states(
    *,
    selected_user_name: str,
    selected_dashboard_helper: str,
    chore_selector_state: str,
    chore_items: list[dict[str, object]],
    chore_shard_items: list[list[dict[str, object]]] | None = None,
    selected_user_ui_control: dict[str, object] | None = None,
    shared_admin_ui_control: dict[str, object] | None = None,
    chore_sensor_state: str = "pending",
    chore_sensor_attributes: dict[str, object] | None = None,
    chore_select_options: list[str] | None = None,
) -> dict[str, _MockState]:
    """Build minimal states for the admin chore-management filter tests."""

    selected_user_ui_control = selected_user_ui_control or {}
    shared_admin_ui_control = shared_admin_ui_control or {}
    chore_sensor_attributes = chore_sensor_attributes or {}
    chore_shard_items = chore_shard_items or []
    chore_helper_eids = [
        f"sensor.alice_dashboard_chore_list_{index}"
        for index in range(1, len(chore_shard_items) + 1)
    ]
    mock_states = {
        "select.choreops_admin_target": _MockState(
            entity_id="select.choreops_admin_target",
            state=selected_user_name,
            attributes={
                "purpose": "purpose_system_dashboard_admin_user",
                "integration_entry_id": "entry-123",
                "dashboard_helper_eid": selected_dashboard_helper,
            },
            name="Admin Target",
        ),
        "sensor.shared_admin_dashboard_helper": _MockState(
            entity_id="sensor.shared_admin_dashboard_helper",
            state="available",
            attributes={
                "purpose": "purpose_system_dashboard_helper",
                "integration_entry_id": "entry-123",
                "dashboard_lookup_key": "entry-123:shared_admin",
                "ui_control": shared_admin_ui_control,
                "user_dashboard_helpers": {
                    "user-alice": selected_dashboard_helper,
                },
                "translation_sensor_eid": "sensor.translations",
            },
            name="Shared Admin Dashboard Helper",
        ),
        selected_dashboard_helper: _MockState(
            entity_id=selected_dashboard_helper,
            state="ok",
            attributes={
                "purpose": "purpose_dashboard_helper",
                "integration_entry_id": "entry-123",
                "dashboard_lookup_key": "entry-123:user-alice",
                "user_name": "Alice",
                "user_id": "user-alice",
                "ui_control": selected_user_ui_control,
                "dashboard_helpers": {
                    "translation_sensor_eid": "sensor.translations",
                    "chore_select_eid": "select.alice_chores",
                    "chore_helper_eids": chore_helper_eids,
                },
                "core_sensors": {},
                "chores": chore_items,
            },
            name="Alice Dashboard Helper",
        ),
        "select.alice_chores": _MockState(
            entity_id="select.alice_chores",
            state=chore_selector_state,
            attributes={
                "purpose": "purpose_select_user_chores",
                "user_name": "Alice",
                **(
                    {"options": chore_select_options}
                    if chore_select_options is not None
                    else {}
                ),
            },
            name="Alice Chores",
        ),
        "sensor.translations": _MockState(
            entity_id="sensor.translations",
            state="ok",
            attributes={
                "ui_translations": {
                    "chores": "Chores",
                    "choose_chore_for_admin_actions": (
                        "Choose the chore for admin actions below."
                    ),
                    "viewing_selected_chore": "Viewing selected chore",
                    "active": "Active",
                    "select_user_to_manage_chores_first": (
                        "Select a user before managing chores."
                    ),
                    "select_chore_to_manage": "Select chore to manage",
                    "none": "None",
                }
            },
            name="Translations",
        ),
    }

    for chore_helper_eid, shard_items in zip(
        chore_helper_eids, chore_shard_items, strict=False
    ):
        mock_states[chore_helper_eid] = _MockState(
            entity_id=chore_helper_eid,
            state="ok",
            attributes={"chores": shard_items},
            name=chore_helper_eid,
        )

    for chore_item in chore_items + [
        shard_chore_item
        for shard_group in chore_shard_items
        for shard_chore_item in shard_group
    ]:
        chore_entity_id = str(chore_item["eid"])
        mock_states[chore_entity_id] = _MockState(
            entity_id=chore_entity_id,
            state=chore_sensor_state,
            attributes={
                "icon": "mdi:broom",
                "default_points": 5,
                "approval_reset_type": "at_midnight_once",
                "completion_criteria": "independent",
                "recurring_frequency": "none",
                **chore_sensor_attributes,
            },
            name=str(chore_item["name"]),
        )

    return mock_states


def _base_admin_economy_management_states(
    *,
    selected_user_name: str,
    selected_dashboard_helper: str,
    gamification_enabled: bool,
    selected_user_ui_control: dict[str, object] | None = None,
    shared_admin_ui_control: dict[str, object] | None = None,
    point_buttons: list[dict[str, object]] | None = None,
    bonuses: list[dict[str, object]] | None = None,
    penalties: list[dict[str, object]] | None = None,
) -> dict[str, _MockState]:
    """Build minimal states for the admin economy-management filter tests."""

    selected_user_ui_control = selected_user_ui_control or {}
    shared_admin_ui_control = shared_admin_ui_control or {}
    point_buttons = point_buttons or []
    bonuses = bonuses or []
    penalties = penalties or []

    mock_states = {
        "select.choreops_admin_target": _MockState(
            entity_id="select.choreops_admin_target",
            state=selected_user_name,
            attributes={
                "purpose": "purpose_system_dashboard_admin_user",
                "integration_entry_id": "entry-123",
                "dashboard_helper_eid": selected_dashboard_helper,
            },
            name="Admin Target",
        ),
        "sensor.shared_admin_dashboard_helper": _MockState(
            entity_id="sensor.shared_admin_dashboard_helper",
            state="available",
            attributes={
                "purpose": "purpose_system_dashboard_helper",
                "integration_entry_id": "entry-123",
                "dashboard_lookup_key": "entry-123:shared_admin",
                "ui_control": shared_admin_ui_control,
                "user_dashboard_helpers": {
                    "user-alice": selected_dashboard_helper,
                },
                "translation_sensor_eid": "sensor.translations",
            },
            name="Shared Admin Dashboard Helper",
        ),
        selected_dashboard_helper: _MockState(
            entity_id=selected_dashboard_helper,
            state="ok",
            attributes={
                "purpose": "purpose_dashboard_helper",
                "integration_entry_id": "entry-123",
                "user_name": "Alice",
                "user_id": "user-alice",
                "gamification_enabled": gamification_enabled,
                "ui_control": selected_user_ui_control,
                "dashboard_helpers": {
                    "translation_sensor_eid": "sensor.translations",
                },
                "core_sensors": {
                    "points_eid": "sensor.alice_points",
                },
                "points_buttons": point_buttons,
                "bonuses": bonuses,
                "penalties": penalties,
            },
            name="Alice Dashboard Helper",
        ),
        "sensor.alice_points": _MockState(
            entity_id="sensor.alice_points",
            state="231",
            attributes={
                "icon": "mdi:star-circle",
                "unit_of_measurement": "Points",
                "points_multiplier": 1.1,
                "point_stat_points_earned_week": 233,
                "point_stat_avg_points_per_day_week": 33,
            },
            name="Alice Points",
        ),
        "sensor.translations": _MockState(
            entity_id="sensor.translations",
            state="ok",
            attributes={
                "ui_translations": {
                    "points_details": "Points Details",
                    "manage_manual_adjustments": "Manage manual adjustments",
                    "viewing_selected_user": "Viewing selected user",
                    "available": "Available",
                    "active": "Active",
                    "this_week": "This Week",
                    "points_per_day": "Points / Day",
                    "weekly_performance": "Weekly Performance",
                    "bonus": "Bonus",
                    "penalty": "Penalty",
                    "applied": "Applied",
                    "none": "None",
                    "clear_applied": "Clear applied",
                }
            },
            name="Translations",
        ),
    }

    for point_button in point_buttons:
        button_eid = str(point_button["eid"])
        mock_states[button_eid] = _MockState(
            entity_id=button_eid,
            state="unknown",
            attributes={
                "icon": str(point_button.get("icon", "mdi:plus-circle-outline")),
            },
            name=str(point_button.get("name", "Points +1")),
        )

    for bonus in bonuses:
        bonus_eid = str(bonus["eid"])
        mock_states[bonus_eid] = _MockState(
            entity_id=bonus_eid,
            state="unknown",
            attributes={
                "icon": str(bonus.get("icon", "mdi:gift-outline")),
            },
            name=str(bonus.get("name", "Bonus")),
        )

    for penalty in penalties:
        penalty_eid = str(penalty["eid"])
        mock_states[penalty_eid] = _MockState(
            entity_id=penalty_eid,
            state="unknown",
            attributes={
                "icon": str(penalty.get("icon", "mdi:alert-octagon-outline")),
            },
            name=str(penalty.get("name", "Penalty")),
        )

    return mock_states


def _base_admin_system_administration_states() -> dict[str, _MockState]:
    """Build minimal states for the admin system-administration filter tests."""

    return {
        "select.choreops_admin_target": _MockState(
            entity_id="select.choreops_admin_target",
            state="Alice",
            attributes={
                "purpose": "purpose_system_dashboard_admin_user",
                "integration_entry_id": "entry-123",
                "dashboard_helper_eid": "",
            },
            name="Admin Target",
        ),
        "sensor.shared_admin_dashboard_helper": _MockState(
            entity_id="sensor.shared_admin_dashboard_helper",
            state="available",
            attributes={
                "purpose": "purpose_system_dashboard_helper",
                "integration_entry_id": "entry-123",
                "dashboard_lookup_key": "entry-123:shared_admin",
                "ui_control": {"admin-shared": {"management-tab": "system"}},
                "user_dashboard_helpers": {
                    "user-alice": "sensor.alice_dashboard_helper",
                },
                "translation_sensor_eid": "sensor.translations",
            },
            name="Shared Admin Dashboard Helper",
        ),
        "sensor.alice_dashboard_helper": _MockState(
            entity_id="sensor.alice_dashboard_helper",
            state="ok",
            attributes={
                "purpose": "purpose_dashboard_helper",
                "integration_entry_id": "entry-123",
                "user_name": "Alice",
                "user_id": "user-alice",
                "dashboard_helpers": {
                    "translation_sensor_eid": "sensor.translations",
                },
                "core_sensors": {},
            },
            name="Alice Dashboard Helper",
        ),
        "sensor.translations": _MockState(
            entity_id="sensor.translations",
            state="ok",
            attributes={
                "ui_translations": {
                    "system_administration": "System Administration",
                    "link_to_choreops_integration_configuration": "Open ChoreOps settings.",
                    "documentation_and_help": "Documentation & Help",
                    "documentation_and_help_description": (
                        "Wiki setup and advanced guides."
                    ),
                    "support_the_project": "Support the project",
                    "support_the_project_description": (
                        "Help fund support and the next release."
                    ),
                }
            },
            name="Translations",
        ),
    }


def test_admin_target_selector_template_renders_as_valid_cards() -> None:
    """Shared admin target selector inner template renders valid card configs."""
    template_str = _read_template("admin-shared-family-hub-v1.yaml")
    context = dh.build_admin_dashboard_context(
        integration_entry_id="entry-123",
        template_profile="admin-shared-family-hub-v1",
        release_ref="0.0.1-beta.3",
        generated_at="2026-03-09T00:00:00+00:00",
    )

    rendered = builder.render_dashboard_template(template_str, context)
    selector_template = next(
        card["filter"]["template"]
        for section in rendered["views"][0]["sections"]
        for card in section.get("cards", [])
        if isinstance(card, dict)
        and isinstance(card.get("filter"), dict)
        and "select.select_option" in str(card["filter"].get("template", ""))
    )

    mock_states = {
        "select.choreops_admin_target": _MockState(
            entity_id="select.choreops_admin_target",
            state="Alice",
            attributes={
                "purpose": "purpose_system_dashboard_admin_user",
                "integration_entry_id": "entry-123",
                "dashboard_helper_eid": "sensor.alice_dashboard_helper",
            },
            name="Admin Target",
        ),
        "sensor.shared_admin_dashboard_helper": _MockState(
            entity_id="sensor.shared_admin_dashboard_helper",
            state="available",
            attributes={
                "purpose": "purpose_system_dashboard_helper",
                "integration_entry_id": "entry-123",
                "dashboard_lookup_key": "entry-123:shared_admin",
                "ui_control": {},
                "user_dashboard_helpers": {
                    "user-alice": "sensor.alice_dashboard_helper",
                    "user-bob": "sensor.bob_dashboard_helper",
                },
                "translation_sensor_eid": "sensor.translations",
            },
            name="Shared Admin Dashboard Helper",
        ),
        "sensor.alice_dashboard_helper": _MockState(
            entity_id="sensor.alice_dashboard_helper",
            state="ok",
            attributes={
                "purpose": "purpose_dashboard_helper",
                "integration_entry_id": "entry-123",
                "user_name": "Alice",
                "ui_control": {},
                "dashboard_helpers": {"translation_sensor_eid": "sensor.translations"},
            },
            name="Alice Dashboard Helper",
        ),
        "sensor.bob_dashboard_helper": _MockState(
            entity_id="sensor.bob_dashboard_helper",
            state="ok",
            attributes={
                "purpose": "purpose_dashboard_helper",
                "integration_entry_id": "entry-123",
                "user_name": "Bob",
                "ui_control": {},
                "dashboard_helpers": {"translation_sensor_eid": "sensor.translations"},
            },
            name="Bob Dashboard Helper",
        ),
        "sensor.translations": _MockState(
            entity_id="sensor.translations",
            state="ok",
            attributes={
                "ui_translations": {
                    "none": "None",
                    "admin_target": "Admin target",
                    "choose_user_for_admin_actions": (
                        "Choose the user for admin actions below."
                    ),
                    "current_review_target": "Current review target",
                }
            },
            name="Translations",
        ),
    }

    env, integration_entities, states, state_attr = _build_runtime_template_env(
        mock_states
    )

    output = env.from_string(selector_template).render(
        integration_entities=integration_entities,
        states=states,
        state_attr=state_attr,
    )

    parsed = yaml.safe_load(f"[{output}]")

    assert isinstance(parsed, list)
    assert len(parsed) == 3
    assert parsed[0]["type"] == "custom:button-card"
    assert parsed[0]["entity"] == "select.choreops_admin_target"
    assert parsed[0]["tap_action"]["action"] == "call-service"
    assert parsed[0]["tap_action"]["service"] == "choreops.manage_ui_control"
    assert parsed[0]["tap_action"]["data"] == {
        "config_entry_id": "entry-123",
        "ui_control_target": "shared_admin",
        "ui_control_action": "update",
        "key": "admin-shared/admin-target-selector/header-collapse",
        "value": True,
    }
    assert parsed[0]["hold_action"]["action"] == "more-info"
    assert "Alice" in parsed[0]["custom_fields"]["target"]


def test_admin_target_selector_template_shows_guidance_without_selection() -> None:
    """Shared admin target selector shows chooser guidance when no user is selected."""
    template_str = _read_template("admin-shared-family-hub-v1.yaml")
    context = dh.build_admin_dashboard_context(
        integration_entry_id="entry-123",
        template_profile="admin-shared-family-hub-v1",
        release_ref="0.0.1-beta.3",
        generated_at="2026-03-09T00:00:00+00:00",
    )

    rendered = builder.render_dashboard_template(template_str, context)
    selector_template = next(
        card["filter"]["template"]
        for section in rendered["views"][0]["sections"]
        for card in section.get("cards", [])
        if isinstance(card, dict)
        and isinstance(card.get("filter"), dict)
        and "select.select_option" in str(card["filter"].get("template", ""))
    )

    mock_states = {
        "select.choreops_admin_target": _MockState(
            entity_id="select.choreops_admin_target",
            state="None",
            attributes={
                "purpose": "purpose_system_dashboard_admin_user",
                "integration_entry_id": "entry-123",
                "dashboard_helper_eid": "",
            },
            name="Admin Target",
        ),
        "sensor.shared_admin_dashboard_helper": _MockState(
            entity_id="sensor.shared_admin_dashboard_helper",
            state="available",
            attributes={
                "purpose": "purpose_system_dashboard_helper",
                "integration_entry_id": "entry-123",
                "dashboard_lookup_key": "entry-123:shared_admin",
                "ui_control": {},
                "user_dashboard_helpers": {
                    "user-alice": "sensor.alice_dashboard_helper",
                },
                "translation_sensor_eid": "sensor.translations",
            },
            name="Shared Admin Dashboard Helper",
        ),
        "sensor.alice_dashboard_helper": _MockState(
            entity_id="sensor.alice_dashboard_helper",
            state="ok",
            attributes={
                "purpose": "purpose_dashboard_helper",
                "integration_entry_id": "entry-123",
                "user_name": "Alice",
                "ui_control": {},
                "dashboard_helpers": {"translation_sensor_eid": "sensor.translations"},
            },
            name="Alice Dashboard Helper",
        ),
        "sensor.translations": _MockState(
            entity_id="sensor.translations",
            state="ok",
            attributes={
                "ui_translations": {
                    "none": "None",
                    "admin_target": "Admin target",
                    "choose_user_for_admin_actions": (
                        "Choose the user for admin actions below."
                    ),
                    "current_review_target": "Current review target",
                    "selected_user": "Selected user",
                }
            },
            name="Translations",
        ),
    }

    env, integration_entities, states, state_attr = _build_runtime_template_env(
        mock_states
    )

    output = env.from_string(selector_template).render(
        integration_entities=integration_entities,
        states=states,
        state_attr=state_attr,
    )

    parsed = yaml.safe_load(f"[{output}]")

    assert isinstance(parsed, list)
    assert len(parsed) == 2
    assert parsed[0]["type"] == "custom:button-card"
    assert parsed[0]["entity"] == "select.choreops_admin_target"
    assert parsed[0]["label"] == "Choose the user for admin actions below."
    assert parsed[0]["tap_action"]["action"] == "call-service"
    assert parsed[0]["tap_action"]["service"] == "choreops.manage_ui_control"
    assert parsed[0]["tap_action"]["data"] == {
        "config_entry_id": "entry-123",
        "ui_control_target": "shared_admin",
        "ui_control_action": "update",
        "key": "admin-shared/admin-target-selector/header-collapse",
        "value": True,
    }
    assert parsed[0]["hold_action"]["action"] == "more-info"


def test_admin_chore_management_hides_without_selected_user() -> None:
    """Shared admin chore management renders nothing when no user is selected."""

    chores_template = _get_admin_filter_template(
        "admin-shared-family-hub-v1", "===== CHORE MANAGEMENT ====="
    )
    mock_states = {
        "select.choreops_admin_target": _MockState(
            entity_id="select.choreops_admin_target",
            state="None",
            attributes={
                "purpose": "purpose_system_dashboard_admin_user",
                "integration_entry_id": "entry-123",
                "dashboard_helper_eid": "",
            },
            name="Admin Target",
        ),
        "sensor.shared_admin_dashboard_helper": _MockState(
            entity_id="sensor.shared_admin_dashboard_helper",
            state="available",
            attributes={
                "purpose": "purpose_system_dashboard_helper",
                "integration_entry_id": "entry-123",
                "dashboard_lookup_key": "entry-123:shared_admin",
                "ui_control": {},
                "user_dashboard_helpers": {
                    "user-alice": "sensor.alice_dashboard_helper",
                },
                "translation_sensor_eid": "sensor.translations",
            },
            name="Shared Admin Dashboard Helper",
        ),
        "sensor.alice_dashboard_helper": _MockState(
            entity_id="sensor.alice_dashboard_helper",
            state="ok",
            attributes={
                "purpose": "purpose_dashboard_helper",
                "integration_entry_id": "entry-123",
                "user_name": "Alice",
                "user_id": "user-alice",
                "ui_control": {},
                "dashboard_helpers": {
                    "translation_sensor_eid": "sensor.translations",
                    "chore_select_eid": "select.alice_chores",
                },
                "core_sensors": {},
                "chores": [],
            },
            name="Alice Dashboard Helper",
        ),
        "sensor.translations": _MockState(
            entity_id="sensor.translations",
            state="ok",
            attributes={"ui_translations": {"chores": "Chores"}},
            name="Translations",
        ),
    }
    env, integration_entities, states, state_attr = _build_runtime_template_env(
        mock_states
    )

    output = env.from_string(chores_template).render(
        integration_entities=integration_entities,
        states=states,
        state_attr=state_attr,
    )

    assert output.strip() == ""


def test_admin_chore_management_shows_selector_when_expanded() -> None:
    """With nothing picked, chores appear as tappable chips instead of a dropdown."""

    chores_template = _get_admin_filter_template(
        "admin-shared-family-hub-v1", "===== CHORE MANAGEMENT ====="
    )
    mock_states = _base_admin_chore_management_states(
        selected_user_name="Alice",
        selected_dashboard_helper="sensor.alice_dashboard_helper",
        chore_selector_state="None",
        chore_items=[
            {
                "name": "Wash Dishes",
                "eid": "sensor.alice_chore_wash_dishes",
                "state": "overdue",
            },
            {"name": "Feed Dog", "eid": "sensor.alice_chore_dog", "state": "pending"},
        ],
        selected_user_ui_control={
            "admin-shared": {"chore-management": {"header-collapse": False}}
        },
        chore_select_options=[
            "None",
            "Feed Dog (Alice)",
            "Wash Dishes (Alice)",
            "──────────",
            "⊘ Laundry",
        ],
    )
    env, integration_entities, states, state_attr = _build_runtime_template_env(
        mock_states
    )
    env.filters["timestamp_custom"] = lambda v, f="", local=True: str(v)
    env.globals["as_timestamp"] = lambda v: 0

    output = env.from_string(chores_template).render(
        integration_entities=integration_entities,
        states=states,
        state_attr=state_attr,
    )
    parsed = yaml.safe_load(f"[{output}]")

    assert len(parsed) == 1
    assert parsed[0]["type"] == "vertical-stack"
    grid = parsed[0]["cards"][1]
    assert grid["type"] == "grid" and grid["columns"] == 2
    names = [c["name"] for c in grid["cards"]]
    assert names == ["Feed Dog", "Wash Dishes", "⊘ Laundry"]
    tap = grid["cards"][1]["tap_action"]
    assert tap["service"] == "select.select_option"
    assert tap["data"] == {
        "entity_id": "select.alice_chores",
        "option": "Wash Dishes (Alice)",
    }
    assert (
        "Overdue" in grid["cards"][1]["label"] or "overdue" in grid["cards"][1]["label"]
    )
    assert (
        "err-" not in grid["cards"][2]["label"]
        or "Not assigned" in grid["cards"][2]["label"]
    )


def _render_chore_management(selected: str, options: list[str], items, state="pending"):
    template = _get_admin_filter_template(
        "admin-shared-family-hub-v1", "===== CHORE MANAGEMENT ====="
    )
    mock_states = _base_admin_chore_management_states(
        selected_user_name="Alice",
        selected_dashboard_helper="sensor.alice_dashboard_helper",
        chore_selector_state=selected,
        chore_items=items,
        chore_sensor_state=state,
        selected_user_ui_control={
            "admin-shared": {"chore-management": {"header-collapse": False}}
        },
        chore_select_options=options,
    )
    env, integration_entities, states, state_attr = _build_runtime_template_env(
        mock_states
    )
    env.filters["timestamp_custom"] = lambda v, f="", local=True: str(v)
    env.globals["as_timestamp"] = lambda v: 0
    output = env.from_string(template).render(
        integration_entities=integration_entities,
        states=states,
        state_attr=state_attr,
    )
    return yaml.safe_load(f"[{output}]")


def test_admin_chore_names_with_parentheses_still_resolve() -> None:
    """A chore called "Evening tidy-up (10 min)" keeps its own parentheses and
    only the trailing list of user names is treated as the assignee suffix."""

    items = [
        {
            "name": "Evening tidy-up (10 min)",
            "eid": "sensor.alice_chore_eve",
            "state": "pending",
        },
        {
            "name": "Plain (10 min)",
            "eid": "sensor.alice_chore_plain",
            "state": "overdue",
        },
    ]
    options = [
        "None",
        "Evening tidy-up (10 min) (Alice)",
        "Plain (10 min)",
    ]
    picker = _render_chore_management("None", options, items)
    chips = picker[0]["cards"][1]["cards"]
    assert [c["name"] for c in chips] == ["Evening tidy-up (10 min)", "Plain (10 min)"]
    assert all(c["label"].strip() for c in chips)
    assert (
        chips[0]["tap_action"]["data"]["option"] == "Evening tidy-up (10 min) (Alice)"
    )

    detail = _render_chore_management(
        "Evening tidy-up (10 min) (Alice)", options, items
    )
    overview = detail[0]["custom_fields"]["overview"]["card"]
    assert overview["entity"] == "sensor.alice_chore_eve"
    assert overview["name"] == "Evening tidy-up (10 min)"
    assert detail[0]["name"] == "Viewing selected chore"


def test_admin_unassigned_chore_explains_why_there_are_no_details() -> None:
    """Picking a chore that is not assigned to the person says so."""

    items = [{"name": "Feed Dog", "eid": "sensor.alice_chore_dog", "state": "pending"}]
    unassigned = _render_chore_management(
        "⊘ Mow lawn", ["None", "Feed Dog (Alice)", "⊘ Mow lawn"], items
    )
    assert unassigned[0]["name"] == "Mow lawn"
    assert "Not assigned to Alice" in unassigned[0]["label"]


def test_admin_chore_picker_caps_chips_and_offers_show_all() -> None:
    """Long chore lists show eight chips plus a Show all chip."""

    chores_template = _get_admin_filter_template(
        "admin-shared-family-hub-v1", "===== CHORE MANAGEMENT ====="
    )
    options = ["None"] + [f"Chore {i} (Alice)" for i in range(10)]
    mock_states = _base_admin_chore_management_states(
        selected_user_name="Alice",
        selected_dashboard_helper="sensor.alice_dashboard_helper",
        chore_selector_state="None",
        chore_items=[],
        selected_user_ui_control={
            "admin-shared": {"chore-management": {"header-collapse": False}}
        },
        chore_select_options=options,
    )
    env, integration_entities, states, state_attr = _build_runtime_template_env(
        mock_states
    )
    env.filters["timestamp_custom"] = lambda v, f="", local=True: str(v)
    env.globals["as_timestamp"] = lambda v: 0
    output = env.from_string(chores_template).render(
        integration_entities=integration_entities,
        states=states,
        state_attr=state_attr,
    )
    cards = yaml.safe_load(f"[{output}]")[0]["cards"][1]["cards"]
    assert len(cards) == 9
    assert cards[-1]["name"] == "Show all 10"
    assert cards[-1]["tap_action"]["data"]["key"] == (
        "admin-shared/quick-actions/picker-all"
    )


def test_admin_all_chores_card_only_shows_when_tile_opens_it() -> None:
    """The All chores card appears only after its Quick actions tile is toggled."""

    chores_template = _get_admin_filter_template(
        "admin-shared-family-hub-v1", "===== CHORE MANAGEMENT ====="
    )
    mock_states = _base_admin_chore_management_states(
        selected_user_name="Alice",
        selected_dashboard_helper="sensor.alice_dashboard_helper",
        chore_selector_state="None",
        chore_items=[
            {
                "name": "Wash Dishes",
                "eid": "sensor.alice_chore_wash",
                "state": "pending",
            }
        ],
        selected_user_ui_control={
            "admin-shared": {"chore-management": {"header-collapse": False}}
        },
        shared_admin_ui_control={
            "admin-shared": {
                "management-tab": "chores",
                "quick-actions": {"allchores-open": True},
            }
        },
    )
    env, integration_entities, states, state_attr = _build_runtime_template_env(
        mock_states
    )
    output = env.from_string(chores_template).render(
        integration_entities=integration_entities,
        states=states,
        state_attr=state_attr,
    )
    parsed = yaml.safe_load(f"[{output}]")
    assert len(parsed) == 2
    assert parsed[0]["name"] == "err-all_chores"
    close = parsed[0]["tap_action"]["data"]
    assert close["key"] == "admin-shared/quick-actions/allchores-open"
    assert close["value"] is False


def test_admin_chore_management_shows_detail_for_selected_chore() -> None:
    """Expanded shared admin chore management shows detail after chore selection."""

    chores_template = _get_admin_filter_template(
        "admin-shared-family-hub-v1", "===== CHORE MANAGEMENT ====="
    )
    mock_states = _base_admin_chore_management_states(
        selected_user_name="Alice",
        selected_dashboard_helper="sensor.alice_dashboard_helper",
        chore_selector_state="Wash Dishes",
        chore_items=[
            {
                "name": "Wash Dishes",
                "eid": "sensor.alice_chore_wash_dishes",
                "state": "pending",
            }
        ],
        selected_user_ui_control={
            "admin-shared": {"chore-management": {"header-collapse": False}}
        },
    )
    env, integration_entities, states, state_attr = _build_runtime_template_env(
        mock_states
    )

    output = env.from_string(chores_template).render(
        integration_entities=integration_entities,
        states=states,
        state_attr=state_attr,
    )
    parsed = yaml.safe_load(f"[{output}]")

    assert isinstance(parsed, list)
    assert len(parsed) == 1
    # Overview card is nested inside the chore select card's custom_fields
    assert parsed[0]["type"] == "custom:button-card"
    overview = parsed[0].get("custom_fields", {}).get("overview", {}).get("card")
    assert overview is not None
    assert overview.get("entity") == "sensor.alice_chore_wash_dishes"
    assert overview.get("name") == "Wash Dishes"
    change = parsed[0]["custom_fields"]["entity_select"]["card"]
    assert change["name"] == "Change chore"
    assert change["tap_action"]["service"] == "select.select_option"
    assert change["tap_action"]["data"]["option"] == "None"


def test_admin_chore_management_resolves_selected_shard_backed_chore() -> None:
    """Shared admin chore management resolves selected chores from shard helpers."""

    chores_template = _get_admin_filter_template(
        "admin-shared-family-hub-v1", "===== CHORE MANAGEMENT ====="
    )
    mock_states = _base_admin_chore_management_states(
        selected_user_name="Alice",
        selected_dashboard_helper="sensor.alice_dashboard_helper",
        chore_selector_state="Wash Dishes",
        chore_items=[],
        chore_shard_items=[
            [
                {
                    "name": "Wash Dishes",
                    "eid": "sensor.alice_chore_wash_dishes",
                    "state": "pending",
                }
            ]
        ],
        selected_user_ui_control={
            "admin-shared": {"chore-management": {"header-collapse": False}}
        },
    )
    env, integration_entities, states, state_attr = _build_runtime_template_env(
        mock_states
    )

    output = env.from_string(chores_template).render(
        integration_entities=integration_entities,
        states=states,
        state_attr=state_attr,
    )
    parsed = yaml.safe_load(f"[{output}]")

    assert isinstance(parsed, list)
    assert len(parsed) == 1
    assert parsed[0]["type"] == "custom:button-card"
    # Overview card is nested inside the chore select card's custom_fields
    overview = parsed[0].get("custom_fields", {}).get("overview", {}).get("card")
    assert overview is not None
    assert overview.get("entity") == "sensor.alice_chore_wash_dishes"
    assert overview.get("name") == "Wash Dishes"


def test_admin_peruser_chore_management_resolves_selected_shard_backed_chore() -> None:
    """Per-user admin chore management resolves selected chores from shard helpers."""

    chores_template = _get_admin_peruser_filter_template("===== CHORE MANAGEMENT =====")
    mock_states = _base_admin_chore_management_states(
        selected_user_name="Alice",
        selected_dashboard_helper="sensor.alice_dashboard_helper",
        chore_selector_state="Wash Dishes",
        chore_items=[],
        chore_shard_items=[
            [
                {
                    "name": "Wash Dishes",
                    "eid": "sensor.alice_chore_wash_dishes",
                    "state": "pending",
                }
            ]
        ],
        selected_user_ui_control={
            "admin-peruser": {"chore-management": {"header-collapse": False}}
        },
    )
    env, integration_entities, states, state_attr = _build_runtime_template_env(
        mock_states
    )

    output = env.from_string(chores_template).render(
        integration_entities=integration_entities,
        states=states,
        state_attr=state_attr,
    )
    parsed = yaml.safe_load(f"[{output}]")

    assert isinstance(parsed, list)
    assert len(parsed) == 3
    assert parsed[2]["type"] == "custom:button-card"
    # Overview card is nested inside the chore select card's custom_fields
    overview = parsed[2].get("custom_fields", {}).get("overview", {}).get("card")
    assert overview is not None
    assert overview.get("entity") == "sensor.alice_chore_wash_dishes"
    assert overview.get("name") == "Wash Dishes"


def test_user_chores_template_renders_with_button_card_templates() -> None:
    """User chores template renders as full dashboard with root templates."""
    template_str = _read_template("user-chores-standard-v1.yaml")
    chore_engine_context = _read_template("shared/chore_engine/context_v1.yaml")
    chore_engine_prepare_groups = _read_template(
        "shared/chore_engine/prepare_groups_v1.yaml"
    )
    chore_engine_header = _read_template("shared/chore_engine/header_v1.yaml")
    chore_engine_settings = _read_template("shared/chore_engine/settings_panel_v1.yaml")
    chore_engine_group_render = _read_template(
        "shared/chore_engine/group_render_v1.yaml"
    )
    standard_row_template_str = _read_template(
        "shared/button_card_template_chore_row_v1.yaml"
    )
    kids_row_template_str = _read_template(
        "shared/button_card_template_chore_row_kids_v1.yaml"
    )
    template_str = dh.compile_prepared_template_assets(
        {
            "templates/user-chores-standard-v1.yaml": template_str,
            "templates/shared/chore_engine/context_v1.yaml": chore_engine_context,
            "templates/shared/chore_engine/prepare_groups_v1.yaml": (
                chore_engine_prepare_groups
            ),
            "templates/shared/chore_engine/header_v1.yaml": chore_engine_header,
            "templates/shared/chore_engine/settings_panel_v1.yaml": (
                chore_engine_settings
            ),
            "templates/shared/chore_engine/group_render_v1.yaml": (
                chore_engine_group_render
            ),
            "templates/shared/button_card_template_chore_row_v1.yaml": (
                standard_row_template_str
            ),
            "templates/shared/button_card_template_chore_row_kids_v1.yaml": (
                kids_row_template_str
            ),
        }
    )["templates/user-chores-standard-v1.yaml"]
    context = dh.build_dashboard_context(
        "Zoe",
        assignee_id="user-123",
        integration_entry_id="entry-123",
        template_profile="user-chores-standard-v1",
        release_ref="0.0.1-beta.3",
        generated_at="2026-03-02T00:00:00+00:00",
    )

    rendered = builder.render_dashboard_template(template_str, dict(context))

    assert isinstance(rendered.get("views"), list)
    assert len(rendered["views"]) == 1
    assert rendered["views"][0]["title"] == "Zoe"
    assert rendered["views"][0]["path"] == "zoe"
    assert isinstance(rendered["views"][0].get("sections"), list)
    assert isinstance(rendered.get("button_card_templates"), dict)
    assert "chore_row_v1" in rendered["button_card_templates"]
    assert "chore_row_kids_v1" in rendered["button_card_templates"]


def test_user_chores_template_contains_ui_control_contract() -> None:
    """User chores template should reference the reviewed UI control contract."""
    template_str = _read_template("user-chores-standard-v1.yaml")

    assert "template_shared.chore_engine/context_v1" in template_str
    assert "template_shared.chore_engine/prepare_groups_v1" in template_str
    assert "template_shared.chore_engine/header_v1" in template_str
    assert "template_shared.chore_engine/settings_panel_v1" in template_str
    assert "template_shared.chore_engine/group_render_v1" in template_str
    assert "pref_ui_control_key_root = 'chores'" in template_str


def test_shared_chore_engine_fragment_contains_ui_control_contract() -> None:
    """Shared chores engine fragment should reference the reviewed UI control contract."""
    template_str = _read_template("shared/chore_engine/context_v1.yaml")

    assert "state_attr(dashboard_helper, 'ui_control')" in template_str
    assert "ui_control_key_root = pref_ui_control_key_root" in template_str
    assert "'/header_collapse'" in template_str
    assert "'/row_variant'" in template_str
    assert "'/exclude_completed'" in template_str
    assert "'/exclude_blocked'" in template_str
    assert "'/sort_within_groups'" in template_str
    assert "chore_helper_eids" in template_str
    assert "state_attr(helper_eid, 'chores')" in template_str
    assert "chores_by_label" not in template_str


def test_shared_chore_engine_group_render_uses_translation_sensor_reference() -> None:
    """Shared group render should avoid duplicating the full UI label map per row."""
    template_str = _read_template("shared/chore_engine/group_render_v1.yaml")

    assert "'translation_sensor_eid': translation_sensor" in template_str
    assert "'ui_labels': ui_labels" not in template_str


def test_shared_chore_engine_prepare_groups_rebuilds_labels_from_rows() -> None:
    """Shared grouping fragment should rebuild labels from merged chore rows."""
    template_str = _read_template("shared/chore_engine/prepare_groups_v1.yaml")

    assert "label_group_candidates" in template_str
    assert "ns.discovered_labels" in template_str
    assert "chores_by_label_raw" not in template_str


def test_user_gamification_premier_template_renders_with_button_card_templates() -> (
    None
):
    """Gamification Premier template renders as full dashboard with root templates."""
    template_str = _read_template("user-gamification-premier-v1.yaml")
    chore_engine_context = _read_template("shared/chore_engine/context_v1.yaml")
    chore_engine_prepare_groups = _read_template(
        "shared/chore_engine/prepare_groups_v1.yaml"
    )
    chore_engine_header = _read_template("shared/chore_engine/header_v1.yaml")
    chore_engine_settings = _read_template("shared/chore_engine/settings_panel_v1.yaml")
    chore_engine_group_render = _read_template(
        "shared/chore_engine/group_render_v1.yaml"
    )
    standard_row_template_str = _read_template(
        "shared/button_card_template_chore_row_v1.yaml"
    )
    kids_row_template_str = _read_template(
        "shared/button_card_template_chore_row_kids_v1.yaml"
    )
    template_str = dh.compile_prepared_template_assets(
        {
            "templates/user-gamification-premier-v1.yaml": template_str,
            "templates/shared/chore_engine/context_v1.yaml": chore_engine_context,
            "templates/shared/chore_engine/prepare_groups_v1.yaml": (
                chore_engine_prepare_groups
            ),
            "templates/shared/chore_engine/header_v1.yaml": chore_engine_header,
            "templates/shared/chore_engine/settings_panel_v1.yaml": (
                chore_engine_settings
            ),
            "templates/shared/chore_engine/group_render_v1.yaml": (
                chore_engine_group_render
            ),
            "templates/shared/button_card_template_chore_row_v1.yaml": (
                standard_row_template_str
            ),
            "templates/shared/button_card_template_chore_row_kids_v1.yaml": (
                kids_row_template_str
            ),
        }
    )["templates/user-gamification-premier-v1.yaml"]
    context = dh.build_dashboard_context(
        "Zoe",
        assignee_id="user-123",
        integration_entry_id="entry-123",
        template_profile="user-gamification-premier-v1",
        release_ref="0.0.1-beta.4",
        generated_at="2026-03-06T00:00:00+00:00",
    )

    rendered = builder.render_dashboard_template(template_str, dict(context))

    assert isinstance(rendered.get("views"), list)
    assert len(rendered["views"]) == 1
    assert rendered["views"][0]["title"] == "Zoe"
    assert rendered["views"][0]["path"] == "zoe"
    assert isinstance(rendered["views"][0].get("sections"), list)
    assert isinstance(rendered.get("button_card_templates"), dict)
    assert "chore_row_v1" in rendered["button_card_templates"]
    assert "chore_row_kids_v1" in rendered["button_card_templates"]


def test_user_gamification_premier_template_contains_ui_control_contract() -> None:
    """Gamification Premier template should reference the reviewed UI control contract."""
    template_str = _read_template("user-gamification-premier-v1.yaml")

    assert f"{const.DOMAIN}.{const.SERVICE_MANAGE_UI_CONTROL}" in _read_template(
        "shared/chore_engine/settings_panel_v1.yaml"
    )
    assert "ui_control_key_root = 'gamification/rewards'" in template_str
    assert "template_shared.chore_engine/context_v1" in template_str
    assert "template_shared.chore_engine/prepare_groups_v1" in template_str
    assert "template_shared.chore_engine/header_v1" in template_str
    assert "template_shared.chore_engine/settings_panel_v1" in template_str
    assert "template_shared.chore_engine/group_render_v1" in template_str
    assert "pref_ui_control_key_root = 'gamification/chores'" in template_str


def test_user_family_hub_template_renders_without_parse_errors() -> None:
    """Family Hub (redesigned Premier layout) renders and parses into a dashboard dict."""
    names = [
        "shared/chore_engine/context_v1.yaml",
        "shared/chore_engine/prepare_groups_v1.yaml",
        "shared/chore_engine/header_v1.yaml",
        "shared/chore_engine/settings_panel_v1.yaml",
        "shared/chore_engine/group_render_v1.yaml",
        "shared/chore_engine/group_render_timeline_v1.yaml",
        "shared/button_card_template_chore_row_v1.yaml",
        "shared/button_card_template_chore_row_kids_v1.yaml",
        "shared/button_card_template_chore_row_timeline_v1.yaml",
    ]
    assets = {
        "templates/user-family-hub-v1.yaml": _read_template("user-family-hub-v1.yaml")
    }
    for name in names:
        assets[f"templates/{name}"] = _read_template(name)
    template_str = dh.compile_prepared_template_assets(assets)[
        "templates/user-family-hub-v1.yaml"
    ]
    context = dh.build_dashboard_context(
        "Zoe",
        assignee_id="user-123",
        integration_entry_id="entry-123",
        template_profile="user-family-hub-v1",
        release_ref="0.0.1-beta.3",
        generated_at="2026-10-18T00:00:00+00:00",
    )

    rendered = builder.render_dashboard_template(template_str, dict(context))

    assert isinstance(rendered.get("views"), list)
    assert len(rendered["views"]) == 1
    assert rendered["views"][0]["title"] == "Zoe"
    assert rendered["views"][0]["path"] == "family-hub-zoe"
    assert rendered["views"][0]["subview"] is True
    assert isinstance(rendered["views"][0].get("sections"), list)
    assert "chore_row_timeline_v1" in rendered["button_card_templates"]


def test_family_home_view_renders_first_tab_and_is_not_selectable() -> None:
    """Family Home renders to the 'home' view and is hidden from template pickers."""
    import jinja2

    template_str = _read_template("user-family-home-v1.yaml")
    root_templates: dict = {}
    view = builder._render_family_home_view(
        template_str,
        integration_entry_id="entry-123",
        release_ref="0.0.1-beta.3",
        release_version=None,
        generated_at="2026-10-19T00:00:00+00:00",
        root_button_card_templates=root_templates,
        user_names=["Dad", "Lily"],
    )

    assert view["path"] == "home"
    assert view["title"] == "Home"
    assert view["max_columns"] == 3
    types = [[c["type"] for c in sec["cards"]] for sec in view["sections"]]
    assert types == [
        ["heading", "custom:auto-entities", "custom:auto-entities"],
        ["heading", "custom:auto-entities", "heading", "custom:auto-entities"],
        ["heading", "custom:auto-entities"],
    ]
    env = jinja2.Environment(extensions=["jinja2.ext.loopcontrols"])
    autos = [
        c
        for sec in view["sections"]
        for c in sec["cards"]
        if c["type"] == "custom:auto-entities"
    ]
    assert len(autos) == 5
    for card in autos:
        env.parse(card["filter"]["template"])
        assert (
            '["Dad", "Lily"]' in card["filter"]["template"]
            or "Achievements" in str(card["filter"]["template"])
            or "ACHIEVEMENTS" in str(card["filter"]["template"])
            or "family_total" in card["filter"]["template"]
        )
    assert "family-hub-" in autos[1]["filter"]["template"]
    assert "user-family-home-v1" not in dh.get_assignee_template_ids()
    assert "user-family-home-v1" not in dh.get_admin_template_ids()
    assert dh.get_template_source_path("user-family-home-v1")


def test_admin_family_goals_card_lists_goals_with_reset_service() -> None:
    """Family goals card lists goals from the shared helper and wires the reset service."""

    goals_template = _get_admin_filter_template(
        "admin-shared-family-hub-v1", "===== FAMILY GOALS (RESET) ====="
    )
    mock_states = _base_admin_system_administration_states()
    mock_states["sensor.shared_admin_dashboard_helper"].attributes["ui_control"] = {
        "admin-shared": {"family-goals": {"header-collapse": False}}
    }
    mock_states["sensor.shared_admin_dashboard_helper"].attributes["family_goals"] = [
        {"name": "Pizza Night", "type": "family_points_total", "total": 4, "target": 10}
    ]
    env, integration_entities, states, state_attr = _build_runtime_template_env(
        mock_states
    )

    output = env.from_string(goals_template).render(
        integration_entities=integration_entities,
        states=states,
        state_attr=state_attr,
    )
    parsed = yaml.safe_load(f"[{output}]")

    assert len(parsed) == 2
    assert parsed[0]["name"] == "Family goals & achievements"
    reset_tap = parsed[1]["custom_fields"]["reset"]["card"]["tap_action"]
    assert reset_tap["service"] == "choreops.reset_family_goal"
    assert reset_tap["data"] == {
        "goal_name": "Pizza Night",
        "config_entry_id": "entry-123",
    }
    assert "confirmation" in reset_tap
    assert "4 / 10" in parsed[1]["custom_fields"]["label"]


def _render_quick_actions(
    tab: str,
    open_state: dict[str, object] | None = None,
    helper_attrs: dict[str, object] | None = None,
    extra_states: dict[str, _MockState] | None = None,
):
    template = _get_admin_filter_template(
        "admin-shared-family-hub-v1", "===== QUICK ACTIONS ====="
    )
    mock_states = _base_admin_chore_management_states(
        selected_user_name="Alice",
        selected_dashboard_helper="sensor.alice_dashboard_helper",
        chore_selector_state="None",
        chore_items=[
            {
                "name": "Wash Dishes",
                "eid": "sensor.alice_chore_wash",
                "state": "overdue",
            },
            {"name": "Feed Dog", "eid": "sensor.alice_chore_dog", "state": "pending"},
        ],
        shared_admin_ui_control={
            "admin-shared": {"management-tab": tab, "quick-actions": open_state or {}}
        },
    )
    mock_states["sensor.alice_dashboard_helper"].attributes["gamification_enabled"] = (
        True
    )
    mock_states["sensor.alice_dashboard_helper"].attributes.update(helper_attrs or {})
    mock_states.update(extra_states or {})
    env, integration_entities, states, state_attr = _build_runtime_template_env(
        mock_states
    )
    env.globals["now"] = lambda: __import__("datetime").datetime(2026, 10, 19, 12, 0)
    env.globals["as_datetime"] = lambda v: __import__(
        "datetime"
    ).datetime.fromisoformat(str(v))
    env.filters["as_local"] = lambda v: v
    env.filters["timestamp_custom"] = lambda v, f="", local=True: str(v)
    env.globals["as_timestamp"] = lambda v: 0
    output = env.from_string(template).render(
        integration_entities=integration_entities,
        states=states,
        state_attr=state_attr,
    )
    return yaml.safe_load(f"[{output}]")


def test_admin_multi_card_output_is_native_parseable() -> None:
    """Card lists must parse as one Python literal, as Home Assistant's template
    engine requires; stray newlines between cards turn the result into a string
    and every card shows "Configuration error"."""
    import ast

    template = _get_admin_filter_template(
        "admin-shared-family-hub-v1", "===== QUICK ACTIONS ====="
    )
    for tab in ("chores", "system"):
        mock_states = _base_admin_chore_management_states(
            selected_user_name="Alice",
            selected_dashboard_helper="sensor.alice_dashboard_helper",
            chore_selector_state="None",
            chore_items=[],
            shared_admin_ui_control={"admin-shared": {"management-tab": tab}},
        )
        env, integration_entities, states, state_attr = _build_runtime_template_env(
            mock_states
        )
        env.globals["now"] = lambda: __import__("datetime").datetime(2026, 10, 19)
        env.filters["timestamp_custom"] = lambda v, f="", local=True: str(v)
        env.globals["as_timestamp"] = lambda v: 0
        output = env.from_string(template).render(
            integration_entities=integration_entities,
            states=states,
            state_attr=state_attr,
        )
        assert len(ast.literal_eval(output.strip())) >= 2


def test_admin_quick_actions_chores_tab_tiles_and_skip_list() -> None:
    """Chores tab shows pause/reset/shift/skip/all-chores tiles and the skip list."""

    parsed = _render_quick_actions("chores", {"skip-open": True})
    assert "QUICK ACTIONS" in parsed[0]["name"]
    tiles = parsed[1]["cards"]
    assert [t["name"] for t in tiles] == [
        "Pause chores",
        "Reset overdue",
        "Shift dates",
        "Skip next due",
        "All chores",
    ]
    assert tiles[0]["tap_action"]["data"]["paused"] is True
    reset = tiles[1]["tap_action"]
    assert reset["action"] == "multi-actions"
    assert reset["actions"][0]["data"]["chore_name"] == "Wash Dishes"
    assert tiles[2]["tap_action"]["service"] == "choreops.reschedule_chores_after"
    assert tiles[4]["tap_action"]["data"]["key"] == (
        "admin-shared/quick-actions/allchores-open"
    )
    skip_names = [c["name"] for c in parsed[3]["cards"]]
    assert "Feed Dog" in skip_names


_ECON_BONUSES = [
    {
        "eid": "button.alice_bonus_good",
        "name": "Good Attitude",
        "points": 5,
        "applied": 2,
    },
    {
        "eid": "button.alice_bonus_praise",
        "name": "Praised",
        "points": 100,
        "applied": 0,
    },
]
_ECON_PENALTIES = [
    {"eid": "button.alice_pen_argue", "name": "Argued", "points": -5, "applied": 1},
]


def test_admin_economy_tab_shows_balance_tabs_and_bonuses_by_default() -> None:
    """Economy tab: balance header, three tabs, bonuses list, then the report tile."""

    eco = _render_quick_actions(
        "economy", None, {"bonuses": _ECON_BONUSES, "penalties": _ECON_PENALTIES}
    )
    assert "Available" in eco[0]["custom_fields"]["content"]
    seg = eco[1]["cards"]
    assert [c["name"] for c in seg] == [
        "Bonuses",
        "Penalties",
        "Points",
        "Achievements",
    ]
    assert seg[0]["styles"]["card"][-1]["background"] == "var(--primary-color)"
    assert seg[1]["tap_action"]["data"] == {
        "config_entry_id": "entry-123",
        "ui_control_target": "shared_admin",
        "ui_control_action": "update",
        "key": "admin-shared/quick-actions/econ-tab",
        "value": "penalties",
    }
    rows = eco[2]["cards"]
    assert [r["name"] for r in rows] == ["Good Attitude", "Praised"]
    assert rows[0]["label"] == "+5 · applied 2×"
    assert rows[0]["tap_action"]["service"] == "button.press"
    assert rows[0]["tap_action"]["target"] == {"entity_id": "button.alice_bonus_good"}
    assert "Alice" in rows[0]["tap_action"]["confirmation"]["text"]
    assert "REPORTS" in eco[3]["name"]
    assert [t["name"] for t in eco[4]["cards"]] == ["Activity report"]
    report = eco[4]["cards"][0]["tap_action"]
    assert report["service"] == "choreops.generate_activity_report"
    assert report["data"]["notify_service"] == "persistent_notification.create"
    assert report["data"]["report_title"] == "Activity report: Alice"
    assert report["data"]["user_name"] == "Alice"


def test_admin_economy_tab_penalties_list() -> None:
    """The Penalties tab lists penalties with a minus sign."""

    eco = _render_quick_actions(
        "economy",
        {"econ-tab": "penalties"},
        {"bonuses": _ECON_BONUSES, "penalties": _ECON_PENALTIES},
    )
    rows = eco[2]["cards"]
    assert [r["name"] for r in rows] == ["Argued"]
    assert rows[0]["label"].startswith("−5")
    assert rows[0]["tap_action"]["target"] == {"entity_id": "button.alice_pen_argue"}
    assert eco[1]["cards"][1]["styles"]["card"][-1]["background"] == (
        "var(--primary-color)"
    )


def test_admin_economy_tab_points_stepper_reason_and_apply() -> None:
    """Points tab: stepper, step sizes, reason chips, Apply, recent changes."""

    eco = _render_quick_actions(
        "economy",
        {
            "econ-tab": "points",
            "pts-amount": 100,
            "pts-step": 50,
            "pts-reason": "Helped out",
        },
        {
            "recent_manual_adjustments": [
                {
                    "timestamp": "2026-10-19T12:10:00",
                    "amount": -50.0,
                    "item_name": "Left shoes out",
                    "source": "manual",
                }
            ]
        },
    )
    stepper = eco[2]["cards"]
    assert "+100" in stepper[1]["custom_fields"]["content"]
    minus, plus = stepper[0]["tap_action"], stepper[2]["tap_action"]
    assert minus["data"]["key"] == "admin-shared/quick-actions/pts-amount"
    assert minus["data"]["value"] == 50  # 100 - step 50
    assert plus["data"]["value"] == 150
    assert plus["data"]["ui_control_target"] == "shared_admin"

    steps = eco[3]["cards"]
    assert [c["name"] for c in steps] == ["±10", "±50", "±100", "±500"]
    assert steps[1]["styles"]["card"][-1]["background"] == "var(--primary-color)"
    assert steps[2]["tap_action"]["data"]["value"] == 100

    reasons = eco[5]["cards"]
    assert [c["name"] for c in reasons] == [
        "Helped out",
        "Good behavior",
        "Extra effort",
        "Kindness",
        "Missed credit",
        "Gift",
    ]
    # The picked reason clears when tapped again; another one sets it.
    assert reasons[0]["tap_action"]["data"]["ui_control_action"] == "remove"
    assert reasons[1]["tap_action"]["data"]["value"] == "Good behavior"

    apply_btn = eco[6]
    assert apply_btn["name"] == "Apply +100"
    assert apply_btn["tap_action"]["service"] == "choreops.manual_adjust_points"
    assert apply_btn["tap_action"]["data"] == {
        "config_entry_id": "entry-123",
        "user_name": "Alice",
        "amount": 100,
        "reason": "Helped out",
    }
    assert "Alice" in apply_btn["tap_action"]["confirmation"]["text"]

    recent = eco[7]["custom_fields"]["content"]
    assert "Left shoes out" in recent and "-50" in recent


def test_admin_economy_tab_points_reasons_switch_with_the_direction() -> None:
    """Removing stars offers its own reasons, and drops a reason from the other list."""

    eco = _render_quick_actions(
        "economy",
        {"econ-tab": "points", "pts-amount": -100, "pts-reason": "Helped out"},
        {},
    )
    assert [c["name"] for c in eco[5]["cards"]] == [
        "Correction",
        "Cashed out",
        "Rule broken",
        "Attitude",
    ]
    # "Helped out" was picked while adding; it does not carry over to a deduction.
    apply_btn = eco[6]
    assert apply_btn["tap_action"]["data"]["reason"] == "Adjustment"
    assert "Adjustment" in apply_btn["tap_action"]["confirmation"]["text"]

    kept = _render_quick_actions(
        "economy",
        {"econ-tab": "points", "pts-amount": -100, "pts-reason": "Rule broken"},
        {},
    )
    assert kept[6]["tap_action"]["data"]["reason"] == "Rule broken"


def test_admin_economy_tab_points_zero_amount_shows_the_adding_reasons() -> None:
    """Before an amount is picked the adding list shows."""

    eco = _render_quick_actions("economy", {"econ-tab": "points"}, {})
    assert [c["name"] for c in eco[5]["cards"]][0] == "Helped out"


def test_admin_economy_tab_points_defaults_to_pick_an_amount() -> None:
    """With nothing picked the Apply button does nothing and no reason is sent."""

    eco = _render_quick_actions("economy", {"econ-tab": "points"}, {})
    assert eco[2]["cards"][1]["custom_fields"]["content"].count("0") >= 1
    apply_btn = eco[6]
    assert apply_btn["name"] == "Pick an amount above"
    assert apply_btn["tap_action"] == {"action": "none"}
    # No manual changes yet, so no recent-changes card follows the button.
    assert len(eco) == 7 or "Recent manual" not in str(eco[7])


def test_admin_economy_tab_points_negative_amount_removes_points() -> None:
    """A negative amount shows a Remove confirmation and no picked reason."""

    eco = _render_quick_actions(
        "economy", {"econ-tab": "points", "pts-amount": -50}, {}
    )
    apply_btn = eco[6]
    assert apply_btn["name"] == "Apply -50"
    data = apply_btn["tap_action"]["data"]
    assert data["amount"] == -50 and data["reason"] == "Adjustment"
    assert "Remove 50" in apply_btn["tap_action"]["confirmation"]["text"]


def test_admin_economy_tab_empty_lists_show_a_hint() -> None:
    """With nothing configured, the Bonuses tab shows a short hint."""

    eco = _render_quick_actions("economy", None, {})
    assert eco[2]["cards"][0]["name"] == "No bonuses set up yet"


def test_admin_quick_actions_system_tab_tools_and_links() -> None:
    """System tab: fix-it tools for the person plus family-wide reset and links."""

    badges = [
        {"name": "Gold Star", "earned": True},
        {"name": "Early Bird", "earned": False},
    ]
    system = _render_quick_actions("system", {"badge-open": True}, {"badges": badges})
    assert "FIX-IT TOOLS" in system[0]["name"]
    assert [t["name"] for t in system[1]["cards"]] == ["Remove badge", "Repair streak"]
    assert "FAMILY-WIDE" in system[2]["name"]
    family = system[3]["cards"]
    assert [t["name"] for t in family] == [
        "Reset all to pending",
        "Integration settings",
        "Documentation",
        "Support",
    ]
    assert family[0]["tap_action"]["service"] == (
        "choreops.reset_chores_to_pending_state"
    )
    picks = system[5]["cards"]
    assert [c["name"] for c in picks] == ["Gold Star"]
    assert picks[0]["tap_action"]["service"] == "choreops.remove_awarded_badges"
    assert picks[0]["tap_action"]["data"]["badge_name"] == "Gold Star"


def test_admin_reward_pools_card_lists_pools_and_refund_actions() -> None:
    """Reward pools card shows progress, approve, refund and per-person refunds."""

    template = _get_admin_filter_template(
        "admin-shared-family-hub-v1", "===== REWARD POOLS ====="
    )
    mock_states = _base_admin_system_administration_states()
    mock_states["sensor.shared_admin_dashboard_helper"].attributes["ui_control"] = {
        "admin-shared": {"reward-pools": {"header-collapse": False}}
    }
    mock_states["sensor.alice_dashboard_helper"].attributes["rewards"] = [
        {"name": "Movie Night", "eid": "sensor.reward_movie", "cost": "60 Points"},
        {"name": "Solo Treat", "eid": "sensor.reward_treat", "cost": "5 Points"},
    ]
    mock_states["sensor.reward_movie"] = _MockState(
        entity_id="sensor.reward_movie",
        state="available",
        attributes={
            "pooled": True,
            "pool_total": 60,
            "pool_remaining": 0,
            "pool_full": True,
            "pool_contributions": {"Lily": 25, "Olivia": 35},
            "icon": "mdi:movie",
        },
        name="Movie Night",
    )
    mock_states["sensor.reward_treat"] = _MockState(
        entity_id="sensor.reward_treat",
        state="available",
        attributes={"pooled": False},
        name="Solo Treat",
    )
    env, integration_entities, states, state_attr = _build_runtime_template_env(
        mock_states
    )
    output = env.from_string(template).render(
        integration_entities=integration_entities,
        states=states,
        state_attr=state_attr,
    )
    parsed = yaml.safe_load(f"[{output}]")

    assert len(parsed) == 2
    assert "1 ready" in parsed[0]["label"] or parsed[0]["label"].startswith("Approve")
    fields = parsed[1]["custom_fields"]
    assert "READY" in fields["head"]
    chips = fields["chips"]["card"]["cards"]
    assert [c["tap_action"]["data"]["user_name"] for c in chips] == ["Lily", "Olivia"]
    assert chips[0]["tap_action"]["service"] == "choreops.refund_reward_pool"
    approve, refund = fields["acts"]["card"]["cards"]
    assert approve["tap_action"]["service"] == "choreops.approve_reward_pool"
    assert refund["tap_action"]["data"] == {
        "config_entry_id": "entry-123",
        "reward_name": "Movie Night",
    }


def _render_home_card(marker: str, mock_states: dict[str, _MockState]):
    template_str = _read_template("user-family-home-v1.yaml")
    view = builder._render_family_home_view(
        template_str,
        integration_entry_id="entry-123",
        release_ref="0.0.1-beta.3",
        release_version=None,
        generated_at="2026-10-19T00:00:00+00:00",
        root_button_card_templates={},
        user_names=["Dad", "Lily"],
    )
    tpl = next(
        c["filter"]["template"]
        for sec in view["sections"]
        for c in sec["cards"]
        if c["type"] == "custom:auto-entities" and marker in c["filter"]["template"]
    )
    env, integration_entities, states, state_attr = _build_runtime_template_env(
        mock_states
    )
    env.add_extension("jinja2.ext.loopcontrols")
    env.filters["slugify"] = lambda v: str(v).lower().replace(" ", "_")
    env.globals["now"] = lambda: __import__("datetime").datetime(2026, 10, 19, 12, 0)
    env.filters["round"] = env.filters["round"]
    env.globals["as_timestamp"] = lambda v: (
        __import__("datetime").datetime.fromisoformat(str(v)).timestamp()
    )
    output = env.from_string(tpl).render(
        integration_entities=integration_entities,
        states=states,
        state_attr=state_attr,
    )
    return yaml.safe_load(f"[{output}]")


def _home_states() -> dict[str, _MockState]:
    def helper(name, over, due, week, streak_daily):
        slug = name.lower()
        return {
            f"sensor.{slug}_helper": _MockState(
                entity_id=f"sensor.{slug}_helper",
                state="ok",
                attributes={
                    "purpose": "purpose_dashboard_helper",
                    "user_name": name,
                    "core_sensors": {
                        "points_eid": f"sensor.{slug}_points",
                        "chores_eid": f"sensor.{slug}_chores",
                        "badges_eid": None,
                    },
                    "dashboard_helpers": {},
                    "chores": [{"eid": f"sensor.{slug}_chore_daily"}],
                    "pending_approvals": {
                        "chores": [{"chore_name": "Dishes"}] if name == "Dad" else [],
                        "rewards": [],
                    },
                    "gamification_enabled": True,
                    "caught_up_streak": {
                        "count": streak_daily,
                        "best": max(streak_daily, 19 if name == "Lily" else 0),
                        "today_counted": False,
                    },
                },
                name=name,
            ),
            f"sensor.{slug}_points": _MockState(
                entity_id=f"sensor.{slug}_points", state="100", attributes={}, name="p"
            ),
            f"sensor.{slug}_chores": _MockState(
                entity_id=f"sensor.{slug}_chores",
                state="1",
                attributes={
                    "chore_stat_current_overdue": over,
                    "chore_stat_current_due_today": due,
                    "chore_stat_points_week": week,
                },
                name="c",
            ),
            f"sensor.{slug}_chore_daily": _MockState(
                entity_id=f"sensor.{slug}_chore_daily",
                state="pending",
                attributes={
                    "recurring_frequency": "daily",
                    "chore_current_streak": streak_daily,
                },
                name="d",
            ),
        }

    states = {}
    states.update(helper("Dad", 2, 1, 58, 4))
    states.update(helper("Lily", 0, 0, 145, 12))
    return states


def test_family_home_summary_leaderboard_and_streak_cards() -> None:
    """Home shows the due-soon line, OpsCenter card, leaderboard and streak chip."""

    states = _home_states()
    summary = _render_home_card("SUMMARY + OPSCENTER", states)
    assert len(summary) == 2
    assert "2 overdue" in summary[0]["custom_fields"]["content"]
    assert summary[0]["tap_action"]["navigation_path"].endswith("family-hub-dad")
    assert "Parents" in summary[1]["custom_fields"]["content"]
    assert summary[1]["tap_action"]["navigation_path"].endswith("admin")

    board = _render_home_card("WEEKLY LEADERBOARD", states)
    html = board[0]["custom_fields"]["content"]
    assert html.index("Lily") < html.index("Dad")
    assert "145" in html and "58" in html

    people = _render_home_card("PERSON CARDS", states)
    lily = next(c for c in people if "Lily" in c["custom_fields"]["content"])
    dad = next(c for c in people if "Dad" in c["custom_fields"]["content"])
    lily_html = lily["custom_fields"]["content"]
    dad_html = dad["custom_fields"]["content"]
    assert lily_html.count("12 days") == 1
    assert "⚠" not in lily_html
    assert dad_html.count("4 days ⚠") == 1
    # The streak sits beside the points (before the chip row), so the chips never wrap.
    assert lily_html.index("12 days") < lily_html.index("flex-wrap:nowrap")
    assert "flex-wrap:wrap" not in lily_html


def test_family_home_goal_cards_show_each_person_on_a_track() -> None:
    """Family Goals: every person sits on a race track at their own progress."""

    def badge_helper(name, progress, status):
        slug = name.lower()
        return {
            f"sensor.{slug}_helper": _MockState(
                entity_id=f"sensor.{slug}_helper",
                state="ok",
                attributes={
                    "purpose": "purpose_dashboard_helper",
                    "user_name": name,
                    "badges": [
                        {
                            "eid": f"sensor.{slug}_badge",
                            "name": "Brush Teeth",
                            "badge_type": "periodic",
                        }
                    ],
                },
                name=name,
            ),
            f"sensor.{slug}_badge": _MockState(
                entity_id=f"sensor.{slug}_badge",
                state=str(progress),
                attributes={
                    "badge_name": "Brush Teeth",
                    "status": status,
                    "end_date": "2026-10-22T00:00:00",
                    "icon": "mdi:tooth",
                },
                name="b",
            ),
        }

    states = {}
    states.update(badge_helper("Dad", 20, "in_progress"))
    states.update(badge_helper("Lily", 20, "in_progress"))
    cards = _render_home_card("pref_urgent_days", states)
    assert len(cards) == 1
    html = cards[0]["custom_fields"]["content"]
    assert "Brush Teeth" in html
    # Footer chips: nobody done yet, so both show their initial
    assert re.findall(
        r"<span style='width:16px;height:16px;border-radius:50%;[^']*'>([^<]+)</span>",
        html,
    ) == ["D", "L"]
    assert "3 days left" in html
    # Milestone notches (no labels, the lanes use that space) and the finish flag
    assert html.count("width:1.5px;height:10px") == 3 and "🏁" in html
    # Both people sit at 20%; the first is above the track and the second below,
    # so neither avatar hides the other
    assert html.count("calc(20% - 8px + 0px)") == 2
    assert "top:-22px" in html and "top:7px" in html
    assert "width:20%" in html


def test_family_hub_recent_activity_card_renders_rows() -> None:
    """Recent activity card lists the helper's latest ledger entries."""
    import datetime as _dt

    template_str = _read_template("user-family-hub-v1.yaml")
    context = dh.build_dashboard_context(
        "Lily",
        assignee_id="user-lily",
        integration_entry_id="entry-123",
        template_profile="user-family-hub-v1",
        release_ref="0.0.1-beta.3",
        generated_at="2026-10-19T00:00:00+00:00",
    )
    rendered = builder.render_dashboard_template(template_str, context)
    assert rendered["views"][0]["max_columns"] == 3
    assert len(rendered["views"][0]["sections"]) == 3
    tpl = None
    for section in rendered["views"][0]["sections"]:
        for outer in section["cards"]:
            for card in outer.get("cards", []):
                if "RECENT ACTIVITY CARD" in str(
                    card.get("filter", {}).get("template", "")
                ):
                    tpl = card["filter"]["template"]
    assert tpl is not None
    assert (
        rendered["views"][0]["sections"][-1]["cards"][-1]["cards"][0]["filter"][
            "template"
        ]
        == tpl
    )

    mock_states = {
        "sensor.lily_helper": _MockState(
            entity_id="sensor.lily_helper",
            state="ok",
            attributes={
                "purpose": "purpose_dashboard_helper",
                "dashboard_lookup_key": "entry-123:user-lily",
                "user_name": "Lily",
                "dashboard_helpers": {},
                "ui_control": {
                    "gamification": {"points_history": {"header_collapse": False}}
                },
                "points_summary": {"today": 1510.0, "week": 1600.0, "balance": 8668.0},
                "recent_activity": [
                    {
                        "timestamp": "2026-10-19T12:20:00",
                        "amount": 1500.0,
                        "balance_after": 8668.0,
                        "source": "challenges",
                        "source_label": "Challenge",
                        "item_name": "Family points goal - Level 5",
                    },
                    {
                        "timestamp": "2026-10-19T12:10:00",
                        "amount": 10.0,
                        "source": "chores",
                        "source_label": "Chore",
                        "item_name": "Dishes",
                    },
                    {
                        "timestamp": "2026-10-18T09:00:00",
                        "amount": -2.0,
                        "source": "penalties",
                        "source_label": "Penalty",
                        "item_name": "Late",
                    },
                ],
            },
            name="Lily helper",
        )
    }
    env, integration_entities, states, state_attr = _build_runtime_template_env(
        mock_states
    )
    env.globals["now"] = lambda: _dt.datetime(2026, 10, 19, 13, 0)
    env.globals["as_datetime"] = lambda v: _dt.datetime.fromisoformat(str(v))
    env.filters["as_local"] = lambda v: v
    output = env.from_string(tpl).render(
        integration_entities=integration_entities,
        states=states,
        state_attr=state_attr,
    )
    parsed = yaml.safe_load(f"[{output}]")
    assert parsed[0]["name"] == "Points history"
    assert parsed[0]["custom_fields"]["toggle"].count("chevron-up") == 1
    html = parsed[1]["custom_fields"]["content"]
    assert "Dishes" in html and "+10" in html and "Today" in html
    assert "Late" in html and "Yesterday" in html and "-2" in html
    # Goal payouts show the goal name, a level tag and the balance after.
    assert "Family points goal" in html and "LEVEL 5" in html
    assert "- Level" not in html
    assert "→ 8,668" in html
    # Summary strip: today, this week, balance.
    assert "Today +1,510" in html
    assert "This week +1,600" in html
    assert "Balance 8,668" in html

    # A saved "collapsed" choice hides the rows and leaves just the header.
    mock_states["sensor.lily_helper"].attributes["ui_control"] = {
        "gamification": {"points_history": {"header_collapse": True}}
    }
    collapsed = env.from_string(tpl).render(
        integration_entities=integration_entities,
        states=states,
        state_attr=state_attr,
    )
    parsed_collapsed = yaml.safe_load(f"[{collapsed}]")
    assert len(parsed_collapsed) == 1
    assert "chevron-down" in parsed_collapsed[0]["custom_fields"]["toggle"]

    # With no saved choice the card starts open: header plus the rows.
    mock_states["sensor.lily_helper"].attributes.pop("ui_control")
    opened = env.from_string(tpl).render(
        integration_entities=integration_entities,
        states=states,
        state_attr=state_attr,
    )
    assert len(yaml.safe_load(f"[{opened}]")) == 2


def test_admin_economy_achievements_tab_gives_achievement_to_selected_user() -> None:
    """Achievements tab: one gold tile per achievement; tapping gives it by name."""

    def ach(eid: str, name: str, points: float, count: int) -> _MockState:
        return _MockState(
            entity_id=eid,
            state=str(count),
            attributes={
                "purpose": "purpose_achievement",
                "achievement_name": name,
                "reward_points": points,
                "awarded_to": {"Alice": count} if count else {},
                "icon": "mdi:trophy",
            },
            name=name,
        )

    eco = _render_quick_actions(
        "economy",
        {"econ-tab": "achievements"},
        {},
        {
            "sensor.alice_ach_kitchen": ach(
                "sensor.alice_ach_kitchen", "Kitchen Hero", 20, 3
            ),
            "sensor.alice_ach_help": ach(
                "sensor.alice_ach_help", "Helped a Sibling", 0, 0
            ),
        },
    )
    seg = eco[1]["cards"]
    assert [c["name"] for c in seg] == [
        "Bonuses",
        "Penalties",
        "Points",
        "Achievements",
    ]
    assert seg[3]["styles"]["card"][-1]["background"] == "var(--primary-color)"
    rows = eco[2]["cards"]
    assert sorted(r["name"] for r in rows) == ["Helped a Sibling", "Kitchen Hero"]
    rows = sorted(rows, key=lambda r: r["name"] != "Kitchen Hero")
    assert rows[0]["label"] == "+20 pts · given 3×"
    assert rows[1]["label"] == "no points · given 0×"
    tap = rows[0]["tap_action"]
    assert tap["service"] == "choreops.award_achievement"
    assert tap["data"] == {
        "config_entry_id": "entry-123",
        "user_name": "Alice",
        "achievement_name": "Kitchen Hero",
    }
    assert "Alice" in tap["confirmation"]["text"]
    assert "#d4a017" in rows[0]["styles"]["card"][3]["border"]


def _hub_card_template(marker: str) -> str:
    """Return the inner template of the Family Hub card containing marker."""
    template_str = _read_template("user-family-hub-v1.yaml")
    context = dh.build_dashboard_context(
        "Lily",
        assignee_id="user-lily",
        integration_entry_id="entry-123",
        template_profile="user-family-hub-v1",
        release_ref="0.0.1-beta.3",
        generated_at="2026-10-19T00:00:00+00:00",
    )
    rendered = builder.render_dashboard_template(template_str, context)
    found: list[str] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            tpl = (
                node.get("filter", {}).get("template")
                if isinstance(node.get("filter"), dict)
                else None
            )
            if isinstance(tpl, str) and marker in tpl:
                found.append(tpl)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(rendered["views"][0]["sections"])
    assert found, marker
    return found[0]


def _render_hub_card(
    tpl: str,
    helper_attrs: dict[str, object],
    extra: dict[str, _MockState],
    *,
    real_dates: bool = False,
):
    import datetime as _dt

    mock_states = {
        "sensor.lily_helper": _MockState(
            entity_id="sensor.lily_helper",
            state="ok",
            attributes={
                "purpose": "purpose_dashboard_helper",
                "dashboard_lookup_key": "entry-123:user-lily",
                "user_name": "Lily",
                "dashboard_helpers": {},
                "gamification_enabled": True,
                **helper_attrs,
            },
            name="Lily helper",
        ),
        **extra,
    }
    env, integration_entities, states, state_attr = _build_runtime_template_env(
        mock_states
    )
    env.globals["now"] = lambda: _dt.datetime(2026, 10, 19, 13, 0)
    env.globals["as_datetime"] = lambda v: _dt.datetime.fromisoformat(str(v))
    env.globals["as_timestamp"] = lambda v: 0
    if real_dates:
        env.globals["as_timestamp"] = lambda v: _dt.datetime.fromisoformat(
            str(v)
        ).timestamp()
        env.filters["timestamp_custom"] = lambda v, f="%Y-%m-%d", local=True: (
            _dt.datetime.fromtimestamp(float(v)).strftime(f)
        )
    env.filters["as_local"] = lambda v: v
    return env.from_string(tpl).render(
        integration_entities=integration_entities,
        states=states,
        state_attr=state_attr,
        pref_points_precision="fixed_0",
    )


def _achievement_state(eid: str, name: str, count: int, last: str, points: float = 5):
    return _MockState(
        entity_id=eid,
        state=str(count),
        attributes={
            "achievement_name": name,
            "icon": "mdi:trophy",
            "description": f"{name} description",
            "reward_points": points,
            "award_count": count,
            "awarded": count > 0,
            "last_awarded": last,
        },
        name=name,
    )


def test_family_hub_goals_card_does_not_repeat_achievements() -> None:
    """Achievements live in the badge area; the goals card no longer lists them."""
    tpl = _hub_card_template("gamification/achievements")
    output = _render_hub_card(
        tpl,
        {
            "achievements": [
                {"eid": "sensor.lily_ach_a", "name": "Kitchen Hero"},
                {"eid": "sensor.lily_ach_c", "name": "Not Yet"},
            ]
        },
        {
            "sensor.lily_ach_a": _achievement_state(
                "sensor.lily_ach_a", "Kitchen Hero", 3, "2026-10-18T10:00:00"
            ),
            "sensor.lily_ach_c": _achievement_state(
                "sensor.lily_ach_c", "Not Yet", 0, ""
            ),
        },
    )
    assert "Kitchen Hero" not in output
    assert "Not Yet" not in output


def test_family_hub_showcase_lists_earned_achievements_as_gold_tiles() -> None:
    """The showcase card shows earned achievements only, newest first, with x-count."""
    tpl = _hub_card_template("ach_ns")
    output = _render_hub_card(
        tpl,
        {
            "achievements": [
                {"eid": "sensor.lily_ach_a", "name": "Kitchen Hero"},
                {"eid": "sensor.lily_ach_c", "name": "Not Yet"},
            ]
        },
        {
            "sensor.lily_ach_a": _achievement_state(
                "sensor.lily_ach_a", "Kitchen Hero", 2, "2026-10-18T10:00:00"
            ),
            "sensor.lily_ach_c": _achievement_state(
                "sensor.lily_ach_c", "Not Yet", 0, ""
            ),
        },
    )
    assert "Kitchen Hero" in output
    assert "×2" in output
    assert "#d4a017" in output
    assert "Not Yet" not in output


_SHOWCASE_UI = {
    "good_afternoon": "Good afternoon",
    "total_earned": "Total earned",
    "multiplier": "Multiplier",
    "chores_completed": "Chores completed",
    "due_today": "Due Today",
    "overdue": "Overdue",
    "all_caught_up": "All Caught Up!",
    "none": "None",
}


def _showcase_card(
    *,
    due_today: int = 2,
    overdue: int = 0,
    streak: dict[str, int] | None = None,
    gamification: bool = True,
    extra_helper: dict[str, object] | None = None,
    marker: str = "SHOWCASE CARD",
) -> str:
    """Render the Showcase (or Welcome) card with a fully wired Lily."""
    helper = {
        "dashboard_helpers": {"translation_sensor_eid": "sensor.lily_ui"},
        "core_sensors": {
            "points_eid": "sensor.lily_points",
            "chores_eid": "sensor.lily_chores",
            "badges_eid": "sensor.lily_rank",
        },
        "caught_up_streak": streak or {"count": 1, "best": 1},
        "gamification_enabled": gamification,
        "badges": [],
        "achievements": [],
        "bonuses": [],
        "penalties": [],
        **(extra_helper or {}),
    }
    states = {
        "sensor.lily_ui": _MockState(
            entity_id="sensor.lily_ui",
            state="ok",
            attributes={"ui_translations": _SHOWCASE_UI},
            name="ui",
        ),
        "sensor.lily_points": _MockState(
            entity_id="sensor.lily_points",
            state="9515",
            attributes={
                "icon": "mdi:star-outline",
                "points_multiplier": 1.5,
                "point_stat_points_earned_all_time": 9525,
            },
            name="points",
        ),
        "sensor.lily_chores": _MockState(
            entity_id="sensor.lily_chores",
            state="ok",
            attributes={
                "chore_stat_approved_all_time": 61,
                "chore_stat_current_due_today": due_today,
                "chore_stat_current_overdue": overdue,
            },
            name="chores",
        ),
        "sensor.lily_rank": _MockState(
            entity_id="sensor.lily_rank",
            state="Gold",
            attributes={"icon": "mdi:medal"},
            name="rank",
        ),
    }
    return _render_hub_card(_hub_card_template(marker), helper, states)


def test_family_hub_showcase_is_the_header_with_level_and_status_tiles() -> None:
    """One card carries the greeting, level, total earned and the status tiles."""
    output = _showcase_card()
    assert "Good afternoon" in output
    assert ">L</div>" in output  # avatar initial
    assert "Lily" in output
    assert ">Gold</span>" in output  # current level chip
    assert "9525" in output  # total earned, not the 9515 spendable balance
    assert "Total earned" in output
    assert ">2</div>" in output  # due today
    assert "Due Today" in output
    assert "<span>1</span>" in output  # streak length
    assert "Day streak" in output
    assert "at risk · best 1" in output
    assert ">x1.5</div>" in output
    assert ">61</span>" in output and "Chores completed" in output
    assert "Showcase" not in output
    assert "Highest Rank" not in output


def test_family_hub_showcase_status_tile_follows_the_chore_state() -> None:
    """The first tile reads caught up, due today or overdue, like the old chip."""
    clear = _showcase_card(due_today=0, streak={"count": 4, "best": 9})
    assert "All Caught Up!" in clear
    assert "var(--success-color)" in clear
    assert "best 9" in clear and "at risk" not in clear

    overdue = _showcase_card(overdue=3, streak={"count": 0, "best": 5})
    assert "Overdue" in overdue
    assert "var(--error-color)" in overdue
    assert "ended · best 5" in overdue


def test_family_hub_showcase_has_no_goal_bars() -> None:
    """Goals live in their own card; the showcase no longer repeats them."""
    output = _showcase_card(
        extra_helper={
            "badges": [
                {
                    "eid": "sensor.lily_goal",
                    "name": "Perfect Week",
                    "badge_type": "periodic",
                }
            ]
        }
    )
    assert "Perfect Week" not in output


def test_family_hub_welcome_card_only_renders_when_gamification_is_off() -> None:
    """With gamification on the Showcase is the header; off, Welcome still greets."""
    on = _showcase_card(marker="WELCOME CARD", gamification=True)
    assert "custom:button-card" not in on
    off = _showcase_card(marker="WELCOME CARD", gamification=False)
    assert "custom:button-card" in off
    assert "Good afternoon" in off


def test_family_hub_showcase_card_comes_first() -> None:
    """The merged header sits above Chores on the page."""
    template = _read_template("user-family-hub-v1.yaml")
    assert (
        template.index("SHOWCASE CARD")
        < template.index("WELCOME CARD")
        < template.index("CHORES CARD")
    )


def _goal_badge_states(attrs: dict[str, object], progress: int = 20):
    return (
        {
            "badges": [
                {
                    "eid": "sensor.lily_goal",
                    "name": "Perfect Week",
                    "badge_type": "periodic",
                }
            ]
        },
        {
            "sensor.lily_goal": _MockState(
                entity_id="sensor.lily_goal",
                state=str(progress),
                attributes={
                    "badge_name": "Perfect Week",
                    "badge_type": "periodic",
                    "status": "in_progress",
                    "icon": "mdi:medal",
                    **attrs,
                },
                name="goal",
            )
        },
    )


def test_family_hub_goal_shows_done_missed_today_and_ahead_days() -> None:
    """A weekly goal shows each day of its cycle: done, missed, today, ahead."""
    tpl = _hub_card_template("pref_urgent_days")
    helper, extra = _goal_badge_states(
        {
            "target_type": "days_all_chores",
            "start_date": "2026-10-17",
            "end_date": "2026-10-23",
            "days_done": ["2026-10-17", "2026-10-19"],
            "days_tracked_since": "2026-10-17",
        }
    )
    output = _render_hub_card(tpl, helper, extra, real_dates=True)
    assert "Sat" in output and "Fri" in output
    assert output.count("✓") == 2  # Sat and today's done day
    assert output.count("✗") == 1  # Sun passed with nothing recorded
    assert "2 of 7" in output and "days done" in output


def test_family_hub_count_goal_does_not_mark_days_as_missed() -> None:
    """Goals that count chores or points show active days, never red misses."""
    tpl = _hub_card_template("pref_urgent_days")
    helper, extra = _goal_badge_states(
        {
            "target_type": "chores_all_chores",
            "start_date": "2026-10-12",
            "end_date": "2026-10-25",
            "days_done": ["2026-10-13"],
        }
    )
    output = _render_hub_card(tpl, helper, extra, real_dates=True)
    assert "✗" not in output
    assert "1</b> day active" in output


def test_family_hub_goal_without_dates_has_no_day_strip() -> None:
    """A goal with no start or end date keeps the plain card."""
    tpl = _hub_card_template("pref_urgent_days")
    helper, extra = _goal_badge_states({"target_type": "days_all_chores"})
    output = _render_hub_card(tpl, helper, extra, real_dates=True)
    assert "Perfect Week" in output
    assert "days done" not in output and "✗" not in output


def _daily_goal_states():
    """One in-progress daily goal, one earned daily goal and one weekly goal."""

    def state(eid: str, name: str, status: str, progress: int, **attrs: object):
        return _MockState(
            entity_id=eid,
            state=str(progress),
            attributes={
                "badge_name": name,
                "badge_type": "daily",
                "status": status,
                "icon": "mdi:medal",
                "description": f"{name} description",
                **attrs,
            },
            name=name,
        )

    return (
        {
            "badges": [
                {
                    "eid": "sensor.lily_d1",
                    "name": "Chores Seven",
                    "badge_type": "daily",
                },
                {"eid": "sensor.lily_d2", "name": "Five A Day", "badge_type": "daily"},
                {
                    "eid": "sensor.lily_w1",
                    "name": "Perfect Week",
                    "badge_type": "periodic",
                },
            ]
        },
        {
            "sensor.lily_d1": state(
                "sensor.lily_d1",
                "Chores Seven",
                "in_progress",
                40,
                awards={"award_points": 25},
            ),
            "sensor.lily_d2": state(
                "sensor.lily_d2",
                "Five A Day",
                "earned",
                100,
                last_awarded_date="2026-10-19T09:00:00",
            ),
            "sensor.lily_w1": state(
                "sensor.lily_w1",
                "Perfect Week",
                "in_progress",
                20,
                badge_type="periodic",
                recurring_frequency="weekly",
                target_type="days_all_chores",
                start_date="2026-10-19",
                end_date="2026-10-25",
                days_done=["2026-10-19"],
            ),
        },
    )


def test_family_hub_daily_goals_are_two_column_ring_cards() -> None:
    """Daily goals share a two-column grid; each card has a ring and stays tappable."""
    tpl = _hub_card_template("pref_urgent_days")
    helper, extra = _daily_goal_states()
    output = _render_hub_card(tpl, helper, extra, real_dates=True)

    assert "'columns': 2" in output
    # In-progress daily goal: ring filled to its percent, percent pill, reward chip.
    assert "stroke-dasharray='45.2 113.1'" in output  # 40% of the ring
    assert ">40%</span>" in output
    assert "+25" in output
    # Earned daily goal: solid green ring, check pill and award date.
    assert "stroke='var(--success-color)' stroke-width='4'" in output
    assert "✓ 2026-10-19" in output
    # Both cards keep their own tap target.
    assert "'entity': 'sensor.lily_d1'" in output
    assert "'entity': 'sensor.lily_d2'" in output


def test_family_hub_non_daily_goals_stay_full_width_cards() -> None:
    """Weekly goals keep the wide card with its day strip, outside the daily grid."""
    tpl = _hub_card_template("pref_urgent_days")
    helper, extra = _daily_goal_states()
    output = _render_hub_card(tpl, helper, extra, real_dates=True)

    weekly_part = output[output.index("Perfect Week") :]
    assert "days done" in weekly_part
    assert "conic-gradient" not in weekly_part


def test_family_hub_daily_goal_ring_shows_the_count() -> None:
    """A daily goal's ring pill reads 3/7, not just a percent."""
    tpl = _hub_card_template("pref_urgent_days")
    helper, extra = _goal_badge_states(
        {
            "badge_type": "daily",
            "target_type": "chore_count",
            "threshold_value": 7,
        },
        progress=43,
    )
    helper["badges"][0]["badge_type"] = "daily"
    output = _render_hub_card(tpl, helper, extra, real_dates=True)
    assert ">3/7</span>" in output


def test_family_hub_long_goal_without_a_day_strip_shows_its_count() -> None:
    """A goal too long for a day strip still reads 'x of N chores'."""
    tpl = _hub_card_template("pref_urgent_days")
    helper, extra = _goal_badge_states(
        {
            "target_type": "chore_count",
            "threshold_value": 10,
            "recurring_frequency": "biweekly",
            "start_date": "2026-09-01",
            "end_date": "2026-12-31",
        },
        progress=30,
    )
    output = _render_hub_card(tpl, helper, extra, real_dates=True)
    assert "3 of 10</b> chores" in output


def test_family_hub_open_ended_streak_shows_one_circle_per_day() -> None:
    """A streak goal shows a circle per day it needs, filled to the streak."""
    tpl = _hub_card_template("pref_urgent_days")
    helper, extra = _goal_badge_states(
        {
            "target_type": "streak_all_chores",
            "threshold_value": 10,
            "last_update_day": "2026-10-19",
        },
        progress=40,
    )
    output = _render_hub_card(tpl, helper, extra, real_dates=True)
    assert "4 of 10</b> days in a row" in output
    assert "6 more to earn" in output
    assert output.count("border:2px solid var(--success-color)") == 4
    assert output.count("border:2px dashed var(--primary-color)") == 1
    assert output.count("border:2px solid var(--divider-color)") == 5


def test_family_hub_two_day_streak_shows_two_circles() -> None:
    """A 2-day streak goal at one day has one filled circle and one to fill."""
    tpl = _hub_card_template("pref_urgent_days")
    helper, extra = _goal_badge_states(
        {"target_type": "streak_all_chores", "threshold_value": 2},
        progress=50,
    )
    output = _render_hub_card(tpl, helper, extra, real_dates=True)
    assert "1 of 2</b> days in a row" in output
    assert output.count("border:2px solid var(--success-color)") == 1
    assert output.count("border:2px dashed var(--primary-color)") == 1


def test_family_hub_open_ended_non_streak_keeps_the_seven_day_strip() -> None:
    """Open-ended goals that are not streaks still show the last seven days."""
    tpl = _hub_card_template("pref_urgent_days")
    helper, extra = _goal_badge_states(
        {"target_type": "days_all_chores", "threshold_value": 10},
        progress=0,
    )
    output = _render_hub_card(tpl, helper, extra, real_dates=True)
    assert "of the last 7 days" in output
    assert "days in a row" not in output


def test_family_hub_chores_a_day_ring_follows_todays_count() -> None:
    """A 'N chores a day' goal shows today's count on the ring, not whole days."""
    tpl = _hub_card_template("pref_urgent_days")
    helper, extra = _goal_badge_states(
        {
            "badge_type": "daily",
            "target_type": "days_min_7_chores",
            "threshold_value": 1,
            "today_chores_done": 5,
            "today_chores_required": 7,
        },
        progress=0,
    )
    helper["badges"][0]["badge_type"] = "daily"
    output = _render_hub_card(tpl, helper, extra, real_dates=True)
    assert ">5/7</span>" in output
    assert "stroke-dasharray='80.3 113.1'" in output  # 71% of the ring


def _long_goal(progress: int, **attrs: object):
    return _goal_badge_states(
        {
            "target_type": "chore_count",
            "threshold_value": 10,
            "recurring_frequency": "biweekly",
            "start_date": "2026-10-12",
            "end_date": "2026-10-25",
            **attrs,
        },
        progress=progress,
    )


def test_family_hub_long_goal_shows_calendar_weeks_and_pace() -> None:
    """A two-week goal shows its days as calendar weeks with a pace line."""
    tpl = _hub_card_template("pref_urgent_days")
    helper, extra = _long_goal(10, days_done=["2026-10-13"])
    output = _render_hub_card(tpl, helper, extra, real_dates=True)
    assert output.count("title='2026-") == 14  # one cell per day of the cycle
    assert "Behind pace" in output
    assert "needs 9 · 1.5 per day" in output
    assert "1 of 10</b> chores" in output
    assert "✗" not in output  # a count goal never marks missed days
    assert "Last 4 weeks" not in output


def test_family_hub_long_goal_pace_is_on_track_within_a_unit() -> None:
    """Within a unit of the even pace reads on track, not behind."""
    tpl = _hub_card_template("pref_urgent_days")
    helper, extra = _long_goal(50)
    output = _render_hub_card(tpl, helper, extra, real_dates=True)
    assert "On track" in output
    assert "Behind pace" not in output


def test_family_hub_long_goal_pace_ahead() -> None:
    """A count well past the even pace reads ahead."""
    tpl = _hub_card_template("pref_urgent_days")
    helper, extra = _long_goal(80)
    output = _render_hub_card(tpl, helper, extra, real_dates=True)
    assert "Ahead of pace" in output
    assert "needs 2 · 0.3 per day" in output


def test_family_hub_very_long_goal_shows_only_the_last_four_weeks() -> None:
    """A months-long cycle shows four week rows and notes the cycle length."""
    tpl = _hub_card_template("pref_urgent_days")
    helper, extra = _long_goal(
        20,
        target_type="days_all_chores",
        threshold_value=21,
        start_date="2026-09-01",
        end_date="2026-12-31",
    )
    output = _render_hub_card(tpl, helper, extra, real_dates=True)
    assert "Last 4 weeks" in output
    assert "cycle is 122 days" in output
    assert output.count("title='2026-") == 28


def test_family_hub_days_before_tracking_are_never_marked_missed() -> None:
    """With no tracking start recorded, past days stay blank instead of red."""
    tpl = _hub_card_template("pref_urgent_days")
    helper, extra = _goal_badge_states(
        {
            "target_type": "days_all_chores",
            "start_date": "2026-10-12",
            "end_date": "2026-10-25",
            "days_done": ["2026-10-13"],
        }
    )
    output = _render_hub_card(tpl, helper, extra, real_dates=True)
    assert "✗" not in output
    assert "missed" not in output


def test_family_hub_missed_days_start_at_the_tracking_day() -> None:
    """Only days since tracking began count as missed."""
    tpl = _hub_card_template("pref_urgent_days")
    helper, extra = _goal_badge_states(
        {
            "target_type": "days_all_chores",
            "threshold_value": 10,
            "start_date": "2026-10-12",
            "end_date": "2026-10-25",
            "days_done": ["2026-10-17"],
            "days_tracked_since": "2026-10-16",
        }
    )
    output = _render_hub_card(tpl, helper, extra, real_dates=True)
    # Oct 16 and Oct 18 passed with nothing recorded; Oct 17 was done.
    assert output.count("✗") == 2
    assert "2</b> missed" in output


def _caught_up_goal_state(today: dict[str, object]) -> _MockState:
    return _MockState(
        entity_id="sensor.family_caught_up",
        state="3",
        attributes={
            "achievement_name": "All Caught Up",
            "type": "family_caught_up_days",
            "target_value": 7,
            "family_total": 3,
            "family_contributions": {},
            "family_levels": [7],
            "family_level_rewards": [10],
            "family_level": 0,
            "family_caught_up_today": today,
        },
        name="All Caught Up",
    )


def _caught_up_chip_icons(output: str) -> dict[str, str]:
    """Return each person's chip icon (check or close) from rendered HTML."""
    import re

    return {
        name: icon
        for icon, name in re.findall(
            r"icon=\\?'mdi:(check-bold|close)\\?'[^<]*></ha-icon></span>([^<]+)</div>",
            output,
        )
    }


def test_family_hub_caught_up_chips_read_counts() -> None:
    """Caught-up chips follow "All Caught Up": nothing due today, nothing overdue."""
    tpl = _hub_card_template("family_caught_up_today")
    expected = {"Lily": "check-bold", "Dad": "close", "Max": "close"}
    today = {
        "Lily": {"open": 0, "done": 2, "overdue": False},
        "Dad": {"open": 2, "done": 1, "overdue": False},
        "Max": {"open": 0, "done": 0, "overdue": True},
    }
    output = _render_hub_card(
        tpl, {}, {"sensor.family_caught_up": _caught_up_goal_state(today)}
    )
    assert _caught_up_chip_icons(output) == expected

    # Sensors from before the update still sent sentences; those keep working.
    legacy = {
        "Lily": "0 still to do today, 2 done",
        "Dad": "2 still to do today, 1 done",
        "Max": "0 still to do today, 0 done, overdue",
    }
    output = _render_hub_card(
        tpl, {}, {"sensor.family_caught_up": _caught_up_goal_state(legacy)}
    )
    assert _caught_up_chip_icons(output) == expected


def test_family_home_caught_up_chips_read_counts() -> None:
    """The Home tab's goal card reads the same caught-up numbers."""
    states = _home_states()
    states["sensor.family_caught_up"] = _caught_up_goal_state(
        {
            "Lily": {"open": 0, "done": 2, "overdue": False},
            "Dad": {"open": 1, "done": 0, "overdue": True},
        }
    )
    view = builder._render_family_home_view(
        _read_template("user-family-home-v1.yaml"),
        integration_entry_id="entry-123",
        release_ref="0.0.1-beta.3",
        release_version=None,
        generated_at="2026-10-19T00:00:00+00:00",
        root_button_card_templates={},
        user_names=["Dad", "Lily"],
    )
    tpl = next(
        c["filter"]["template"]
        for sec in view["sections"]
        for c in sec["cards"]
        if c["type"] == "custom:auto-entities"
        and "family_caught_up_today" in c["filter"]["template"]
    )
    env, integration_entities, states_fn, state_attr = _build_runtime_template_env(
        states
    )
    env.add_extension("jinja2.ext.loopcontrols")
    env.globals["now"] = lambda: __import__("datetime").datetime(2026, 10, 19, 12, 0)
    # Rendered as raw text: the card holds HTML that only Home Assistant's
    # Python-literal parsing (not YAML) accepts.
    output = env.from_string(tpl).render(
        integration_entities=integration_entities,
        states=states_fn,
        state_attr=state_attr,
    )
    assert _caught_up_chip_icons(output) == {"Lily": "check-bold", "Dad": "close"}


def test_family_hub_goal_card_uses_dashboard_translations() -> None:
    """Goal card wording comes from the person's dashboard translations."""
    tpl = _hub_card_template("family_caught_up_today")
    goal = _caught_up_goal_state({"Lily": {"open": 0, "done": 1, "overdue": False}})
    goal.attributes.update(
        {"family_levels": [3, 7, 14], "family_level": 1, "family_next_target": 7}
    )
    german = {
        "level": "Stufe",
        "of": "von",
        "to_go": "fehlen noch",
        "days": "Tage",
        "left": "übrig",
    }
    output = _render_hub_card(
        tpl,
        {"dashboard_helpers": {"translation_sensor_eid": "sensor.lily_translations"}},
        {
            "sensor.family_caught_up": goal,
            "sensor.lily_translations": _MockState(
                entity_id="sensor.lily_translations",
                state="de",
                attributes={"ui_translations": german},
                name="Lily translations",
            ),
        },
    )
    assert "4 Tage fehlen noch" in output
    assert "/ 7 Tage" in output
    assert "übrig" in output
    assert " to go" not in output
    assert " left" not in output


def test_family_views_use_build_time_wording() -> None:
    """View titles and section headings use the household's dashboard wording."""
    words = {
        "home": "Startseite",
        "family": "Familie",
        "this_week_heading": "Diese Woche",
        "goals_heading": "Ziele",
        "family_goals_heading": "Familienziele",
        "parents": "Eltern",
    }
    view = builder._render_family_home_view(
        _read_template("user-family-home-v1.yaml"),
        integration_entry_id="entry-123",
        release_ref="0.0.1-beta.3",
        release_version=None,
        generated_at="2026-10-19T00:00:00+00:00",
        root_button_card_templates={},
        user_names=["Dad", "Lily"],
        words=words,
    )
    assert view["title"] == "Startseite"
    headings = [
        card["heading"]
        for sec in view["sections"]
        for card in sec["cards"]
        if card["type"] == "heading"
    ]
    assert headings == ["Familie", "Diese Woche", "Ziele", "Familienziele"]

    admin = builder.render_dashboard_template(
        _read_template("admin-shared-family-hub-v1.yaml"),
        {
            **dh.build_admin_dashboard_context(
                integration_entry_id="entry-123",
                template_profile="admin-shared-family-hub-v1",
            ),
            "t": words,
        },
    )
    assert admin["views"][0]["title"] == "Eltern"

    # Without wording (older callers), the English defaults stay
    plain = builder._render_family_home_view(
        _read_template("user-family-home-v1.yaml"),
        integration_entry_id="entry-123",
        release_ref=None,
        release_version=None,
        generated_at="2026-10-19T00:00:00+00:00",
        root_button_card_templates={},
    )
    assert plain["title"] == "Home"


def test_family_home_race_track_moves_with_todays_chores() -> None:
    """ "N chores a day" goals place each person by today's chore count."""
    view = builder._render_family_home_view(
        _read_template("user-family-home-v1.yaml"),
        integration_entry_id="entry-123",
        release_ref=None,
        release_version=None,
        generated_at="2026-10-21T00:00:00+00:00",
        root_button_card_templates={},
        user_names=["Olivia", "Lily", "Mom", "Dad"],
    )
    tpl = next(
        c["filter"]["template"]
        for sec in view["sections"]
        for c in sec["cards"]
        if c["type"] == "custom:auto-entities"
        and "special_occasion" in c["filter"]["template"]
    )
    people = {
        "Olivia": (5, "earned"),
        "Lily": (4, "in_progress"),
        "Mom": (0, "in_progress"),
        "Dad": (3, "in_progress"),
    }
    states: dict[str, _MockState] = {}
    for name, (done, status) in people.items():
        slug = name.lower()
        badge_eid = f"sensor.{slug}_badge_5aday"
        states[f"sensor.{slug}_helper"] = _MockState(
            entity_id=f"sensor.{slug}_helper",
            state="ok",
            attributes={
                "purpose": "purpose_dashboard_helper",
                "user_name": name,
                "dashboard_helpers": {},
                "badges": [{"eid": badge_eid, "badge_type": "daily"}],
            },
            name=name,
        )
        states[badge_eid] = _MockState(
            entity_id=badge_eid,
            state="100" if status == "earned" else "0",
            attributes={
                "badge_name": "5 chores a day",
                "status": status,
                "today_chores_done": done,
                "today_chores_required": 5,
                "threshold_value": 1,
                "end_date": "2026-10-21",
                "start_date": "2026-10-21",
            },
            name="badge",
        )
    env, integration_entities, states_fn, state_attr = _build_runtime_template_env(
        states
    )
    env.add_extension("jinja2.ext.loopcontrols")
    env.filters["slugify"] = lambda v: str(v).lower()
    env.globals["now"] = lambda: __import__("datetime").datetime(2026, 10, 21, 12, 0)
    env.globals["as_timestamp"] = lambda v: (
        __import__("datetime").datetime.fromisoformat(str(v)).timestamp()
    )
    output = env.from_string(tpl).render(
        integration_entities=integration_entities,
        states=states_fn,
        state_attr=state_attr,
    )
    positions = {
        initial: float(pos)
        for pos, initial in re.findall(
            r"left:calc\(([\d.]+)% - 8px[^>]*><div[^>]*>([A-Z])</div>", output
        )
    }
    # Olivia is done (sits at the finish, drawn at 94%); the rest by today's count
    assert positions == {"O": 94.0, "L": 80.0, "D": 60.0, "M": 0.0}
    # Footer: one chip per person, finished people first as green ticks
    chips = re.findall(
        r"<span style='width:16px;height:16px;border-radius:50%;[^']*'>([^<]+)</span>",
        output,
    )
    assert chips == ["✓", "L", "M", "D"]
    assert "of 4" not in output
