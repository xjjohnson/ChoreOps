# File: helpers/dashboard_template_warmup.py
"""Keep the dashboards' Home Assistant templates compiled.

Home Assistant caches compiled templates only while something holds them, so
the first browser to open a dashboard compiles every card's template (up to
130 KB each) inside Home Assistant, and the page waits. Compiling them ahead
of time and holding on to them makes that first load as fast as the next.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.helpers.template import Template

from .. import const

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_WARM_TEMPLATES_KEY = f"{const.DOMAIN}_warm_dashboard_templates"


def _collect_templates(node: Any, found: set[str]) -> None:
    """Gather every string in a dashboard config that holds Jinja."""
    if isinstance(node, dict):
        for value in node.values():
            _collect_templates(value, found)
    elif isinstance(node, list):
        for value in node:
            _collect_templates(value, found)
    elif isinstance(node, str) and ("{{" in node or "{%" in node):
        found.add(node)


def _compile(template: Template) -> bool:
    """Compile one template into Home Assistant's cache (runs in a worker)."""
    try:
        template.ensure_valid()
    except Exception:
        return False
    return True


async def async_warm_dashboard_templates(
    hass: HomeAssistant,
    config: dict[str, Any] | None = None,
    url_path: str | None = None,
) -> int:
    """Compile and hold the templates of one dashboard, or of all ChoreOps ones.

    Pass `config` when the dashboard was just saved; otherwise the stored
    config of every ChoreOps dashboard is read. Returns how many templates
    are now held.
    """
    configs: list[dict[str, Any]] = []
    if config is not None:
        configs.append(config)
    elif LOVELACE_DATA in hass.data:
        for path, dashboard in hass.data[LOVELACE_DATA].dashboards.items():
            if not path or not path.startswith(
                (
                    const.DASHBOARD_URL_PATH_PREFIX,
                    const.DASHBOARD_LEGACY_URL_PATH_PREFIX,
                )
            ):
                continue
            try:
                stored = await dashboard.async_load(False)
            except Exception:
                continue
            if isinstance(stored, dict):
                configs.append(stored)

    found: set[str] = set()
    for item in configs:
        _collect_templates(item, found)

    held: dict[str, Template] = hass.data.setdefault(_WARM_TEMPLATES_KEY, {})
    for source in found:
        if source in held:
            continue
        template = Template(source, hass)
        if await hass.async_add_executor_job(_compile, template):
            held[source] = template

    const.LOGGER.debug(
        "Warmed %d dashboard templates (%s)", len(held), url_path or "all dashboards"
    )
    return len(held)
