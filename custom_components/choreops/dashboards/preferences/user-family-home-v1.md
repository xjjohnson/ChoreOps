# user-family-home-v1 preferences

`user-family-home-v1` is the Family Home tab: tappable person cards, family goals tiles, and family achievements.

It is not picked from a template list. Whenever a dashboard is generated or updated with the Family Hub template, one Home tab (path `home`) is added as the first tab, followed by each person's Family Hub page, with OpsCenter last.

Each person card opens that person's Family Hub page (`family-hub-<name>`).

## Editable settings (in the generated card templates)

- `pref_dashboard_path` (person cards and goals tiles): set to your dashboard URL path (for example `dashboard-choreops`) if tapping a card does not open the right page. Leave empty to use paths relative to the current dashboard.
- `pref_points_precision` (person cards): `fixed_0`, `fixed_1` or `fixed_2`.
- `pref_urgent_days` (goals tiles): days left at which a goal's clock turns to the warning color.
