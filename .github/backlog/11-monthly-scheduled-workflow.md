---
title: "Scheduled monthly run with artifacts and fail-closed behavior"
labels: [phase-5, "area:ci"]
depends_on: [fetch-raw-fixtures, monthly-aggregation, post-report-to-discord]
---

## Context

The last mile of V1: the job must wake once a month with no persistent infrastructure, build
the previous month's report, post it, and exit. The failure policy matters as much as the
happy path - a report missing `#wars` data would quietly understate everyone, so it must
fail instead of posting.

## Scope

- `.github/workflows/monthly-report.yml` with both `workflow_dispatch` (accepting an optional
  `month` input) and a monthly `cron`.
- Schedule chosen so the run always falls on or after the 1st in `America/Toronto`; the
  application still resolves the month itself rather than trusting the cron timezone.
- Secrets and variables wired from the names in `.env.example`.
- Steps: checkout, set up Python, install, run tests, then
  `clash-reporter run --month previous --post`.
- Upload `artifacts/raw`, `artifacts/normalized`, `artifacts/diagnostics`, and the rendered
  report as workflow artifacts on both success and failure.
- Fail closed: an inaccessible required channel, or missing critical data, aborts before
  posting. A `--allow-partial` flag may permit posting anyway, defaulting to off.
- `docs/DEVELOPMENT.md` section on required repository secrets and variables.

## Out of scope

Multi-clan support and persisted history. Both are explicitly post-V1 in `ROADMAP.md`.

## Acceptance criteria

- [ ] A manual `workflow_dispatch` run completes end to end and posts one report to
      `#clan-reports`.
- [ ] Artifacts are uploaded even when the job fails, since diagnostics matter most then.
- [ ] Simulating an inaccessible `#wars` fails the run and posts nothing.
- [ ] A month with no Clan Games event is a valid run, not a failure.
- [ ] The bot token is never echoed into logs.
- [ ] The cron time is documented together with the reasoning about UTC versus
      `REPORT_TIMEZONE`.

## Dependencies

- `fetch` command
- Monthly aggregation
- Posting to Discord
- Phase 0 Discord setup, for the secrets

## References

- `ROADMAP.md` phase 5
- `docs/ARCHITECTURE.md` - "Failure policy"
- `docs/DEVELOPMENT.md` - "Secrets and variables"
