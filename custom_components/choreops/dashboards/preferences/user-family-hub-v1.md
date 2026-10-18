# user-family-hub-v1 preferences

`user-family-hub-v1` is a shared family page. Every person sees the same hub, so it works as a wall-tablet or kitchen-display view.

## What it shows

- **Family Goals:** every family goal with its level chips, progress bar, next reward, record line, and each person's contribution this level.
- **Pool Rewards:** progress bar toward each pooled reward, plus your own share.
- **Leaderboard:** everyone's points side by side, ranked.
- **Today:** per person, overdue and due-today chore counts, or "All Caught Up".

## Behavior

- Read-mostly: it has no approve, claim, or admin buttons.
- A section hides itself when it has nothing to show (no family goals, no pooled rewards).
- Section labels use the dashboard translations when a key exists and fall back to English.

## Dependency policy

- Required custom dependencies: `auto-entities` and `button-card`.
