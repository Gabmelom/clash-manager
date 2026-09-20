# Development Guide

## Principles

- Build parsers from real ClashPerk Discord payloads.
- Keep Discord transport, ClashPerk parsing, aggregation, scoring, and rendering separate.
- Prefer pure functions for parsing and scoring.
- Treat unknown input formats as diagnostics, not silent failures.
- Never substitute missing data with zero unless the source explicitly represents zero.

## Recommended dependencies

Runtime:

```text
httpx
pydantic
```

Development:

```text
pytest
pytest-cov
ruff
mypy          # optional but recommended
```

Avoid adding a Discord Gateway framework unless a future feature genuinely needs real-time events.

## Suggested commands

The CLI shape can evolve, but aim for commands similar to:

```text
python -m clash_reporter fetch --month 2026-08 --output ./artifacts/raw
python -m clash_reporter normalize --input ./artifacts/raw --output ./artifacts/normalized
python -m clash_reporter report --month 2026-08 --dry-run
python -m clash_reporter report --month previous --post
```

A single end-to-end command should eventually be enough for GitHub Actions:

```text
python -m clash_reporter run --month previous --post
```

## Capture raw payloads

`clash-reporter fetch` downloads the raw Discord messages for a reporting month. It is the
only step that needs live Discord access, and it is deliberately parse-free.

```bash
clash-reporter fetch --month 2026-08 --output ./artifacts/raw
clash-reporter fetch --month current --output ./artifacts/raw     # the month so far
clash-reporter fetch --month previous --channel cp-wars --sanitize
```

Notes:

- `--month` accepts `YYYY-MM`, `previous`, and `current`, resolved in `REPORT_TIMEZONE`.
  A still-open month is a valid capture: waiting for a complete calendar month is never
  required to start building parsers.
- Each run writes `<channel>.json` per channel plus `manifest.json` with the channel IDs,
  window, message counts, capture time, and Discord API version.
- Output is deterministic - sorted keys, two-space indentation, chronological order - so a
  re-capture of the same messages produces byte-identical files and reviewable diffs.
- `--sanitize` pseudonymizes guild and Discord user IDs, mapping each source ID to the same
  replacement for the whole run. Message IDs, timestamps, content text, embed structure, and
  player tags are preserved.
- A channel the bot cannot read fails the run with the channel name. No empty or partial
  file is written for it, so a capture is never silently incomplete.

## Develop parsers from fixtures

Before implementing a parser:

1. fetch a real Discord message payload
2. save it under `tests/fixtures/<log-type>/`
3. remove secrets if necessary
4. write the failing parser test
5. implement only enough parsing to satisfy the fixture
6. add edge-case fixtures as new formats appear

### Promote a captured file into `tests/fixtures/`

A capture under `artifacts/raw/` is a whole channel. A fixture is the smallest payload that
pins down one ClashPerk message format.

1. Capture with `--sanitize` unless the raw IDs are genuinely needed:

   ```bash
   clash-reporter fetch --month current --output ./artifacts/raw --sanitize
   ```

2. Find the messages illustrating the format, for example a member join:

   ```bash
   python - <<'PY'
   import json, pathlib
   messages = json.loads(pathlib.Path("artifacts/raw/cp-members.json").read_text())
   for message in messages:
       print(message["id"], message["content"][:80] or message.get("embeds"))
   PY
   ```

3. Copy the chosen message objects into `tests/fixtures/<log-type>/<case>.json`, using the
   naming in the fixture structure above (`members/join.json`, `wars/attack.json`, ...).
   Keep one message per file, or a short list when the case is about several messages.
4. Re-check the file before committing: no bot token, no unsanitized user or guild IDs, and
   player tags intact if the parser needs them. See `CONTRIBUTING.md`, "Commit useful
   fixtures".
5. Write the failing parser test against the fixture, then implement the parser.

`artifacts/` is ignored by git; only files promoted into `tests/fixtures/` are committed.

Suggested fixture structure:

```text
tests/fixtures/
  members/
    join.json
    leave.json
    role-change.json
    name-change.json
  wars/
    attack.json
    missed-attacks.json
    embed-final.json
  cwl/
    attack.json
    missed-attacks.json
    lineup-change.json
  capital/
    contribution.json
    raid-attack.json
    weekly-summary.json
  clan-games/
    final-leaderboard.json
```

## Tests

### Parser tests

Verify:

- message type detection
- player tag extraction
- numeric parsing
- timestamps
- embed field ordering changes where practical
- unsupported layouts produce diagnostics

### Aggregation tests

Verify:

- join mid-month
- leave mid-month
- leave then rejoin
- name change
- duplicate messages
- regular war vs CWL separation
- month boundary war
- no wars in a month
- zero Clan Games points vs missing Clan Games data

### Scoring tests

Verify:

- deterministic ranking
- new members excluded correctly
- missing data does not become zero
- ties follow explicit tie-breakers
- zero-war month does not penalize everyone

## Logging

Prefer structured logs with concise fields:

```text
level
operation
channel_id
message_id
parser
player_tag
warning_code
```

Never log `DISCORD_BOT_TOKEN`.

## Discord pagination

`GET /channels/{channel.id}/messages` returns paginated results. The collector must continue fetching until it crosses the beginning of the requested reporting window.

Do not assume one request contains a full month's history.

Reference: https://docs.discord.com/developers/resources/message#get-channel-messages

## Rate limits

Discord API clients must respect rate-limit headers and retry instructions.

`httpx` client logic should centralize this behavior rather than implementing ad-hoc sleeps in each collector.

## GitHub Actions

V1 workflow should support both:

```text
workflow_dispatch
schedule
```

The workflow should:

1. checkout
2. set up Python
3. install dependencies
4. run tests
5. run monthly report
6. upload diagnostics / raw / normalized artifacts

The application, not the cron expression, owns reporting-month calculation.

## Secrets and variables

Use GitHub repository secrets for:

```text
DISCORD_BOT_TOKEN
```

Use repository variables or secrets for IDs:

```text
DISCORD_GUILD_ID
DISCORD_CP_MEMBERS_CHANNEL_ID
DISCORD_CP_WARS_CHANNEL_ID
DISCORD_CP_CWL_CHANNEL_ID
DISCORD_CP_CAPITAL_CHANNEL_ID
DISCORD_CP_GAMES_CHANNEL_ID
DISCORD_CP_DONATIONS_CHANNEL_ID
DISCORD_REPORT_CHANNEL_ID
```

Channel IDs are not credentials, but keeping environment-specific configuration outside code is still preferable.

## Manual validation

Before enabling scheduled posting:

- run one month in dry-run mode
- compare results to ClashPerk `/export season`
- compare war metrics to ClashPerk `/export wars`
- investigate differences
- add regression fixtures for parser issues

## Coding style

- use type hints
- prefer small modules
- prefer dataclasses / pydantic models over loose dictionaries after parsing
- keep configuration centralized
- no business logic in Discord HTTP client
- no Discord payload parsing in scoring code
- include player tag in diagnostics whenever available
