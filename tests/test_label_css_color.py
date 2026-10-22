"""Tests for turning Home Assistant label colors into CSS for the dashboard."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import label_registry as lr

from custom_components.choreops.helpers.entity_helpers import get_label_css_color


async def test_label_css_color(hass: HomeAssistant) -> None:
    """Theme color names become CSS variables; hex colors and blanks pass through."""
    registry = lr.async_get(hass)
    named = registry.async_create("Reading", color="purple")
    hexed = registry.async_create("Kindness", color="#e91e63")
    plain = registry.async_create("Plain")

    assert get_label_css_color(hass, named.label_id) == "var(--purple-color)"
    assert get_label_css_color(hass, hexed.label_id) == "#e91e63"
    assert get_label_css_color(hass, plain.label_id) == ""
    assert get_label_css_color(hass, "missing") == ""
