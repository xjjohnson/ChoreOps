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
    zoe = scenario_full.assignee_ids["Zoë"]
    max_ = scenario_full.assignee_ids["Max!"]
    reward_id = _make_pool(scenario_full)
    _set_points(scenario_full, zoe, 50.0)
    _set_points(scenario_full, max_, 50.0)

    assert await rm.contribute_to_pool(zoe, reward_id, 30.0) == 30.0
    await hass.async_block_till_done()
    assert await rm.contribute_to_pool(max_, reward_id, 20.0) == 20.0
    await hass.async_block_till_done()
    assert await rm.contribute_to_pool(zoe, reward_id, 5.0) == 5.0
    await hass.async_block_till_done()

    assert _points(scenario_full, zoe) == 15.0
    assert _points(scenario_full, max_) == 30.0
    assert _pool(scenario_full, reward_id) == {zoe: 35.0, max_: 20.0}
    reward = scenario_full.coordinator.rewards_data[reward_id]
    assert rm.get_pool_total(reward) == 55.0


async def test_contribution_is_capped_and_default_amount_is_all_affordable(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """A contribution never overfills the pool; no amount means all you can."""
    rm = scenario_full.coordinator.reward_manager
    zoe = scenario_full.assignee_ids["Zoë"]
    max_ = scenario_full.assignee_ids["Max!"]
    reward_id = _make_pool(scenario_full)
    _set_points(scenario_full, zoe, 40.0)
    _set_points(scenario_full, max_, 500.0)

    # No amount: Zoë puts in her whole balance (pool still needs 100)
    assert await rm.contribute_to_pool(zoe, reward_id) == 40.0
    await hass.async_block_till_done()
    # Max asks for 500 but only 60 is still needed
    assert await rm.contribute_to_pool(max_, reward_id, 500.0) == 60.0
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
    zoe = scenario_full.assignee_ids["Zoë"]
    max_ = scenario_full.assignee_ids["Max!"]
    reward_id = _make_pool(scenario_full)
    normal_reward_id = scenario_full.reward_ids["Extra Screen Time"]
    _set_points(scenario_full, zoe, 10.0)

    with pytest.raises(HomeAssistantError) as err:
        await rm.contribute_to_pool(zoe, normal_reward_id, 5.0)
    assert err.value.translation_key == const.TRANS_KEY_ERROR_REWARD_NOT_POOLED

    with pytest.raises(HomeAssistantError) as err:
        await rm.contribute_to_pool(zoe, reward_id, 25.0)
    assert err.value.translation_key == const.TRANS_KEY_ERROR_INSUFFICIENT_POINTS

    _set_points(scenario_full, zoe, 0.0)
    with pytest.raises(HomeAssistantError) as err:
        await rm.contribute_to_pool(zoe, reward_id)
    assert err.value.translation_key == const.TRANS_KEY_ERROR_REWARD_POOL_INVALID_AMOUNT

    rm.update_reward(reward_id, {const.DATA_REWARD_ASSIGNED_USER_IDS: [zoe]})
    _set_points(scenario_full, max_, 50.0)
    with pytest.raises(HomeAssistantError) as err:
        await rm.contribute_to_pool(max_, reward_id, 5.0)
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
    zoe = scenario_full.assignee_ids["Zoë"]
    max_ = scenario_full.assignee_ids["Max!"]
    reward_id = _make_pool(scenario_full)
    _set_points(scenario_full, zoe, 60.0)
    _set_points(scenario_full, max_, 60.0)

    broadcast = AsyncMock()
    with patch.object(
        coordinator.notification_manager, "broadcast_to_all_approvers", broadcast
    ):
        await rm.contribute_to_pool(zoe, reward_id, 60.0)
        await hass.async_block_till_done()
        broadcast.assert_not_called()

        await rm.contribute_to_pool(max_, reward_id, 60.0)
        await hass.async_block_till_done()

    broadcast.assert_awaited_once()
    assert (
        broadcast.await_args.kwargs["title_key"]
        == const.TRANS_KEY_NOTIF_TITLE_REWARD_POOL_FULL_APPROVER
    )
    assert broadcast.await_args.kwargs["placeholders"]["reward_name"] == (
        "Pick Next Movie"
    )
    assert _points(scenario_full, max_) == 20.0

    with pytest.raises(HomeAssistantError) as err:
        await rm.contribute_to_pool(max_, reward_id, 5.0)
    assert err.value.translation_key == const.TRANS_KEY_ERROR_REWARD_POOL_FULL


async def test_approve_pool_empties_it_without_charging_again(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """Approval needs a full pool, then resets it and tells each contributor."""
    coordinator = scenario_full.coordinator
    rm = coordinator.reward_manager
    zoe = scenario_full.assignee_ids["Zoë"]
    max_ = scenario_full.assignee_ids["Max!"]
    reward_id = _make_pool(scenario_full)
    _set_points(scenario_full, zoe, 70.0)
    _set_points(scenario_full, max_, 70.0)

    await rm.contribute_to_pool(zoe, reward_id, 70.0)
    await hass.async_block_till_done()
    with pytest.raises(HomeAssistantError) as err:
        await rm.approve_pool("Mom", reward_id)
    assert err.value.translation_key == const.TRANS_KEY_ERROR_REWARD_POOL_NOT_FULL

    await rm.contribute_to_pool(max_, reward_id, 30.0)
    await hass.async_block_till_done()

    notify = AsyncMock()
    with patch.object(
        coordinator.notification_manager, "notify_assignee_translated", notify
    ):
        await rm.approve_pool("Mom", reward_id)
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
    assert await rm.contribute_to_pool(zoe, reward_id, 10.0) == 10.0


async def test_approve_refunds_overfill_when_cost_was_lowered(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """Lowering the cost below the pool refunds the excess by share on approval."""
    rm = scenario_full.coordinator.reward_manager
    zoe = scenario_full.assignee_ids["Zoë"]
    max_ = scenario_full.assignee_ids["Max!"]
    reward_id = _make_pool(scenario_full)
    _set_points(scenario_full, zoe, 60.0)
    _set_points(scenario_full, max_, 20.0)

    await rm.contribute_to_pool(zoe, reward_id, 60.0)
    await rm.contribute_to_pool(max_, reward_id, 20.0)
    await hass.async_block_till_done()

    # Pool holds 80; cost drops to 40, so 40 comes back split 3:1
    rm.update_reward(reward_id, {const.DATA_REWARD_COST: 40.0})
    assert _pool(scenario_full, reward_id) == {zoe: 60.0, max_: 20.0}
    await rm.approve_pool("Mom", reward_id)
    await hass.async_block_till_done()

    assert _points(scenario_full, zoe) == 30.0
    assert _points(scenario_full, max_) == 10.0
    assert _pool(scenario_full, reward_id) == {}


def test_split_overfill_sums_exactly() -> None:
    """Rounding residue goes to the largest contributor so refunds sum exactly."""
    from custom_components.choreops.managers.reward_manager import RewardManager

    refunds = RewardManager._split_overfill({"a": 1.0, "b": 1.0, "c": 1.0}, 1.0)
    assert round(sum(refunds.values()), 2) == 1.0
    assert RewardManager._split_overfill({"a": 5.0}, 0.0) == {}


async def test_refund_returns_exact_contributions_without_counting_as_earned(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """Refunds restore balances and reverse points spent, not points earned."""
    rm = scenario_full.coordinator.reward_manager
    zoe = scenario_full.assignee_ids["Zoë"]
    max_ = scenario_full.assignee_ids["Max!"]
    reward_id = _make_pool(scenario_full)
    _set_points(scenario_full, zoe, 50.0)
    _set_points(scenario_full, max_, 50.0)
    earned_before = _all_time_points(scenario_full, zoe).get(
        const.DATA_USER_POINT_PERIOD_POINTS_EARNED, 0.0
    )

    await rm.contribute_to_pool(zoe, reward_id, 25.5)
    await rm.contribute_to_pool(max_, reward_id, 10.0)
    await hass.async_block_till_done()

    assert await rm.refund_pool(reward_id) == {zoe: 25.5, max_: 10.0}
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
    assert await rm.refund_pool(reward_id) == {}


async def test_deleting_pooled_reward_refunds_everyone(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """Deleting a pooled reward gives contributors their points back."""
    rm = scenario_full.coordinator.reward_manager
    zoe = scenario_full.assignee_ids["Zoë"]
    reward_id = _make_pool(scenario_full)
    _set_points(scenario_full, zoe, 50.0)

    await rm.contribute_to_pool(zoe, reward_id, 40.0)
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
    zoe = scenario_full.assignee_ids["Zoë"]
    reward_id = _make_pool(scenario_full)
    _set_points(scenario_full, zoe, 50.0)
    await rm.contribute_to_pool(zoe, reward_id, 15.0)
    await hass.async_block_till_done()

    rm.update_reward(reward_id, {const.DATA_REWARD_DESCRIPTION: "Popcorn included"})
    assert _pool(scenario_full, reward_id) == {zoe: 15.0}

    # Turning the pool off keeps the points so they can still be refunded
    rm.update_reward(reward_id, {const.DATA_REWARD_POOLED: False})
    assert _pool(scenario_full, reward_id) == {zoe: 15.0}
    await rm.refund_pool(reward_id)
    await hass.async_block_till_done()
    assert _points(scenario_full, zoe) == 50.0


async def test_pooled_reward_cannot_be_redeemed_or_charged_to_one_person(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """Redeem and a full-cost approve are refused; free badge-style grants still work."""
    rm = scenario_full.coordinator.reward_manager
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
        const.SERVICE_CONTRIBUTE_TO_REWARD_POOL,
        {"user_name": "Zoë", "reward_name": "Family Pizza Night"},
        blocking=True,
        return_response=True,
    )
    assert response == {const.SERVICE_FIELD_POINTS_AMOUNT: 30.0}
    await hass.services.async_call(
        const.DOMAIN,
        const.SERVICE_CONTRIBUTE_TO_REWARD_POOL,
        {"user_name": "Max!", "reward_name": "Family Pizza Night", "amount": 20},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert _points(scenario_full, zoe) == 0.0
    assert _points(scenario_full, max_) == 10.0

    await hass.services.async_call(
        const.DOMAIN,
        const.SERVICE_APPROVE_REWARD_POOL,
        {"reward_name": "Family Pizza Night", "approver_name": "Mom"},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert _pool(scenario_full, reward_id) == {}

    await hass.services.async_call(
        const.DOMAIN,
        const.SERVICE_CONTRIBUTE_TO_REWARD_POOL,
        {"user_name": "Max!", "reward_name": "Family Pizza Night", "amount": 10},
        blocking=True,
    )
    await hass.services.async_call(
        const.DOMAIN,
        const.SERVICE_REFUND_REWARD_POOL,
        {"reward_name": "Family Pizza Night"},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert _points(scenario_full, max_) == 10.0


async def test_reward_status_sensor_shows_pool(
    hass: HomeAssistant,
    scenario_full: SetupResult,
) -> None:
    """The reward status sensor exposes pool progress and reports a full pool."""
    coordinator = scenario_full.coordinator
    rm = coordinator.reward_manager
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

    await rm.contribute_to_pool(zoe, reward_id, 25.0)
    await hass.async_block_till_done()
    coordinator.async_update_listeners()
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == const.REWARD_STATE_AVAILABLE
    assert state.attributes[const.ATTR_REWARD_POOLED] is True
    assert state.attributes[const.ATTR_REWARD_POOL_TOTAL] == 25.0
    assert state.attributes[const.ATTR_REWARD_POOL_REMAINING] == 75.0
    assert state.attributes[const.ATTR_REWARD_POOL_MY_CONTRIBUTION] == 25.0
    assert state.attributes[const.ATTR_REWARD_POOL_CONTRIBUTIONS] == {"Zoë": 25.0}

    await rm.contribute_to_pool(max_, reward_id, 60.0)
    await hass.async_block_till_done()
    await rm.contribute_to_pool(zoe, reward_id, 15.0)
    await hass.async_block_till_done()
    coordinator.async_update_listeners()
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == const.REWARD_STATE_REQUESTED
    assert state.attributes[const.ATTR_REWARD_POOL_FULL] is True


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
    zoe = scenario_full.assignee_ids["Zoë"]
    reward_id = _make_pool(scenario_full)
    _set_points(scenario_full, zoe, 100.0)
    await rm.contribute_to_pool(zoe, reward_id)
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
    zoe = scenario_full.assignee_ids["Zoë"]
    max_ = scenario_full.assignee_ids["Max!"]
    reward_id = _make_pool(scenario_full)
    _set_points(scenario_full, zoe, 50.0)
    _set_points(scenario_full, max_, 50.0)

    await rm.contribute_to_pool(zoe, reward_id, 25.0)
    await rm.contribute_to_pool(max_, reward_id, 10.0)
    await hass.async_block_till_done()

    assert await rm.refund_pool(reward_id, zoe) == {zoe: 25.0}
    await hass.async_block_till_done()

    assert _points(scenario_full, zoe) == 50.0
    assert _points(scenario_full, max_) == 40.0
    assert _pool(scenario_full, reward_id) == {max_: 10.0}
    # Refunding someone who has nothing in the pool is a no-op
    assert await rm.refund_pool(reward_id, zoe) == {}
    assert _pool(scenario_full, reward_id) == {max_: 10.0}
