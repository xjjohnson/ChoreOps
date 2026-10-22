"""Tests for family pool rewards (everyone pays points toward one reward)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, patch

from homeassistant.components.button import DOMAIN as BUTTON_DOMAIN, SERVICE_PRESS
from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
import pytest

from custom_components.choreops import const
from custom_components.choreops.reward_pools import const as rp
from tests.helpers import SetupResult, get_dashboard_helper, setup_from_yaml
from tests.helpers.workflows import find_reward, get_reward_buttons

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


@pytest.fixture
async def scenario_full(
    hass: HomeAssistant,
    mock_hass_users: dict[str, Any],
) -> SetupResult:
    """Load full scenario: 3 assignees (Zoë, Max!, Lila), rewards incl. 'Pick Next Movie' (100)."""
    return await setup_from_yaml(
        hass,
        mock_hass_users,
        "tests/scenarios/scenario_full.yaml",
    )


def _make_pool(setup: SetupResult, reward_name: str = "Pick Next Movie") -> str:
    """Turn a scenario reward into a family pool reward and return its ID."""
    reward_id = setup.reward_ids[reward_name]
    setup.coordinator.reward_manager.update_reward(
        reward_id, {const.DATA_REWARD_POOLED: True}
    )
    return reward_id


def _set_points(setup: SetupResult, assignee_id: str, points: float) -> None:
    """Set an assignee's balance directly."""
    setup.coordinator.assignees_data[assignee_id][const.DATA_USER_POINTS] = points


def _points(setup: SetupResult, assignee_id: str) -> float:
    """Return an assignee's balance."""
    return float(setup.coordinator.assignees_data[assignee_id][const.DATA_USER_POINTS])


def _pool(setup: SetupResult, reward_id: str) -> dict[str, float]:
    """Return a reward's pool contributions keyed by user ID."""
    reward = setup.coordinator.rewards_data[reward_id]
    return dict(reward.get(const.DATA_REWARD_POOL_CONTRIBUTIONS, {}))


def _all_time_points(setup: SetupResult, assignee_id: str) -> dict[str, Any]:
    """Return the assignee's all-time point period entry."""
    periods: Any = setup.coordinator.assignees_data[assignee_id].get(
        const.DATA_USER_POINT_PERIODS, {}
    )
    return periods.get(const.DATA_USER_POINT_PERIODS_ALL_TIME, {}).get(
        const.PERIOD_ALL_TIME, {}
    )


