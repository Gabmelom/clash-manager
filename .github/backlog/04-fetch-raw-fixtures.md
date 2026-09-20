---
title: "`fetch` command: capture raw ClashPerk payloads as JSON fixtures"
labels: [phase-1, "area:discord"]
depends_on: [reporting-window, discord-rest-client, clashperk-channel-setup]
---

## Context

Parsers must be built from real payloads. A capture command turns one manual run against the
live server into a permanent, reviewable test corpus, which is what lets every later parser
issue be done offline by an agent with no Discord access.

## Scope

- `clash-reporter fetch --month 2026-08 --output ./artifacts/raw [--channel cp-wars]`,
  writing one JSON file per channel (`cp-members.json`, `cp-wars.json`, …) containing the raw
  Discord message objects in chronological order.
- Include a small run manifest per capture: channel ID, window, message count, captured-at
  timestamp, and the API version used.
- `--sanitize` to strip or pseudonymize guild and Discord user IDs consistently across a
  capture while preserving message and embed structure, message IDs, timestamps, and player
  tags. The mapping must be stable within one run so message relationships survive.
- A short section in `docs/DEVELOPMENT.md` describing how to promote a captured file into
  `tests/fixtures/<log-type>/`.
- Fail loudly and per channel: a channel the bot cannot read is an error naming the channel,
  never an empty file.

## Out of scope

Parsing. This command only downloads and writes.

## Acceptance criteria

- [ ] Output is deterministic: same input messages produce byte-identical JSON (sorted keys,
      fixed indentation, chronological order).
- [ ] `--sanitize` maps the same source ID to the same replacement throughout a run and
      leaves player tags and embed structure untouched.
- [ ] Tests drive the command through a mocked transport and assert the on-disk layout.
- [ ] A channel returning 403 fails the command with a message naming the channel, and no
      partial file is left behind for it.
- [ ] The captured output is verified to round-trip: reading a written file back yields the
      same message objects.
- [ ] Documented in `README.md` and `docs/DEVELOPMENT.md`.

## Dependencies

- Discord REST client
- Reporting window
- Phase 0 Discord setup, to actually run it against the live server

## References

- `docs/CODING_AGENT_BRIEF.md` - step 3
- `docs/DEVELOPMENT.md` - "Develop parsers from fixtures"
- `CONTRIBUTING.md` - "Commit useful fixtures"
