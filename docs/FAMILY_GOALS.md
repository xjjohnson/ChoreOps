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

## Restarting a goal

Call the `choreops.reset_family_goal` service with the goal's name
(`achievement_name`). Points and chores goals remember what each person had
already contributed and count only new activity from then on; the caught-up goal
clears its streak (tomorrow is day one). Everyone's award is cleared so the goal
can be earned again. Reward points already paid out are kept.

## "Everyone caught up for X days"

Type **Family Goal: Everyone Caught Up for X Days**; the target value is the
number of days. A day counts once every assigned person has finished everything
due that day and nobody has anything overdue. Days where nothing is owed are
neutral; a scheduled chore that passes unmet breaks the streak (same rule as
badge streaks). When the streak reaches the target, everyone assigned is awarded.

## Repeating streak badges

A streak-type badge whose reset schedule is **None** now repeats: when the
streak target is hit the badge is awarded and the streak restarts from zero
(tomorrow is day one of the next streak), so e.g. "7 days in a row" earns the
badge again after each further 7-day run. Streak badges with a weekly/monthly
reset schedule keep the once-per-cycle behavior.

## Levels

Family goals (points, chores and caught-up) can have levels. In the goal's
**Levels** box, list one entry per level as `target:reward`, separated by commas,
for example `100:10, 250:25, 500:50`. When the pooled total reaches a level's
target, everyone assigned is awarded that level's reward and the goal stays open
for the next level; the last level closes the goal. A level written without a
reward (just `250`) pays the goal's own Extra Points value. Leave the box blank
for a single level at the Target Value, which is how family goals worked before.
The first level's target replaces the Target Value. Restarting a goal sends it
back to level 1.

The goal's sensors expose `family_level` (levels completed), `family_levels`,
`family_next_target` and `family_next_reward` for dashboards; the bar fills
toward the next level's target.

### Top contributor multiplier

Set **Top Contributor Multiplier** above 1 (for example `2`) to give the
biggest contributor to each level a larger reward. Contribution is measured per
level: points or chores added since the previous level was reached. The top
contributor's reward for that level is the level reward times the multiplier;
ties share the bonus, and someone with zero contribution never gets it. The
multiplier applies to every level and is exposed as `family_top_multiplier`,
with the per-level shares in `family_level_contributions`. Level 1 counts
everything since the goal was created or restarted.
