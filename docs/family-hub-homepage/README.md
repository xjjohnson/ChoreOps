# Family Hub homepage cards

Standalone cards for an OpsCenter-style homepage. Paste each file into **Edit dashboard → Add card → Manual**.

- `goals-card.yaml`: quests across everyone as two-column tiles, ending soonest first. Tapping a tile opens the Family Hub page of the quest leader (`family-hub-<slug>`). Set `pref_dashboard_path` if relative paths do not work on your dashboard.
- `bonuses-penalties-card.yaml`: quick-apply rows. Tap a person's initial and confirm to press their bonus or penalty button.

To hide personal pages from the tab bar, add `subview: true` and `back_path` to each personal view in the raw configuration editor.
