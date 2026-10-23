# Family Goals

A **family goal** is a goal the whole household works on together. Instead of
each person tracking their own progress toward their own copy of a target, every
assigned person's contribution is added into **one pooled total**. When the pooled
total reaches the target, **everyone assigned is awarded at the same time**.

## Creating one

1. **Settings → Devices & Services → ChoreOps → Configure → Manage Family Goals → Add**
   (family goals are stored separately from achievements, which are untouched)
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
- "Points earned" counts points added to balances from chores, bonuses and manual
  adds. Award points (family goal payouts, achievements and badges) don't count,
  so a level's own payout never carries the goal toward the next level. Spending
  points on rewards or penalties does **not** reduce it.
- Only people listed under **Assigned Assignees** contribute and receive the award.
- Evaluation runs whenever any assigned person is re-evaluated (for example when a
  chore is approved), so the goal completes as soon as the pooled total is reached.

## What you can see

The family goal sensor's state is the pooled percentage (0-100) toward the single
target. It also exposes:

| Attribute | Meaning |
| --- | --- |
| `family_total` | Pooled total so far |
| `family_contributions` | Each person's share, keyed by display name |
| `family_repeat` | `never`, `weekly` or `monthly` |
| `family_end_date` | The finish date or the end of the repeat period, whichever comes first |
| `family_days_left` | Days left including today (empty without an end) |
| `family_pace` | `ahead`, `on_track`, `behind`, or empty when there is no pace |
| `family_finished` | The finish date has passed and progress is frozen |
| `family_pace_expected` | The total an even pace would have by now (the dashed line on the card) |
| `family_deadline` | What `family_end_date` is: `finish`, `week` or `month` (cards say "5 days left this week") |

Each person's goal progress sensor shows the same pooled percentage and
exposes `family_total`; its `raw_progress` attribute is that person's own share.

## Things to know

- The goal is awarded once per person and is permanent, like other achievements.
- Resetting achievement data clears the awards. Because counting is all-time, a goal
  whose target is already met will be awarded again on the next evaluation.
- A person added to a goal that is already complete is awarded on the next
  evaluation.
- Goals pay out through the same completion signal as challenges, so points and
  notifications work the same way. Existing achievements are unchanged.

## Upgrading from earlier versions

Family goals used to be stored as achievements. On the first start after upgrading,
they are converted into family goals automatically, keeping their progress, levels,
streaks and records. The old achievement entities are removed, and the goals appear
under **Manage Family Goals** with new "Family Goal" sensors. Regenerate your
dashboards afterwards.

## Restarting a goal

Call the `choreops.reset_family_goal` service with the goal's name
(`goal_name`). Points and chores goals remember what each person had
already contributed and count only new activity from then on; the caught-up goal
clears its streak (tomorrow is day one). Everyone's award is cleared so the goal
can be earned again. Reward points already paid out are kept.

## Goal settings

- **Also count chores with these labels** (Total Chores Completed): counts every
  chore with one of the labels, together with the chosen chore if there is one.
  A chore given the label later brings its past approvals with it.
- **Repeat** (Never / Every week / Every month): at the start of each week
  (Monday) or month the goal starts over, exactly like a reset. Points already
  paid are kept. Only for Total Points, Total Chores and Everyone Completes
  goals; the streak and one-day goals ignore it. Changing the setting starts
  counting periods from then, without restarting the goal.
- **Finish date**: the last day that counts. The day after, everyone's share is
  frozen and nothing more is paid until the goal repeats or is reset (a reset
  moves past a finish date that already passed). Moving the date later lets it
  count again.
- **Pace**: with a finish date or a repeat, the sensors show days left and
  whether the total is ahead, on track or behind an even pace from the start of
  the run to the deadline (10 % either side counts as on track). Streak and
  one-day goals get days left but no pace.
- **Who is told when a level is reached**: everyone (the default), only the
  people working on it, only parents, or nobody. The points are paid either way.

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

## More family goal types

- **Everyone Completes at Least X Chores** - counts the *smallest* share, so the
  goal only advances as fast as the person who has done the least. Everyone
  must reach the target before anyone is rewarded.
- **X Chores Together in One Day** - the whole family's approved chores for
  today. It is a daily goal: at the start of each day it starts over (level,
  awards and progress clear) and can be earned and rewarded again. Top
  contributor means most chores that day. The best day is remembered as a
  record (`family_record`, `family_record_day`, `family_record_top` on the
  goal's sensors); it survives the daily restart, a reset from the Parents tab
  (`choreops.reset_family_goal`) clears it, and a tying day does not replace it.
- **Everyone Completes a Chore for X Days** - a day counts once every assigned
  person has had at least one chore approved. A day that ends without that
  voids the streak (noticed on the next evaluation). Easier than "everyone
  caught up" because it does not look at what was due.

The single-person types (Chore Streak, Chore Total, Daily Minimum) are still
accepted so existing achievements keep working, but are labelled "(Old)" and
sit at the bottom of the list.
