# admin-shared-family-hub-v1 preferences

`admin-shared-family-hub-v1` ("Admin (Family Hub)") is the OpsCenter that goes with the Family Hub dashboard. It is a separate template from `admin-shared-v1`, which is unchanged. Pick it under **Shared Admin Dashboard Template** when you generate the dashboard.

## What it shows

- Approval Center: counts, split by chores and rewards, with per-person approve all and an Approve all button.
- Bonuses & Penalties: quick-apply cards for every person.
- Family goals & achievements: progress rows with a reset button per goal.
- Reward pools: approve, refund and per-person refund.
- Management: a person strip plus three tabs.
  - Chores: pause or resume, reset overdue, shift due dates, skip next due, all chores, and a chip picker for one chore with its details and actions.
  - Economy: balance header with Bonuses, Penalties and Points tabs, and an Activity report tile that posts the last 7 days to the Home Assistant notifications bell.
  - System: fix-it tools (remove badge, repair streak) and family-wide tools (reset all to pending, integration settings, documentation, support).

## Notes

- The view path is `admin`, so the OpsCenter card on the Family Home tab opens it.
- Layout is three columns on wide screens and one column on a phone.
- Cards use Home Assistant theme variables; no extra custom cards are needed beyond Auto-Entities and Button Card.
- UI state (open tiles, selected tab) is stored in the shared admin `ui_control` under `admin-shared/...`.
