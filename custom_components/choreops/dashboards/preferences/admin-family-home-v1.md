# admin-family-home-v1 preferences

`admin-family-home-v1` is a single-page family home: tappable person cards, family goals tiles, and family achievements.

Each person card opens that person's Family Hub page (`family-hub-<name>`). Generate the Family Hub dashboard for each person first, and generate this page into the same dashboard so the relative paths resolve.

## Editable settings (in the generated card templates)

- `pref_dashboard_path` (person cards and goals tiles): set to your dashboard URL path (for example `dashboard-choreops`) if tapping a card does not open the right page. Leave empty to use paths relative to the current dashboard.
- `pref_points_precision` (person cards): `fixed_0`, `fixed_1` or `fixed_2`.
- `pref_urgent_days` (goals tiles): days left at which a goal's clock turns to the warning color.

## Tip

To make each person's page a subpage (hidden from the tab bar with a back arrow), set `subview: true` and `back_path: home` on that person's view in the dashboard's raw configuration editor.
