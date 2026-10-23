"""Dashboard template warm-up: templates stay compiled for the first page load."""

from __future__ import annotations

import gc
import threading
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

from homeassistant.helpers.template import Template

from custom_components.choreops.helpers import dashboard_template_warmup as warmup

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_SOURCE = "{% for i in range(3) %}{{ i }}{% endfor %}"
_CONFIG = {"views": [{"cards": [{"filter": {"template": _SOURCE}}, {"name": "plain"}]}]}


def _compiled_in_cache(hass: HomeAssistant) -> bool:
    return _SOURCE in Template(_SOURCE, hass)._env.template_cache


async def test_warm_templates_stay_compiled_after_use(hass: HomeAssistant) -> None:
    """A warmed template is still compiled once every other holder is gone."""
    held = await warmup.async_warm_dashboard_templates(hass, _CONFIG)
    assert held == 1

    browser_template = Template(_SOURCE, hass)
    browser_template.async_render()
    del browser_template
    gc.collect()

    assert _compiled_in_cache(hass)


async def test_unwarmed_template_is_dropped_once_unused(hass: HomeAssistant) -> None:
    """Without the warm-up, Home Assistant forgets the compiled template."""
    browser_template = Template(_SOURCE, hass)
    browser_template.async_render()
    assert _compiled_in_cache(hass)

    del browser_template
    gc.collect()

    assert not _compiled_in_cache(hass)


async def test_broken_template_does_not_stop_the_rest(hass: HomeAssistant) -> None:
    """One bad template is skipped; the others are still held."""
    config = {"a": "{% if %}", "b": _SOURCE}
    assert await warmup.async_warm_dashboard_templates(hass, config) == 1


async def test_start_handler_runs_on_the_event_loop(hass: HomeAssistant) -> None:
    """The startup hook creates its task on the main thread (it once ran in a worker)."""
    threads: list[str] = []

    def _record(_hass: HomeAssistant, coro: Any, _name: str) -> None:
        threads.append(threading.current_thread().name)
        coro.close()

    entry = MagicMock()
    entry.async_create_background_task.side_effect = _record

    warmup.async_start_template_warmup(hass, entry)
    await hass.async_block_till_done()

    assert threads == [threading.main_thread().name]
