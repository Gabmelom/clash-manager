---
title: "Parser framework with diagnostics, plus the #cp-members parser"
labels: [phase-1, "area:parsers", needs-fixtures]
depends_on: [fetch-raw-fixtures]
---

## Context

There are six ClashPerk log families to parse. Deciding message-type detection,
diagnostics, and deduplication once - in a framework - keeps the five later parsers small
and consistent. Members is the right first parser because membership drives eligibility, and
`#cp-members` is the one channel whose absence fails the whole report.

The hard rule from `docs/ARCHITECTURE.md`: an unrecognized message is a recorded diagnostic,
never a silent drop.

## Scope

- Event models from `docs/DATA_CONTRACT.md` in `src/clash_reporter/events.py`:
  `MemberJoined`, `MemberLeft`, `PlayerNameChanged`, `PlayerRoleChanged`, each carrying the
  source metadata block (channel ID, message ID, message timestamp, edited timestamp, parser
  name, parser version).
- `src/clash_reporter/parsers/base.py`:
  - a `Parser` protocol: given a raw message, return parsed events or a structured
    `IgnoredMessage(reason_code, detail)`.
  - a `ParseOutcome` aggregate collecting events plus diagnostics.
  - deterministic event keys, `<message_id>:<event_type>:<player_tag>:<index>`, used to
    de-duplicate.
  - a player-tag extraction helper with a single canonical normalization (uppercase, leading
    `#`, `O`/`0` handled as ClashPerk emits them).
- `src/clash_reporter/parsers/members.py` handling join, leave, role change, and name change.
- Fixtures under `tests/fixtures/members/` captured from the real server.

## Out of scope

War, CWL, Clan Games, capital, and donations parsers. They build on this framework in
separate issues.

## Acceptance criteria

- [ ] Every fixture in `tests/fixtures/members/` is either parsed into events or classified
      with an explicit reason code. A test asserts no message can fall through unclassified.
- [ ] Player tags are extracted from every members fixture, and tag normalization is tested
      against the raw forms ClashPerk emits.
- [ ] Parsing the same message twice yields the same event keys and de-duplicates to one
      event.
- [ ] A deliberately malformed or unknown message produces a diagnostic and does not raise.
- [ ] A message with a display name but no recoverable player tag produces a warning, not an
      invented event.
- [ ] Parsers are pure functions: no HTTP, no clock, no file access.

## Dependencies

- `fetch` command, for the fixtures

## References

- `docs/DATA_CONTRACT.md` - event models, deduplication, diagnostics
- `docs/CODING_AGENT_BRIEF.md` - steps 4 and 5
- `docs/DEVELOPMENT.md` - "Parser tests"
