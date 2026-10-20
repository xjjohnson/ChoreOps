# Achievements

An **achievement** is recognition an approver gives by hand. Nothing earns it
automatically: there are no targets, streaks, schedules or other triggers. Use it
for the things the rules can't see, like "Helped a sibling" or "Cleaned the whole
kitchen".

## Creating one

**Settings → Devices & Services → ChoreOps → Configure → Manage Achievement → Add**

| Field | Meaning |
| --- | --- |
| Name | Shown on the badge. |
| Description | Optional line shown under the name. |
| Icon | Shown inside the gold badge. |
| Labels | Optional, for grouping. |
| Points | Paid to the person every time you give it. Use 0 for none. |

Every person can be given every achievement, so there is no "assigned to" list.

## Giving one

- **OpsCenter:** open the **Economy** tab, pick the person, choose the
  **Achievements** segment and tap an achievement. Confirm and it is given.
- **Automations:** call `choreops.award_achievement` with `user_name` and
  `achievement_name`. `approver_name` is optional. The response includes
  `times_awarded`.

Giving an achievement pays its points, notifies the person and the approvers, and
raises the person's count. The same achievement can be given again: each time pays
the points again and adds one to the count (shown as ×N).

## How it looks

On a person's Family Hub, earned achievements appear as **gold-framed badges**
(newest first) on the showcase card and in the Achievements section, with a ×N marker
when given more than once. Achievements not yet given show dimmed in the
Achievements section.

## Sensors

| Sensor | State | Useful attributes |
| --- | --- | --- |
| Achievement progress (one per person per achievement) | Times given to that person | `awarded`, `award_count`, `last_awarded`, `reward_points` |
| Achievement (one per achievement) | Times given in total | `awarded_to` (name → count), `reward_points` |

## Upgrading from earlier versions

Existing achievements keep their name, icon, description, labels, reward points and
who already earned them (counted as once). Their type, target, chore and assigned
people settings are dropped, and they stop being awarded automatically. The next time
you save one in the options form, those old fields are removed.

The original Premier dashboards still read achievement progress, so they show given
achievements as earned but no progress bars.
