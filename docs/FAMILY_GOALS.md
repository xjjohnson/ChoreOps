# Family Goal Achievements

A **family goal** is an achievement the whole household works on together. Instead of
each person tracking their own progress toward their own copy of a target, every
assigned person's contribution is added into **one pooled total**. When the pooled
total reaches the target, **everyone assigned is awarded at the same time**.

## Creating one

1. **Settings → Devices & Services → ChoreOps → Configure → Manage Achievement → Add Achievement**
2. Under **Type**, choose one of:
   - **Family Goal: Total Points Earned** - pools all-time points earned by everyone assigned.
   - **Family Goal: Total Chores Completed** - pools all-time approved chores by everyone assigned.
     Optionally pick a **Selected Chore** to count only that chore.
3. Set **Assigned Assignees** to the people who are working on the goal.
4. Set **Target Value** (for example `100000` points, or `500` chores).
5. Set **Reward Points**. Each assigned person receives the full amount once when the goal completes.

## How counting works

- Counts are **all-time**: everything each assigned person has ever earned/completed
  counts, including history from before the goal was created. A goal can therefore
  start partway to its target.
- "Points earned" counts points added to balances (chores, bonuses, manual adds,
  other awards). Spending points on rewards or penalties does **not** reduce it.
- Only people listed under **Assigned Assignees** contribute and receive the award.
- Evaluation runs whenever any assigned person is re-evaluated (for example when a
  chore is approved), so the goal completes as soon as the pooled total is reached.

## What you can see

The achievement sensor's state is the pooled percentage (0-100) toward the single
target. It also exposes:

| Attribute | Meaning |
| --- | --- |
| `family_total` | Pooled total so far |
| `family_contributions` | Each person's share, keyed by display name |

Each person's achievement progress sensor shows the same pooled percentage and
exposes `family_total`; its `raw_progress` attribute is that person's own share.

## Things to know

- The goal is awarded once per person and is permanent, like other achievements.
- Resetting achievement data clears the awards. Because counting is all-time, a goal
  whose target is already met will be awarded again on the next evaluation.
- A person added to a goal that is already complete is awarded on the next
  evaluation.
- Existing achievement types are unchanged.
