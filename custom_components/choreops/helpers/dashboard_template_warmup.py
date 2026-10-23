# File: helpers/dashboard_template_warmup.py
"""Keep the dashboards' Home Assistant templates compiled.

Home Assistant caches compiled templates only while something holds them, so
the first browser to open a dashboard compiles every card's template (up to
130 KB each) inside Home Assistant, and the page waits. Compiling them ahead
of time and holding on to them makes that first load as fast as the next.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.core import callback
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.template import Template

from .. import const

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.config_entries import ConfigEntry
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


def _compile(template: Template) -> str | None:
    """Compile one template into Home Assistant's cache (runs in a worker).

    Returns None on success, or the error text.
    """
    try:
        template.ensure_valid()
    except Exception as err:
        return str(err)
    return None


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
    started = time.perf_counter()
    configs: dict[str, dict[str, Any]] = {}
    if config is not None:
        configs[url_path or "saved dashboard"] = config
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
            except Exception as err:
                const.LOGGER.warning(
                    "Template warm-up could not read dashboard %s: %s", path, err
                )
                continue
            if isinstance(stored, dict):
                configs[path] = stored

    found: set[str] = set()
    for name, item in configs.items():
        before = len(found)
        _collect_templates(item, found)
        const.LOGGER.info(
            "Template warm-up: dashboard %s has %d templates to compile",
            name,
            len(found) - before,
        )
    if not configs:
        const.LOGGER.info("Template warm-up: no ChoreOps dashboards found")

    held: dict[str, Template] = hass.data.setdefault(_WARM_TEMPLATES_KEY, {})
    slowest = 0.0
    failed = 0
    for source in found:
        if source in held:
            continue
        template = Template(source, hass)
        compile_started = time.perf_counter()
        error = await hass.async_add_executor_job(_compile, template)
        slowest = max(slowest, time.perf_counter() - compile_started)
        if error is None:
            held[source] = template
        else:
            failed += 1
            const.LOGGER.warning(
                "Template warm-up: a %d-character template failed to compile: %s",
                len(source),
                error[:200],
            )

    const.LOGGER.info(
        "Template warm-up: holding %d compiled templates (%d failed, slowest "
        "%.2f s), took %.2f s",
        len(held),
        failed,
        slowest,
        time.perf_counter() - started,
    )
    return len(held)


def async_start_template_warmup(
    hass: HomeAssistant, entry: ConfigEntry
) -> Callable[[], None]:
    """Run the warm-up in the background once Home Assistant has started.

    Returns the function that cancels the wait. The start handler must be a
    @callback: a plain function runs in a worker thread, where creating the
    task fails and the warm-up silently never happens.
    """

    @callback
    def _start(_hass: HomeAssistant) -> None:
        entry.async_create_background_task(
            hass, async_warm_dashboard_templates(hass), "choreops_warm_templates"
        )

    return async_at_started(hass, _start)
