---
title: "Epic: ship V1 of the monthly ClashPerk report"
labels: [epic]
tracks:
  - clashperk-channel-setup
  - reporting-window
  - discord-rest-client
  - fetch-raw-fixtures
  - parser-framework-members
  - war-cwl-parsers
  - games-capital-donations-parsers
  - name-only-log-tag-attribution
  - monthly-aggregation
  - post-report-to-discord
  - ci-workflow
  - monthly-scheduled-workflow
---

## Goal

Replace the manual ClashPerk export → Google Sheets → calculation workflow with a scheduled
job that reads a month of ClashPerk Discord logs and posts a monthly report to
`#clan-reports`.

V1 is done when a GitHub Actions run, triggered manually and on a monthly cron, produces a
report for the previous calendar month whose numbers are trusted enough to act on.

## Where the project stands

Already merged:

- project scaffold, packaging, and dev tooling (`pyproject.toml`, `.cursor/install.sh`)
- configuration with scoring weights and thresholds (`clash_reporter.config`)
- aggregate models for a normalized month (`clash_reporter.models`)
- transparent metrics, eligibility, and ranking (`clash_reporter.scoring`)
- report rendering (`clash_reporter.reporting`)
- `clash-reporter report --input <normalized.json> --dry-run`

Missing: everything upstream of a normalized dataset. Today the JSON that drives the report
has to be written by hand. Nothing talks to Discord, nothing parses a ClashPerk message, and
nothing turns events into a `MonthlyPlayerSummary`.

## Critical path

```text
clashperk-channel-setup (human)
        │
        ├── reporting-window ──┐
        └── discord-rest-client┴── fetch-raw-fixtures ── parser-framework-members ──┬── war-cwl-parsers ──────────────┐
                                                                                    └── games-capital-donations-parsers┤
                                                                                                                       │
                                                                          monthly-aggregation ─────────────────────────┘
                                                                                    │
                                        post-report-to-discord ── monthly-scheduled-workflow
```

`name-only-log-tag-attribution` is deferred until a real duplicate display name appears;
it is not on the critical path. `ci-workflow` is independent and can land at any time.

## Tracked issues

- [ ] {{issue:clashperk-channel-setup}} - Phase 0 Discord and ClashPerk setup
- [ ] {{issue:reporting-window}} - timezone-aware reporting window
- [ ] {{issue:discord-rest-client}} - Discord REST client with pagination
- [ ] {{issue:fetch-raw-fixtures}} - `fetch` command that captures raw payloads
- [ ] {{issue:parser-framework-members}} - parser framework, diagnostics, members parser
- [ ] {{issue:war-cwl-parsers}} - regular war and CWL parsers
- [ ] {{issue:games-capital-donations-parsers}} - Clan Games, Capital, donations parsers
- [ ] {{issue:name-only-log-tag-attribution}} - name-only log → tag attribution (deferred)
- [ ] {{issue:monthly-aggregation}} - monthly aggregation and `normalize`
- [ ] {{issue:post-report-to-discord}} - post the report to `#clan-reports`
- [ ] {{issue:ci-workflow}} - CI on pull requests
- [ ] {{issue:monthly-scheduled-workflow}} - scheduled monthly run

## Acceptance criteria

- [ ] `clash-reporter run --month previous --post` produces and posts a report end to end.
- [ ] A manual `workflow_dispatch` run succeeds and uploads raw, normalized, and diagnostic
      artifacts.
- [ ] Every captured fixture is parsed or explicitly recorded as unsupported. No silent drops.
- [ ] Report values were compared against ClashPerk `/export season` and `/export wars` for
      the same month, and every remaining difference is explained in a comment on this issue
      (`ROADMAP.md` phase 6).
- [ ] No Clash of Clans API except the deferred duplicate-name exception in `AGENTS.md`;
      no Gateway connection; no database.

## References

- `ROADMAP.md`
- `docs/CODING_AGENT_BRIEF.md`
- `docs/ARCHITECTURE.md`
