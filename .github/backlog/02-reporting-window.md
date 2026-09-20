---
title: "Reporting window: timezone-aware month resolution"
labels: [phase-1, "area:discord", agent-ready]
---

## Context

Every downstream step needs to agree on exactly which messages belong to a reporting month:
the collector uses it to stop paginating, aggregation uses it to count eligible days, and the
scheduled workflow uses it to resolve "previous month" without trusting the cron timezone.
GitHub Actions cron is UTC, so the application must own this calculation.

Nothing in `clash_reporter` computes a window today; `report` takes a pre-built dataset whose
`month_label` is just a string.

## Scope

New module `src/clash_reporter/window.py`:

- `ReportingWindow` with the half-open interval `[start_of_month, start_of_next_month)`
  in `Settings.report_timezone`, the equivalent UTC instants, and a `month_label`
  (`"August 2026"`) plus `month_key` (`"2026-08"`).
- `resolve_month(value: str, *, now, timezone) -> ReportingWindow` accepting `YYYY-MM`,
  `previous`, and `current`.
- `contains(timestamp)` for UTC-aware Discord timestamps.
- Discord snowflake helpers: `snowflake_for(instant)` and `instant_for(snowflake)`, so the
  collector can seed pagination with `before`/`after` instead of scanning from the present.
- Wire `--month` into the existing CLI so `report` can label output from the window.

## Out of scope

Fetching or filtering actual messages. That is the collector's job.

## Acceptance criteria

- [ ] `resolve_month("previous", ...)` returns the previous calendar month in
      `REPORT_TIMEZONE`, not in UTC. Test the case that distinguishes them: a `now` of
      `2026-09-01T02:00:00Z`, which is still August 31 in `America/Toronto`, must resolve to
      July 2026.
- [ ] DST boundaries are covered: a March and a November window in `America/Toronto` have
      correct UTC offsets at each end.
- [ ] The interval is half-open. A message at exactly `start_of_next_month` is excluded.
- [ ] Invalid input (`"2026-13"`, `"august"`) raises a clear error instead of silently
      defaulting.
- [ ] Snowflake helpers round-trip against a known Discord ID/timestamp pair.
- [ ] `zoneinfo` resolves in CI. `tzdata` is already a runtime dependency.

## Dependencies

None.

## References

- `docs/ARCHITECTURE.md` - "Reporting window"
- `ROADMAP.md` phase 2
- https://docs.discord.com/developers/resources/message#get-channel-messages
