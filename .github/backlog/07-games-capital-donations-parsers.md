---
title: "Clan Games, Capital, and donations parsers"
labels: [phase-1, "area:parsers", needs-fixtures]
depends_on: [parser-framework-members]
---

## Context

These three complete the scoring inputs. Clan Games is the awkward one: ClashPerk edits a
single leaderboard message in place, so the parser reads a final snapshot rather than a
stream of events, and the message's creation timestamp is not when the data was produced.
Capital contribution is highly skewed, so the parser must preserve raw amounts and leave
normalization to scoring.

## Scope

- `src/clash_reporter/parsers/clan_games.py`: parse the leaderboard embed into one
  `ClanGamesResult` per row, keeping `message_edited_at` and an `event_key` for the Clan
  Games occurrence.
- `src/clash_reporter/parsers/capital.py`: `CapitalContribution` from the Capital Gold
  Contribution Log and `CapitalRaidAttack` from the Capital Gold Raid Log, with a raid
  weekend key. The weekly summary is parsed as validation context, not as the primary source.
- `src/clash_reporter/parsers/donations.py`: `DonationSummary` from the daily donation log.
  Optional for V1 and display-only, so it must not feed the score.

## Out of scope

Scoring normalization, including the Clan Games cap and capital percentile handling. Those
already live in `clash_reporter.scoring` and stay there.

## Acceptance criteria

- [ ] A leaderboard row explicitly showing `0` points parses as `0`, while a missing or
      inaccessible Clan Games message leaves points `None`. Both cases have tests, because
      this distinction decides whether someone gets flagged for review.
- [ ] Clan Games is attributed to the month the event ended in, using the edit timestamp
      rather than the creation timestamp, with a cross-month fixture.
- [ ] A truncated or paginated leaderboard produces a diagnostic about missing rows rather
      than a silently short result.
- [ ] Capital contributions keep raw amounts; the parser applies no normalization.
- [ ] Donations are parsed but do not affect any score, asserted by a test.

## Dependencies

- Parser framework and members parser
- Fixtures for the Clan Games leaderboard, capital contribution, capital raid, capital weekly
  summary, and daily donation log

## References

- `docs/DATA_CONTRACT.md` - `ClanGamesResult`, `Capital*`, `DonationSummary`, "Missing data
  semantics"
- `docs/CLASHPERK_SETUP.md` - sections 6, 7, and 8
- `docs/REPORT_SPEC.md` - "Clan Games", "Capital"
