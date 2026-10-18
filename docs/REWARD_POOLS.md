# Family Pool Rewards

A **family pool** reward is one the whole household saves up for together.
Instead of one person paying the full cost, everyone assigned to the reward pays
points from their own balance into **one shared pool**. When the pool reaches the
reward's cost, approvers are notified, and once they've delivered the reward they
approve the pool. The pool then empties so the family can save up for it again.

Family goals (see [FAMILY_GOALS.md](FAMILY_GOALS.md)) pool points *earned*.
Family pools are different: people *spend* their points into them.

## Creating one

1. **Settings → Devices & Services → ChoreOps → Configure → Manage Reward → Add Reward**
   (or edit an existing reward)
2. Tick **Family pool**.
3. Set **Reward Cost**. This is the pool's target.
4. Set **Assigned to**. Only these people can pay into the pool.

The `create_reward` and `update_reward` services also take `pooled: true`.

## Paying in

Call `choreops.contribute_to_reward_pool` with `user_name`, `reward_name` and,
optionally, `amount`:

- The points leave the person's balance **immediately**.
- A contribution never takes more than the pool still needs. Asking for 50 when
  only 10 is left takes 10.
- Leaving `amount` empty contributes as much as the person can afford, up to
  what the pool still needs.
- The service returns the points actually contributed.

A family pool reward can't be redeemed the normal way. Its redeem button and
`redeem_reward` both refuse it, because one person would be charged the full
cost.

## When the pool is full

Every approver gets a "Family Pool Full" notification. After delivering the
reward, an approver calls `choreops.approve_reward_pool` with the
`reward_name`. Each contributor gets the normal "reward approved" notification,
and the pool starts again from zero.

If the cost was lowered after the pool filled, the extra is refunded on
approval in proportion to what each person paid in.

## Refunds

- `choreops.refund_reward_pool` cancels the pool and gives everyone back exactly
  what they paid in.
- Deleting a pooled reward refunds everyone automatically.
- Unticking **Family pool** keeps the points in the pool, so they can still be
  refunded.

Refunds reverse "points spent". They don't count as "points earned", so they
don't move badges or family goals.

## What you can see

Each person's reward status sensor for a pooled reward is:

| State | Meaning |
| --- | --- |
| `requested` | The pool is full and waiting for an approver |
| `available` | The person has points to put in |
| `locked` | The person has no points |

It also has these attributes:

| Attribute | Meaning |
| --- | --- |
| `pooled` | `true` for a family pool reward |
| `cost` | The pool's target |
| `pool_total` | Points in the pool so far |
| `pool_remaining` | Points still needed |
| `pool_full` | Whether the target is reached |
| `pool_my_contribution` | This person's share of the current pool |
| `pool_contributions` | Everyone's share, keyed by display name |
