---
title: "Monthly aggregation and the `normalize` command"
labels: [phase-2, "area:aggregation", needs-fixtures]
depends_on: [parser-framework-members, war-cwl-parsers, games-capital-donations-parsers]
---

## Context

This is the missing middle of the pipeline. `clash_reporter.scoring` and
`clash_reporter.reporting` already consume a `MonthlyDataset`, but nothing builds one - today
the JSON has to be written by hand. Aggregation turns normalized events into that dataset and
is where membership fairness is decided: a member who joined on the 28th must not be ranked
against someone present all month.

## Scope

New package `src/clash_reporter/aggregation/`:

- `membership.py`: reconstruct membership intervals from join/leave events, including
  leave-then-rejoin, and compute `eligible_days` against the reporting window. Members
  present before the window started but never observed joining must be treated as present
  for the whole window, not as unknown.
- `monthly_summary.py`: build a `MonthlyPlayerSummary` per player tag observed in the window,
  filling regular war, CWL, Clan Games, capital, and donation fields, keeping regular war and
  CWL strictly separate.
- Resolve the latest display name for output while keeping the tag as identity.
- Populate `MonthlyDataset` context: `regular_wars`, `cwl_rounds`, `clan_games_completed`,
  `raid_weekends`, and `data_notes` from parser diagnostics.
- Per-player `warnings` for attributable data-quality problems.
- `clash-reporter normalize --input ./artifacts/raw --output ./artifacts/normalized`, writing
  `events.json`, `monthly_players.json`, and `diagnostics/parser_warnings.json`.

## Out of scope

Changing the scoring formula or the report layout. Both already exist and this issue should
feed them unchanged.

## Acceptance criteria

- [ ] Tests cover join mid-month, leave mid-month, leave then rejoin, a name change during
      the month, a player present for the entire window with no join event, and duplicate
      messages.
- [ ] `eligible_days` is computed in `REPORT_TIMEZONE` and matches the window, not UTC days.
- [ ] Regular war and CWL totals never bleed into each other.
- [ ] A month with no wars yields `wars_participated = 0` without penalizing anyone, and a
      test asserts nobody is flagged for review solely because of it.
- [ ] Missing source data stays `None` and surfaces as a warning; only observed zeros become
      `0`.
- [ ] `normalize` output validates against `MonthlyDataset` and is accepted by the existing
      `report --dry-run` command without modification.
- [ ] Output is deterministic for a fixed input set.

## Dependencies

- Parser framework and members parser
- War and CWL parsers
- Clan Games, capital, and donations parsers

## References

- `docs/DATA_CONTRACT.md` - `MonthlyPlayerSummary`, "Reporting eligibility"
- `ROADMAP.md` phase 2
- `docs/DEVELOPMENT.md` - "Aggregation tests"
