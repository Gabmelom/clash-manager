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
python -m clash_reporter report --input ./artifacts/normalized/monthly_players.json --dry-run
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
- `--verbose` logs each channel as it is captured, plus rate-limit and retry activity.
- `DISCORD_API_BASE_URL` points the client somewhere other than `https://discord.com/api`.
  Use it to exercise the command end to end against a local stub; it is not needed for a
  real capture.

## Members-only `normalize` (partial #11)

`clash-reporter normalize` is the local path from a Discord `fetch` directory to
`report --dry-run`. It is **not** the full aggregation issue: only `#cp-members` is parsed.

```bash
clash-reporter normalize --input ./artifacts/raw --output ./artifacts/normalized
clash-reporter report --input ./artifacts/normalized/monthly_players.json --dry-run
```

What it does:

- Reads `cp-members.json` (same layout `fetch` writes) and optional `manifest.json` for the month.
- Parses join / leave / role / name events, de-duplicates by Discord message ID.
- Reconstructs membership intervals and `eligible_days` in `REPORT_TIMEZONE`
  (the process timezone, not a timezone stored on the fetch manifest). A
  mismatch with the manifest timezone is recorded as a data note.
- Writes `events.json`, `monthly_players.json`, and `diagnostics/parser_warnings.json`.
- `joined_this_month` / `departed_this_month` mean presence at the window start /
  end. A leave-then-rejoin still ranks if the player was in at both ends; the
  mid-month gap is only on `intervals` and a per-player warning. Full #11 can
  decide whether the report should surface that churn.

What it deliberately does not do:

- War, CWL, Clan Games, capital, and donation parsers are not wired. Those per-player
  fields stay `None` (missing). Dataset war counts are `0` only because nothing was parsed,
  not because a war month was observed to be empty. `report --dry-run` must not flag anyone
  for review solely from that gap.
- Name→tag attribution and the Clash of Clans API stay deferred (`AGENTS.md`).

`--month` is optional when the fetch manifest is present. Pass `--month YYYY-MM` to
override it, or when normalizing a directory that has `cp-members.json` but no manifest.

Full aggregation (issue #11) starts from this slice once the other log-family parsers land.

## ClashPerk's source is the payload reference

ClashPerk is open source, and its log builders are the authoritative description of what
lands in the data channels. Read them instead of waiting for a month of live messages to
accumulate, and instead of guessing from screenshots:
[clashperk/clashperk](https://github.com/clashperk/clashperk).

| Log family | Source |
| --- | --- |
| member join / leave / role / name change, capital contribution and raid | `src/core/clan-log.ts` |
| regular war attacks, missed attacks, war embed | `src/core/clan-war-log.ts` |
| CWL attacks, missed attacks, lineup changes, round embeds | `src/core/clan-war-log.ts` (the `warTag` branches) |
| capital weekly summary | `src/core/capital-log.ts` |
| Clan Games leaderboard | `src/core/clan-games-log.ts` and `src/helper/clan-games.helper.ts` |
| donations | `src/core/donation-log.ts` |
| `/export season`, `/export wars` columns for phase 6 validation | `src/commands/export/export-season.ts`, `export-wars.ts` |

Emoji IDs, embed colors, and role names live in `src/util/emojis.ts` and
`src/util/constants.ts`.

Facts worth knowing before writing a parser, all of them read out of those files:

- Every log is posted through a **webhook**, so messages carry `webhook_id` and an
  `author.id` that is the same snowflake. The REST message object has no `guild_id`.
- The war and CWL **attack logs are plain `content`, not embeds**.
- Most log families identify players by **name only**. A player tag appears only in the
  per-player member and capital logs, whose embed title is `\u200e{name} ({tag})`. War
  attacks, missed attacks, lineup changes, Clan Games, capital summaries, and donations
  carry no tag at all, which matters because the player tag is this project's canonical
  identity.
- Clan Games and war embeds are **edited in place**. The payload holds the final state and
  `edited_timestamp` is set, so the creation timestamp is not when the data was produced.

## Develop parsers from fixtures

Before implementing a parser:

1. read the ClashPerk builder for that log family
2. use the committed fixture for it, or capture a real payload with `clash-reporter fetch`
3. save it under `tests/fixtures/<log-type>/`
4. remove secrets if necessary
5. write the failing parser test
6. implement only enough parsing to satisfy the fixture
7. add edge-case fixtures as new formats appear

### The committed fixture corpus

`tests/fixtures/` already holds one message per log family, synthesized from the ClashPerk
builders above with sanitized IDs and invented clan/player identities. They exist so parser
work can start with no Discord access at all. `tests/fixtures/README.md` records which
builder each file came from and which ClashPerk commit was transcribed.

Treat them as a starting point, not as ground truth: when a real capture disagrees with a
synthetic fixture, the real capture wins, and the difference is worth recording on the
issue.

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

Fixture structure:

```text
tests/fixtures/
  README.md              # provenance: which ClashPerk builder each file came from
  members/
    join.json
    leave.json
    role-change.json
    name-change.json
  wars/
    attack.json
    attack-missing-fields.json
    missed-attacks.json
    embed-final.json
    unknown-layout.json
  cwl/
    attack.json
    missed-attacks.json
    lineup-change.json
    embed-round.json
    unknown-layout.json
  capital/
    contribution.json
    raid-attack.json
    weekly-summary.json
  clan-games/
    final-leaderboard.json
  donations/
    monthly-summary.json
  normalized/
    monthly_players.sample.json
```

Tests reach these through the `clashperk_message`, `repost`, and `history_page` fixtures in
`tests/conftest.py`, so a mocked transport serves real payload shapes rather than invented
ones.

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
- `eligible_days` in `REPORT_TIMEZONE`, not UTC
- a player present the whole window with no join event
- members-only month does not flag review for missing wars
- regular war vs CWL separation (deferred until those parsers land)
- month boundary war (deferred)
- no wars in a month (deferred beyond leaving war metrics missing)
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
