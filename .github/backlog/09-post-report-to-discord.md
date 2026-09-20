---
title: "Post the monthly report to #clan-reports, with splitting and a CSV attachment"
labels: [phase-4, "area:reporting"]
depends_on: [discord-rest-client, monthly-aggregation]
---

## Context

`report --dry-run` renders the report, but `--post` currently exits with
"Posting to Discord is not implemented yet". This issue closes the last step of the pipeline.
The Discord report is meant to stay short - top 3 to 5 - while the full per-member table
travels as an attachment.

## Scope

- `post_message(channel_id, content)` and multipart attachment upload on `DiscordClient`.
- Safe splitting: a report longer than Discord's 2000-character message limit is split on
  section boundaries, never mid-entry, and posted in order.
- CSV export of all ranking-eligible members using the exact column list in
  `docs/REPORT_SPEC.md`, attached to the report.
- `clash-reporter report --post` wired to `Settings.require_discord()`, which already fails
  closed on missing configuration.
- `clash-reporter run --month previous [--post]` running fetch, normalize, report, and post
  as one command, for the scheduled workflow to call.

## Out of scope

Changing the report layout or the scoring formula.

## Acceptance criteria

- [ ] Posting is tested through a mocked transport; no live Discord calls in the suite.
- [ ] A report exceeding the character limit splits into multiple messages, each under the
      limit, with no section header orphaned from its content.
- [ ] The CSV contains every column listed in `docs/REPORT_SPEC.md`, in that order.
- [ ] `--post` without `DISCORD_BOT_TOKEN` or `DISCORD_REPORT_CHANNEL_ID` exits non-zero with
      a clear message and posts nothing.
- [ ] `--dry-run` never performs a network call, asserted by a test.
- [ ] A partial failure mid-split is surfaced, not swallowed.

## Dependencies

- Discord REST client
- Monthly aggregation, for a real end-to-end `run`

## References

- `docs/REPORT_SPEC.md` - sections and "Full-data attachment"
- `ROADMAP.md` phase 4
