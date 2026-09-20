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

## Develop parsers from fixtures

Before implementing a parser:

1. fetch a real Discord message payload
2. save it under `tests/fixtures/<log-type>/`
3. remove secrets if necessary
4. write the failing parser test
5. implement only enough parsing to satisfy the fixture
6. add edge-case fixtures as new formats appear

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
