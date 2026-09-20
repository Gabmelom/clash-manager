---
title: "Regular war and CWL parsers"
labels: [phase-1, "area:parsers", needs-fixtures]
depends_on: [parser-framework-members]
---

## Context

War participation is the heaviest-weighted input in the scoring model, and it is also where
the data is trickiest: attacks and misses arrive as separate log types, wars straddle month
boundaries, and CWL must stay separate from regular war throughout.

## Scope

`src/clash_reporter/parsers/wars.py`:

- `WarAttack` from the War Attack Log: stars, destruction, attacker/defender town hall, and
  target position where ClashPerk exposes them. Fields that are not reliably present are
  optional, not zero.
- `WarMissedAttacks` from the War Missed Attacks Log, normalized to one event per player even
  though one message lists several.
- A stable `war_id_or_key` so attacks and misses from the same war join up, derived from the
  War Embed Log when available with a documented and tested fallback.

`src/clash_reporter/parsers/cwl.py`:

- `CwlAttack`, `CwlMissedAttack`, and `CwlLineupChange`, carrying `round_number` where it is
  reliably available.
- A CWL season key so rounds group into one season.

## Out of scope

Turning events into per-player war totals. That is monthly aggregation.

## Acceptance criteria

- [ ] Regular war and CWL events are distinct types and are never merged by the parser.
- [ ] A missed-attacks message listing several players produces one event per player with
      distinct event keys.
- [ ] Attacks and misses from one war resolve to the same `war_id_or_key`, and the fallback
      path has its own fixture and test.
- [ ] The month-attribution rule from `docs/DATA_CONTRACT.md` - a war belongs to the month it
      ended in - is implemented and covered by a war that starts in one month and ends in the
      next.
- [ ] Absent destruction or town hall data stays `None`, and a test asserts it is not coerced
      to `0`.
- [ ] Unknown embed layouts produce diagnostics naming the log type.

## Dependencies

- Parser framework and members parser
- Fixtures for war attack, war missed, war embed, CWL attack, CWL missed, CWL lineup

## References

- `docs/DATA_CONTRACT.md` - `WarAttack`, `WarMissedAttacks`, `Cwl*`, "Event inclusion rules"
- `docs/CLASHPERK_SETUP.md` - sections 4 and 5
