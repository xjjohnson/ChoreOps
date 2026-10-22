"""Tests for the optional badge color setting."""

from typing import Any, cast

from custom_components.choreops import const, data_builders as db
from custom_components.choreops.helpers.entity_helpers import css_color_from_name


def _badge_input(**extra: Any) -> dict[str, Any]:
    return {
        const.CFOF_BADGES_INPUT_NAME: "Helper",
        const.CFOF_BADGES_INPUT_TARGET_THRESHOLD_VALUE: 5,
        **extra,
    }


def test_badge_color_is_stored_and_default_clears_it() -> None:
    """A picked color is stored by name; choosing Default stores no color."""
    badge = db.build_badge(_badge_input(**{const.CFOF_BADGES_INPUT_COLOR: "teal"}))
    assert badge[const.DATA_BADGE_COLOR] == "teal"

    updated = db.build_badge(
        {const.CFOF_BADGES_INPUT_COLOR: const.BADGE_COLOR_DEFAULT},
        existing=badge,
    )
    assert updated[const.DATA_BADGE_COLOR] == ""


def test_badge_color_kept_when_not_in_input() -> None:
    """Editing other fields keeps the stored color; new badges have none."""
    badge = db.build_badge(_badge_input(**{const.CFOF_BADGES_INPUT_COLOR: "amber"}))
    updated = db.build_badge(
        {const.CFOF_BADGES_INPUT_NAME: "Big Helper"}, existing=badge
    )
    assert updated[const.DATA_BADGE_COLOR] == "amber"
    assert db.build_badge(_badge_input())[const.DATA_BADGE_COLOR] == ""


def test_badge_color_survives_data_reset() -> None:
    """The color is configuration, so a data reset keeps it."""
    assert const.DATA_BADGE_COLOR in db._BADGE_DATA_RESET_PRESERVE_FIELDS


def test_every_badge_color_option_maps_to_a_theme_variable() -> None:
    """Each named option except Default becomes its --<name>-color variable."""
    for option in cast("list[dict[str, str]]", const.BADGE_COLOR_OPTIONS):
        value = option["value"]
        if value == const.BADGE_COLOR_DEFAULT:
            continue
        assert css_color_from_name(value) == f"var(--{value}-color)"