async def test_contributions_leave_balance_immediately_and_pool_up(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """Each contribution is withdrawn at once and adds to one shared total."""
    rm = scenario_full.coordinator.reward_manager
    pm = scenario_full.coordinator.reward_pool_manager
    zoe = scenario_full.assignee_ids["Zoë"]
    max_ = scenario_full.assignee_ids["Max!"]
    reward_id = _make_pool(scenario_full)
    _set_points(scenario_full, zoe, 50.0)
    _set_points(scenario_full, max_, 50.0)

    assert await pm.contribute_to_pool(zoe, reward_id, 30.0) == 30.0
    await hass.async_block_till_done()
    assert await pm.contribute_to_pool(max_, reward_id, 20.0) == 20.0
    await hass.async_block_till_done()
    assert await pm.contribute_to_pool(zoe, reward_id, 5.0) == 5.0
    await hass.async_block_till_done()

    assert _points(scenario_full, zoe) == 15.0
    assert _points(scenario_full, max_) == 30.0
    assert _pool(scenario_full, reward_id) == {zoe: 35.0, max_: 20.0}
    reward = scenario_full.coordinator.rewards_data[reward_id]
    assert pm.get_pool_total(reward) == 55.0


async def test_contribution_is_capped_and_default_amount_is_all_affordable(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """A contribution never overfills the pool; no amount means all you can."""
    rm = scenario_full.coordinator.reward_manager
    pm = scenario_full.coordinator.reward_pool_manager
    zoe = scenario_full.assignee_ids["Zoë"]
    max_ = scenario_full.assignee_ids["Max!"]
    reward_id = _make_pool(scenario_full)
    _set_points(scenario_full, zoe, 40.0)
    _set_points(scenario_full, max_, 500.0)

    # No amount: Zoë puts in her whole balance (pool still needs 100)
    assert await pm.contribute_to_pool(zoe, reward_id) == 40.0
    await hass.async_block_till_done()
    # Max asks for 500 but only 60 is still needed
    assert await pm.contribute_to_pool(max_, reward_id, 500.0) == 60.0
    await hass.async_block_till_done()

    assert _points(scenario_full, zoe) == 0.0
    assert _points(scenario_full, max_) == 440.0
    assert sum(_pool(scenario_full, reward_id).values()) == 100.0


async def test_contribution_rejections(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """Not pooled, not assigned, unaffordable and zero contributions fail cleanly."""
    rm = scenario_full.coordinator.reward_manager
    pm = scenario_full.coordinator.reward_pool_manager
    zoe = scenario_full.assignee_ids["Zoë"]
    max_ = scenario_full.assignee_ids["Max!"]
    reward_id = _make_pool(scenario_full)
    normal_reward_id = scenario_full.reward_ids["Extra Screen Time"]
    _set_points(scenario_full, zoe, 10.0)

    with pytest.raises(HomeAssistantError) as err:
        await pm.contribute_to_pool(zoe, normal_reward_id, 5.0)
    assert err.value.translation_key == rp.TRANS_KEY_ERROR_REWARD_NOT_POOLED

    with pytest.raises(HomeAssistantError) as err:
        await pm.contribute_to_pool(zoe, reward_id, 25.0)
    assert err.value.translation_key == const.TRANS_KEY_ERROR_INSUFFICIENT_POINTS

    _set_points(scenario_full, zoe, 0.0)
    with pytest.raises(HomeAssistantError) as err:
        await pm.contribute_to_pool(zoe, reward_id)
    assert err.value.translation_key == rp.TRANS_KEY_ERROR_REWARD_POOL_INVALID_AMOUNT

    rm.update_reward(reward_id, {const.DATA_REWARD_ASSIGNED_USER_IDS: [zoe]})
    _set_points(scenario_full, max_, 50.0)
    with pytest.raises(HomeAssistantError) as err:
        await pm.contribute_to_pool(max_, reward_id, 5.0)
    assert err.value.translation_key == const.TRANS_KEY_ERROR_NOT_ASSIGNED

    assert _pool(scenario_full, reward_id) == {}
    assert _points(scenario_full, max_) == 50.0


async def test_full_pool_notifies_approvers_and_blocks_more_contributions(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """Filling the pool tells approvers once; the pool then refuses more points."""
    coordinator = scenario_full.coordinator
    rm = coordinator.reward_manager
    pm = coordinator.reward_pool_manager
    zoe = scenario_full.assignee_ids["Zoë"]
    max_ = scenario_full.assignee_ids["Max!"]
    reward_id = _make_pool(scenario_full)
    _set_points(scenario_full, zoe, 60.0)
    _set_points(scenario_full, max_, 60.0)

    broadcast = AsyncMock()
    with patch.object(
        coordinator.notification_manager, "broadcast_to_all_approvers", broadcast
    ):
        await pm.contribute_to_pool(zoe, reward_id, 60.0)
        await hass.async_block_till_done()
        broadcast.assert_not_called()

        await pm.contribute_to_pool(max_, reward_id, 60.0)
        await hass.async_block_till_done()

    broadcast.assert_awaited_once()
    assert (
        broadcast.await_args.kwargs["title_key"]
        == rp.TRANS_KEY_NOTIF_TITLE_REWARD_POOL_FULL_APPROVER
    )
    assert broadcast.await_args.kwargs["placeholders"]["reward_name"] == (
        "Pick Next Movie"
    )
    assert _points(scenario_full, max_) == 20.0

    with pytest.raises(HomeAssistantError) as err:
        await pm.contribute_to_pool(max_, reward_id, 5.0)
    assert err.value.translation_key == rp.TRANS_KEY_ERROR_REWARD_POOL_FULL


async def test_approve_pool_empties_it_without_charging_again(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """Approval needs a full pool, then resets it and tells each contributor."""
    coordinator = scenario_full.coordinator
    rm = coordinator.reward_manager
    pm = coordinator.reward_pool_manager
    zoe = scenario_full.assignee_ids["Zoë"]
    max_ = scenario_full.assignee_ids["Max!"]
    reward_id = _make_pool(scenario_full)
    _set_points(scenario_full, zoe, 70.0)
    _set_points(scenario_full, max_, 70.0)

    await pm.contribute_to_pool(zoe, reward_id, 70.0)
    await hass.async_block_till_done()
    with pytest.raises(HomeAssistantError) as err:
        await pm.approve_pool("Mom", reward_id)
    assert err.value.translation_key == rp.TRANS_KEY_ERROR_REWARD_POOL_NOT_FULL

    await pm.contribute_to_pool(max_, reward_id, 30.0)
    await hass.async_block_till_done()

    notify = AsyncMock()
    with patch.object(
        coordinator.notification_manager, "notify_assignee_translated", notify
    ):
        await pm.approve_pool("Mom", reward_id)
        await hass.async_block_till_done()

    assert _pool(scenario_full, reward_id) == {}
    assert _points(scenario_full, zoe) == 0.0
    assert _points(scenario_full, max_) == 40.0
    notified = {call.args[0] for call in notify.await_args_list}
    assert notified == {zoe, max_}
    reward_data = coordinator.assignees_data[zoe][const.DATA_USER_REWARD_DATA]
    assert reward_data[reward_id][const.DATA_USER_REWARD_DATA_LAST_APPROVED]

    # The family can save up again
    _set_points(scenario_full, zoe, 10.0)
    assert await pm.contribute_to_pool(zoe, reward_id, 10.0) == 10.0


async def test_approve_refunds_overfill_when_cost_was_lowered(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """Lowering the cost below the pool refunds the excess by share on approval."""
    rm = scenario_full.coordinator.reward_manager
    pm = scenario_full.coordinator.reward_pool_manager
    zoe = scenario_full.assignee_ids["Zoë"]
    max_ = scenario_full.assignee_ids["Max!"]
    reward_id = _make_pool(scenario_full)
    _set_points(scenario_full, zoe, 60.0)
    _set_points(scenario_full, max_, 20.0)

    await pm.contribute_to_pool(zoe, reward_id, 60.0)
    await pm.contribute_to_pool(max_, reward_id, 20.0)
    await hass.async_block_till_done()

    # Pool holds 80; cost drops to 40, so 40 comes back split 3:1
    rm.update_reward(reward_id, {const.DATA_REWARD_COST: 40.0})
    assert _pool(scenario_full, reward_id) == {zoe: 60.0, max_: 20.0}
    await pm.approve_pool("Mom", reward_id)
    await hass.async_block_till_done()

    assert _points(scenario_full, zoe) == 30.0
    assert _points(scenario_full, max_) == 10.0
    assert _pool(scenario_full, reward_id) == {}


def test_split_overfill_sums_exactly() -> None:
    """Rounding residue goes to the largest contributor so refunds sum exactly."""
    from custom_components.choreops.reward_pools.manager import RewardPoolManager

    refunds = RewardPoolManager._split_overfill({"a": 1.0, "b": 1.0, "c": 1.0}, 1.0)
    assert round(sum(refunds.values()), 2) == 1.0
    assert RewardPoolManager._split_overfill({"a": 5.0}, 0.0) == {}


async def test_refund_returns_exact_contributions_without_counting_as_earned(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """Refunds restore balances and reverse points spent, not points earned."""
    rm = scenario_full.coordinator.reward_manager
    pm = scenario_full.coordinator.reward_pool_manager
    zoe = scenario_full.assignee_ids["Zoë"]
    max_ = scenario_full.assignee_ids["Max!"]
    reward_id = _make_pool(scenario_full)
    _set_points(scenario_full, zoe, 50.0)
    _set_points(scenario_full, max_, 50.0)
    earned_before = _all_time_points(scenario_full, zoe).get(
        const.DATA_USER_POINT_PERIOD_POINTS_EARNED, 0.0
    )

    await pm.contribute_to_pool(zoe, reward_id, 25.5)
    await pm.contribute_to_pool(max_, reward_id, 10.0)
    await hass.async_block_till_done()

    assert await pm.refund_pool(reward_id) == {zoe: 25.5, max_: 10.0}
    await hass.async_block_till_done()

    assert _points(scenario_full, zoe) == 50.0
    assert _points(scenario_full, max_) == 50.0
    assert _pool(scenario_full, reward_id) == {}
    all_time = _all_time_points(scenario_full, zoe)
    assert all_time.get(const.DATA_USER_POINT_PERIOD_POINTS_EARNED, 0.0) == (
        earned_before
    )
    assert all_time.get(const.DATA_USER_POINT_PERIOD_POINTS_SPENT, 0.0) == 0.0
    # Refunding an empty pool is a no-op
    assert await pm.refund_pool(reward_id) == {}


async def test_deleting_pooled_reward_refunds_everyone(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """Deleting a pooled reward gives contributors their points back."""
    rm = scenario_full.coordinator.reward_manager
    pm = scenario_full.coordinator.reward_pool_manager
    zoe = scenario_full.assignee_ids["Zoë"]
    reward_id = _make_pool(scenario_full)
    _set_points(scenario_full, zoe, 50.0)

    await pm.contribute_to_pool(zoe, reward_id, 40.0)
    await hass.async_block_till_done()
    assert _points(scenario_full, zoe) == 10.0

    rm.delete_reward(reward_id)
    await hass.async_block_till_done()

    assert _points(scenario_full, zoe) == 50.0


async def test_pool_survives_reward_edits(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """Editing other reward fields keeps the points in the pool."""
    rm = scenario_full.coordinator.reward_manager
    pm = scenario_full.coordinator.reward_pool_manager
    zoe = scenario_full.assignee_ids["Zoë"]
    reward_id = _make_pool(scenario_full)
    _set_points(scenario_full, zoe, 50.0)
    await pm.contribute_to_pool(zoe, reward_id, 15.0)
    await hass.async_block_till_done()

    rm.update_reward(reward_id, {const.DATA_REWARD_DESCRIPTION: "Popcorn included"})
    assert _pool(scenario_full, reward_id) == {zoe: 15.0}

    # Turning the pool off keeps the points so they can still be refunded
    rm.update_reward(reward_id, {const.DATA_REWARD_POOLED: False})
    assert _pool(scenario_full, reward_id) == {zoe: 15.0}
    await pm.refund_pool(reward_id)
    await hass.async_block_till_done()
    assert _points(scenario_full, zoe) == 50.0


async def test_pooled_reward_cannot_be_redeemed_or_charged_to_one_person(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """Redeem and a full-cost approve are refused; free badge-style grants still work."""
    rm = scenario_full.coordinator.reward_manager
    pm = scenario_full.coordinator.reward_pool_manager
    zoe = scenario_full.assignee_ids["Zoë"]
    reward_id = _make_pool(scenario_full)
    _set_points(scenario_full, zoe, 500.0)

    with pytest.raises(HomeAssistantError) as err:
        await rm.redeem("Zoë", zoe, reward_id)
    assert err.value.translation_key == const.TRANS_KEY_ERROR_REWARD_IS_POOLED

    with pytest.raises(HomeAssistantError) as err:
        await rm.approve("Mom", zoe, reward_id)
    assert err.value.translation_key == const.TRANS_KEY_ERROR_REWARD_IS_POOLED

    await rm.approve("Badge", zoe, reward_id, cost_override=0.0)
    await hass.async_block_till_done()
    assert _points(scenario_full, zoe) == 500.0


async def test_pool_services_end_to_end(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """Create a pooled reward by service, contribute, approve and refund by service."""
    coordinator = scenario_full.coordinator
    zoe = scenario_full.assignee_ids["Zoë"]
    max_ = scenario_full.assignee_ids["Max!"]
    _set_points(scenario_full, zoe, 30.0)
    _set_points(scenario_full, max_, 30.0)

    await hass.services.async_call(
        const.DOMAIN,
        const.SERVICE_CREATE_REWARD,
        {"name": "Family Pizza Night", "cost": 50, "pooled": True},
        blocking=True,
        return_response=True,
    )
    reward_id = next(
        rid
        for rid, reward in coordinator.rewards_data.items()
        if reward[const.DATA_REWARD_NAME] == "Family Pizza Night"
    )
    assert coordinator.rewards_data[reward_id][const.DATA_REWARD_POOLED] is True

    response = await hass.services.async_call(
        const.DOMAIN,
        rp.SERVICE_CONTRIBUTE_TO_REWARD_POOL,
        {"user_name": "Zoë", "reward_name": "Family Pizza Night"},
        blocking=True,
        return_response=True,
    )
    assert response == {const.SERVICE_FIELD_POINTS_AMOUNT: 30.0}
    await hass.services.async_call(
        const.DOMAIN,
        rp.SERVICE_CONTRIBUTE_TO_REWARD_POOL,
        {"user_name": "Max!", "reward_name": "Family Pizza Night", "amount": 20},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert _points(scenario_full, zoe) == 0.0
    assert _points(scenario_full, max_) == 10.0

    await hass.services.async_call(
        const.DOMAIN,
        rp.SERVICE_APPROVE_REWARD_POOL,
        {"reward_name": "Family Pizza Night", "approver_name": "Mom"},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert _pool(scenario_full, reward_id) == {}

    await hass.services.async_call(
        const.DOMAIN,
        rp.SERVICE_CONTRIBUTE_TO_REWARD_POOL,
        {"user_name": "Max!", "reward_name": "Family Pizza Night", "amount": 10},
        blocking=True,
    )
    await hass.services.async_call(
        const.DOMAIN,
        rp.SERVICE_REFUND_REWARD_POOL,
        {"reward_name": "Family Pizza Night"},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert _points(scenario_full, max_) == 10.0

    # Refunding one person by name (the dashboard's name chips)
    await hass.services.async_call(
        const.DOMAIN,
        rp.SERVICE_CONTRIBUTE_TO_REWARD_POOL,
        {"user_name": "Max!", "reward_name": "Family Pizza Night", "amount": 5},
        blocking=True,
    )
    _set_points(scenario_full, zoe, 8.0)
    await hass.services.async_call(
        const.DOMAIN,
        rp.SERVICE_CONTRIBUTE_TO_REWARD_POOL,
        {"user_name": "Zoë", "reward_name": "Family Pizza Night", "amount": 8},
        blocking=True,
    )
    await hass.services.async_call(
        const.DOMAIN,
        rp.SERVICE_REFUND_REWARD_POOL,
        {"reward_name": "Family Pizza Night", "user_name": "Max!"},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert _points(scenario_full, max_) == 10.0
    assert _pool(scenario_full, reward_id) == {zoe: 8.0}


async def test_reward_status_sensor_shows_pool(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """The reward status sensor exposes pool progress and reports a full pool."""
    coordinator = scenario_full.coordinator
    rm = coordinator.reward_manager
    pm = coordinator.reward_pool_manager
    zoe = scenario_full.assignee_ids["Zoë"]
    max_ = scenario_full.assignee_ids["Max!"]
    reward_id = _make_pool(scenario_full)
    _set_points(scenario_full, zoe, 60.0)
    _set_points(scenario_full, max_, 60.0)

    unique_id = (
        f"{scenario_full.config_entry.entry_id}_{zoe}_{reward_id}"
        f"{const.SENSOR_KC_UID_SUFFIX_REWARD_STATUS_SENSOR}"
    )
    entity_id = er.async_get(hass).async_get_entity_id(
        "sensor", const.DOMAIN, unique_id
    )
    assert entity_id

    await pm.contribute_to_pool(zoe, reward_id, 25.0)
    await hass.async_block_till_done()
    coordinator.async_update_listeners()
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == const.REWARD_STATE_AVAILABLE
    assert state.attributes[rp.ATTR_REWARD_POOLED] is True
    assert state.attributes[rp.ATTR_REWARD_POOL_TOTAL] == 25.0
    assert state.attributes[rp.ATTR_REWARD_POOL_REMAINING] == 75.0
    assert state.attributes[rp.ATTR_REWARD_POOL_MY_CONTRIBUTION] == 25.0
    assert state.attributes[rp.ATTR_REWARD_POOL_CONTRIBUTIONS] == {"Zoë": 25.0}

    await pm.contribute_to_pool(max_, reward_id, 60.0)
    await hass.async_block_till_done()
    await pm.contribute_to_pool(zoe, reward_id, 15.0)
    await hass.async_block_till_done()
    coordinator.async_update_listeners()
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == const.REWARD_STATE_REQUESTED
    assert state.attributes[rp.ATTR_REWARD_POOL_FULL] is True


# =============================================================================
# Dashboard buttons
# =============================================================================


async def _press(hass: HomeAssistant, button_eid: str, context: Context) -> None:
    """Press a button entity, propagating errors."""
    await hass.services.async_call(
        BUTTON_DOMAIN,
        SERVICE_PRESS,
        {"entity_id": button_eid},
        blocking=True,
        context=context,
    )
    await hass.async_block_till_done()


def _zoe_buttons(hass: HomeAssistant, reward_name: str) -> tuple[str, dict[str, str]]:
    """Return Zoë's reward sensor entity ID and its claim/approve/disapprove buttons."""
    reward = find_reward(get_dashboard_helper(hass, "zoe"), reward_name)
    assert reward is not None
    buttons = get_reward_buttons(hass, reward["eid"])
    state = hass.states.get(reward["eid"])
    assert state is not None
    buttons["disapprove"] = state.attributes[
        const.ATTR_REWARD_DISAPPROVE_BUTTON_ENTITY_ID
    ]
    return reward["eid"], buttons


async def test_redeem_button_chips_in_by_chip_in_amount(
    hass: HomeAssistant,
    scenario_full: SetupResult,
    mock_hass_users: dict[str, Any],
) -> None:
    """On a pooled reward the dashboard button pays in the chip-in amount per press."""
    rm = scenario_full.coordinator.reward_manager
    pm = scenario_full.coordinator.reward_pool_manager
    zoe = scenario_full.assignee_ids["Zoë"]
    reward_id = _make_pool(scenario_full)
    rm.update_reward(reward_id, {const.DATA_REWARD_POOL_CHIP_IN: 10.0})
    _set_points(scenario_full, zoe, 35.0)
    _, buttons = _zoe_buttons(hass, "Pick Next Movie")
    zoe_context = Context(user_id=mock_hass_users["assignee1"].id)

    await _press(hass, buttons["claim"], zoe_context)
    await _press(hass, buttons["claim"], zoe_context)

    assert _pool(scenario_full, reward_id) == {zoe: 20.0}
    assert _points(scenario_full, zoe) == 15.0
    # No claim was created - the reward never enters the normal approval queue
    assert rm.get_pending_approvals() == []


async def test_redeem_button_without_chip_in_puts_in_all_affordable(
    hass: HomeAssistant,
    scenario_full: SetupResult,
    mock_hass_users: dict[str, Any],
) -> None:
    """A chip-in amount of 0 puts in as much as the person can afford."""
    zoe = scenario_full.assignee_ids["Zoë"]
    reward_id = _make_pool(scenario_full)
    _set_points(scenario_full, zoe, 35.0)
    _, buttons = _zoe_buttons(hass, "Pick Next Movie")

    await _press(
        hass, buttons["claim"], Context(user_id=mock_hass_users["assignee1"].id)
    )

    assert _pool(scenario_full, reward_id) == {zoe: 35.0}
    assert _points(scenario_full, zoe) == 0.0


async def test_approve_button_confirms_full_pool_and_disapprove_refuses(
    hass: HomeAssistant,
    scenario_full: SetupResult,
    mock_hass_users: dict[str, Any],
) -> None:
    """Approve on a full pool empties it; disapprove never refunds from a tap."""
    rm = scenario_full.coordinator.reward_manager
    pm = scenario_full.coordinator.reward_pool_manager
    zoe = scenario_full.assignee_ids["Zoë"]
    reward_id = _make_pool(scenario_full)
    _set_points(scenario_full, zoe, 100.0)
    await pm.contribute_to_pool(zoe, reward_id)
    await hass.async_block_till_done()
    scenario_full.coordinator.async_update_listeners()
    await hass.async_block_till_done()

    sensor_eid, buttons = _zoe_buttons(hass, "Pick Next Movie")
    state = hass.states.get(sensor_eid)
    assert state is not None
    assert state.state == const.REWARD_STATE_REQUESTED
    admin_context = Context(user_id=mock_hass_users["admin"].id)

    with pytest.raises(HomeAssistantError) as err:
        await _press(hass, buttons["disapprove"], admin_context)
    assert err.value.translation_key == const.TRANS_KEY_ERROR_REWARD_POOL_NO_DISAPPROVE
    assert _pool(scenario_full, reward_id) == {zoe: 100.0}

    await _press(hass, buttons["approve"], admin_context)

    assert _pool(scenario_full, reward_id) == {}
    assert _points(scenario_full, zoe) == 0.0


async def test_refund_single_contributor_leaves_the_rest_in_the_pool(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """Refunding one person returns only their share and keeps the others."""
    rm = scenario_full.coordinator.reward_manager
    pm = scenario_full.coordinator.reward_pool_manager
    zoe = scenario_full.assignee_ids["Zoë"]
    max_ = scenario_full.assignee_ids["Max!"]
    reward_id = _make_pool(scenario_full)
    _set_points(scenario_full, zoe, 50.0)
    _set_points(scenario_full, max_, 50.0)

    await pm.contribute_to_pool(zoe, reward_id, 25.0)
    await pm.contribute_to_pool(max_, reward_id, 10.0)
    await hass.async_block_till_done()

    assert await pm.refund_pool(reward_id, zoe) == {zoe: 25.0}
    await hass.async_block_till_done()

    assert _points(scenario_full, zoe) == 50.0
    assert _points(scenario_full, max_) == 40.0
    assert _pool(scenario_full, reward_id) == {max_: 10.0}
    # Refunding someone who has nothing in the pool is a no-op
    assert await pm.refund_pool(reward_id, zoe) == {}
    assert _pool(scenario_full, reward_id) == {max_: 10.0}


def test_pool_validation_rules() -> None:
    """A pooled reward needs a cost above 0 and a chip-in no bigger than the cost."""
    from custom_components.choreops.data_builders import validate_reward_data
    from custom_components.choreops.reward_pools.validation import (
        validate_pool_settings,
    )

    pooled = {const.DATA_REWARD_NAME: "Pool", const.DATA_REWARD_POOLED: True}
    assert validate_reward_data({**pooled, const.DATA_REWARD_COST: 0}) == {
        const.CFOP_ERROR_REWARD_COST: rp.TRANS_KEY_CFOF_REWARD_POOL_COST_ZERO
    }
    assert validate_reward_data(
        {**pooled, const.DATA_REWARD_COST: 50, const.DATA_REWARD_POOL_CHIP_IN: 60}
    ) == {
        const.CFOF_REWARDS_INPUT_POOL_CHIP_IN: (
            rp.TRANS_KEY_CFOF_REWARD_POOL_CHIP_IN_TOO_HIGH
        )
    }
    assert (
        validate_reward_data(
            {**pooled, const.DATA_REWARD_COST: 50, const.DATA_REWARD_POOL_CHIP_IN: 50}
        )
        == {}
    )
    # Normal rewards may still be free
    assert validate_reward_data({const.DATA_REWARD_NAME: "Free", "cost": 0}) == {}

    # A partial update falls back to the stored reward
    stored = {const.DATA_REWARD_COST: 0, const.DATA_REWARD_POOLED: False}
    assert validate_pool_settings({const.DATA_REWARD_POOLED: True}, stored) == {
        const.CFOP_ERROR_REWARD_COST: rp.TRANS_KEY_CFOF_REWARD_POOL_COST_ZERO
    }
    stored = {const.DATA_REWARD_COST: 40, const.DATA_REWARD_POOLED: True}
    assert validate_pool_settings({const.DATA_REWARD_POOL_CHIP_IN: 41}, stored) == {
        const.CFOF_REWARDS_INPUT_POOL_CHIP_IN: (
            rp.TRANS_KEY_CFOF_REWARD_POOL_CHIP_IN_TOO_HIGH
        )
    }


async def test_services_refuse_free_pool_and_oversized_chip_in(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """create_reward / update_reward reject pool settings that can't work."""
    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            const.DOMAIN,
            const.SERVICE_CREATE_REWARD,
            {"name": "Free Pool", "cost": 0, "pooled": True},
            blocking=True,
            return_response=True,
        )
    assert err.value.translation_key == rp.TRANS_KEY_CFOF_REWARD_POOL_COST_ZERO

    reward_id = _make_pool(scenario_full)  # Pick Next Movie, cost 100
    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            const.DOMAIN,
            const.SERVICE_UPDATE_REWARD,
            {"name": "Pick Next Movie", "pool_chip_in": 150},
            blocking=True,
            return_response=True,
        )
    assert err.value.translation_key == rp.TRANS_KEY_CFOF_REWARD_POOL_CHIP_IN_TOO_HIGH
    assert scenario_full.coordinator.rewards_data[reward_id].get(
        const.DATA_REWARD_POOL_CHIP_IN, 0
    ) in (0, 0.0)


async def test_back_to_back_contributions_to_two_pools_cannot_overspend(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """Two quick taps on two different pools only take points that exist.

    The pools have separate locks, so the second contribution must see the
    first one's withdrawal; otherwise both pass the balance check and one pool
    keeps points that never left the balance.
    """
    import asyncio

    pm = scenario_full.coordinator.reward_pool_manager
    zoe = scenario_full.assignee_ids["Zoë"]
    movie = _make_pool(scenario_full)
    outing = _make_pool(scenario_full, "Special Outing")
    _set_points(scenario_full, zoe, 30.0)

    results = await asyncio.gather(
        pm.contribute_to_pool(zoe, movie, 30.0),
        pm.contribute_to_pool(zoe, outing, 30.0),
        return_exceptions=True,
    )
    await hass.async_block_till_done()

    assert results[0] == 30.0
    assert isinstance(results[1], HomeAssistantError)
    assert results[1].translation_key == const.TRANS_KEY_ERROR_INSUFFICIENT_POINTS
    assert _points(scenario_full, zoe) == 0.0
    assert _pool(scenario_full, movie) == {zoe: 30.0}
    assert _pool(scenario_full, outing) == {}


# ---------------------------------------------------------------------------
# Pool settings: share limit, parent match, after delivery
# ---------------------------------------------------------------------------


async def test_share_limit_caps_each_person(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """Nobody can pay in more than the share limit, counted over all chip-ins."""
    pm = scenario_full.coordinator.reward_pool_manager
    zoe = scenario_full.assignee_ids["Zoë"]
    reward_id = _make_pool(scenario_full)
    scenario_full.coordinator.reward_manager.update_reward(
        reward_id, {rp.DATA_REWARD_POOL_MAX_SHARE: 40}
    )
    _set_points(scenario_full, zoe, 500.0)

    assert await pm.contribute_to_pool(zoe, reward_id, 25.0) == 25.0
    await hass.async_block_till_done()
    # Only 15 of her 40 point share is left
    assert await pm.contribute_to_pool(zoe, reward_id) == 15.0
    await hass.async_block_till_done()
    with pytest.raises(HomeAssistantError) as err:
        await pm.contribute_to_pool(zoe, reward_id, 1.0)
    assert err.value.translation_key == rp.TRANS_KEY_ERROR_REWARD_POOL_SHARE_REACHED
    assert _points(scenario_full, zoe) == 460.0

    reward = scenario_full.coordinator.rewards_data[reward_id]
    attrs = pm.sensor_attributes(reward, zoe)
    assert attrs[rp.ATTR_REWARD_POOL_MAX_SHARE] == 40.0
    assert attrs[rp.ATTR_REWARD_POOL_MY_SHARE_LEFT] == 0.0


async def test_parent_match_comes_from_the_parents_balance(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """A match is withdrawn from the parent, capped, refunded to them, never granted."""
    coordinator = scenario_full.coordinator
    pm = coordinator.reward_pool_manager
    zoe = scenario_full.assignee_ids["Zoë"]
    max_ = scenario_full.assignee_ids["Max!"]
    parent = scenario_full.assignee_ids["Lila"]  # Stands in for a parent with points
    reward_id = _make_pool(scenario_full)
    coordinator.reward_manager.update_reward(
        reward_id,
        {
            rp.DATA_REWARD_POOL_MATCH_RATIO: 1,
            rp.DATA_REWARD_POOL_MATCH_USER_IDS: [parent],
            const.DATA_REWARD_ASSIGNED_USER_IDS: [zoe, max_],
        },
    )
    _set_points(scenario_full, zoe, 100.0)
    _set_points(scenario_full, max_, 100.0)
    _set_points(scenario_full, parent, 30.0)

    assert await pm.contribute_to_pool(zoe, reward_id, 20.0) == 20.0
    await hass.async_block_till_done()
    assert _pool(scenario_full, reward_id) == {zoe: 20.0, parent: 20.0}
    # The parent only has 10 left to match with
    await pm.contribute_to_pool(max_, reward_id, 25.0)
    await hass.async_block_till_done()
    assert _pool(scenario_full, reward_id) == {zoe: 20.0, max_: 25.0, parent: 30.0}
    assert _points(scenario_full, parent) == 0.0

    # Refunding the pool returns the match to the parent
    await pm.refund_pool(reward_id)
    await hass.async_block_till_done()
    assert _points(scenario_full, parent) == 30.0
    assert _points(scenario_full, zoe) == 100.0

    # The match never fills the pool past its cost, and the parent is not
    # recorded as receiving the reward
    _set_points(scenario_full, parent, 500.0)
    await pm.contribute_to_pool(zoe, reward_id, 40.0)
    await hass.async_block_till_done()
    await pm.contribute_to_pool(max_, reward_id, 15.0)
    await hass.async_block_till_done()
    assert _pool(scenario_full, reward_id) == {zoe: 40.0, max_: 15.0, parent: 45.0}
    await pm.approve_pool("Mom", reward_id)
    await hass.async_block_till_done()
    parent_rewards = coordinator.assignees_data[parent].get(
        const.DATA_USER_REWARD_DATA, {}
    )
    assert not parent_rewards.get(reward_id, {}).get(
        const.DATA_USER_REWARD_DATA_LAST_APPROVED
    )


async def test_closed_pool_refuses_chip_ins_until_reward_saved(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """After delivery a closing pool takes no chip-ins; saving the reward reopens it."""
    coordinator = scenario_full.coordinator
    pm = coordinator.reward_pool_manager
    zoe = scenario_full.assignee_ids["Zoë"]
    reward_id = _make_pool(scenario_full)
    coordinator.reward_manager.update_reward(
        reward_id, {rp.DATA_REWARD_POOL_AFTER_DELIVERY: rp.AFTER_DELIVERY_CLOSE}
    )
    _set_points(scenario_full, zoe, 300.0)
    await pm.contribute_to_pool(zoe, reward_id, 100.0)
    await hass.async_block_till_done()
    await pm.approve_pool("Mom", reward_id)
    await hass.async_block_till_done()

    reward = coordinator.rewards_data[reward_id]
    assert pm.sensor_attributes(reward, zoe)[rp.ATTR_REWARD_POOL_CLOSED] is True
    assert pm.status_override(reward, 100.0, 300.0) == const.REWARD_STATE_LOCKED
    with pytest.raises(HomeAssistantError) as err:
        await pm.contribute_to_pool(zoe, reward_id, 10.0)
    assert err.value.translation_key == rp.TRANS_KEY_ERROR_REWARD_POOL_CLOSED

    coordinator.reward_manager.update_reward(reward_id, {})
    assert await pm.contribute_to_pool(zoe, reward_id, 10.0) == 10.0


def test_pool_settings_validation_and_cleanup() -> None:
    """Share limit must be 0-100, a match needs a parent; values are cleaned."""
    from custom_components.choreops.reward_pools.settings import build_settings
    from custom_components.choreops.reward_pools.validation import (
        validate_pool_settings,
    )

    pooled = {const.DATA_REWARD_POOLED: True, const.DATA_REWARD_COST: 100}
    assert validate_pool_settings({**pooled, rp.DATA_REWARD_POOL_MAX_SHARE: 101}) == {
        rp.DATA_REWARD_POOL_MAX_SHARE: rp.TRANS_KEY_CFOF_REWARD_POOL_MAX_SHARE_INVALID
    }
    assert validate_pool_settings({**pooled, rp.DATA_REWARD_POOL_MATCH_RATIO: 1}) == {
        rp.DATA_REWARD_POOL_MATCH_USER_IDS: rp.TRANS_KEY_CFOF_REWARD_POOL_MATCH_NO_PARENT
    }
    assert (
        validate_pool_settings(
            {
                **pooled,
                rp.DATA_REWARD_POOL_MATCH_RATIO: 1,
                rp.DATA_REWARD_POOL_MATCH_USER_IDS: ["parent"],
            }
        )
        == {}
    )
    stored = {rp.DATA_REWARD_POOL_AFTER_DELIVERY: "bogus", "pool_max_share": -5}
    built = build_settings(stored.get)
    assert built == {
        rp.DATA_REWARD_POOL_MAX_SHARE: 0.0,
        rp.DATA_REWARD_POOL_MATCH_RATIO: 0.0,
        rp.DATA_REWARD_POOL_MATCH_USER_IDS: [],
        rp.DATA_REWARD_POOL_AFTER_DELIVERY: rp.AFTER_DELIVERY_RESTART,
    }


def test_reward_form_offers_pool_settings_and_lists_only_parents() -> None:
    """The reward form has the pool settings; the match lists approvers only."""
    from custom_components.choreops.helpers.flow_helpers import build_reward_schema
    from custom_components.choreops.reward_pools.form import match_parent_options

    users = {
        "kid": {const.DATA_USER_NAME: "Kid"},
        "mom": {const.DATA_USER_NAME: "Mom", const.DATA_USER_CAN_APPROVE: True},
    }
    keys = {str(key) for key in build_reward_schema(assignees_dict=users).schema}
    assert set(rp.POOL_SETTING_KEYS) <= keys
    values = [option["value"] for option in match_parent_options(users)]
    assert values == ["mom"]


async def test_match_is_split_between_parents_and_covered_when_one_runs_out(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """Two parents share the match evenly; one short of points, the other covers."""
    coordinator = scenario_full.coordinator
    pm = coordinator.reward_pool_manager
    zoe = scenario_full.assignee_ids["Zoë"]
    mom = scenario_full.assignee_ids["Max!"]  # Stand-ins for parents with points
    dad = scenario_full.assignee_ids["Lila"]
    reward_id = _make_pool(scenario_full)
    coordinator.reward_manager.update_reward(
        reward_id,
        {
            rp.DATA_REWARD_POOL_MATCH_RATIO: 1,
            rp.DATA_REWARD_POOL_MATCH_USER_IDS: [mom, dad],
            const.DATA_REWARD_ASSIGNED_USER_IDS: [zoe],
        },
    )
    _set_points(scenario_full, zoe, 100.0)
    _set_points(scenario_full, mom, 100.0)
    _set_points(scenario_full, dad, 4.0)

    await pm.contribute_to_pool(zoe, reward_id, 10.0)
    await hass.async_block_till_done()
    # 10 to match: Dad can only give 4, Mom covers the other 6
    assert _pool(scenario_full, reward_id) == {zoe: 10.0, dad: 4.0, mom: 6.0}

    await pm.contribute_to_pool(zoe, reward_id, 10.0)
    await hass.async_block_till_done()
    assert _pool(scenario_full, reward_id) == {zoe: 20.0, dad: 4.0, mom: 16.0}

    _set_points(scenario_full, dad, 50.0)
    await pm.contribute_to_pool(zoe, reward_id, 10.0)
    await hass.async_block_till_done()
    assert _pool(scenario_full, reward_id) == {zoe: 30.0, dad: 9.0, mom: 21.0}

    reward = coordinator.rewards_data[reward_id]
    names = pm.sensor_attributes(reward, zoe)[rp.ATTR_REWARD_POOL_MATCH_NAMES]
    assert names == ["Max!", "Lila"]
    assert not pm.sensor_attributes(reward, zoe)[rp.ATTR_REWARD_POOL_MATCH_OUT]
    _set_points(scenario_full, mom, 0.0)
    _set_points(scenario_full, dad, 0.0)
    assert pm.sensor_attributes(reward, zoe)[rp.ATTR_REWARD_POOL_MATCH_OUT]
