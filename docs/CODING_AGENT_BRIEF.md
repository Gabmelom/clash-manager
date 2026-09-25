# Coding Agent Brief

## Project

Build a lightweight monthly Clash of Clans clan-management reporter using **ClashPerk Discord logs** as the only game-data source.

## Hard constraints

1. Do **not** call the Supercell / Clash of Clans API for data collection. ClashPerk
   Discord logs are the only game-data source. The **only** exception — deferred until a
   real duplicate appears, and not to be built in the meantime — is using the CoC API to
   disambiguate a **known duplicate display name** that Discord logs cannot separate.
   Never call it preemptively, for every player, or as a general identity layer. See
   `AGENTS.md`, "Known deferred decisions".
2. Keep ClashPerk as the collector and source of game-data aggregation.
3. Do **not** build an always-running Discord Gateway bot for V1.
4. The process should wake once per month, read Discord history through the REST API, produce a report, post it, and exit.
5. Do not require a database for V1.
6. Player tag is the canonical player identity.
7. Missing data is not the same as zero.
8. Do not automate kicks, promotions, or demotions.

## Preferred stack

- Python 3.12+
- httpx
- pydantic
- pytest
- GitHub Actions

## Input channels

```text
#members
#wars
#cwl
#capital
#clan-games
#donations   # optional
```

Output:

```text
#clan-reports
```

Read `docs/CLASHPERK_SETUP.md` for the expected log types in each channel.

## Implementation order

### Step 1 - scaffold

Create:

```text
src/clash_reporter/
tests/
tests/fixtures/
```

Add configuration loading and a very small CLI.

### Step 2 - Discord REST client

Implement only what is needed:

- fetch channel messages
- paginate backwards
- filter by reporting date window
- post a message
- optional attachment upload later

Do not connect to Discord Gateway.

### Step 3 - fixture capture

Add a development command that downloads raw messages from configured channels into JSON files.

This is important because parsers must be based on real ClashPerk payloads.

### Step 4 - normalized event models

Implement models from `docs/DATA_CONTRACT.md`.

### Step 5 - parsers

Implement in this order:

1. member join / leave / role / name
2. regular war attacks and misses
3. CWL attacks, misses, lineup changes
4. Clan Games leaderboard
5. capital contribution / raid
6. donations

Every parser should return either:

- normalized event(s), or
- a structured reason the message was intentionally ignored / unsupported

### Step 6 - aggregation

Build a monthly summary by player tag.

Key requirements:

- calculate eligible days
- separate CWL from regular wars
- support partial-month membership
- preserve source / diagnostic information

### Step 7 - report without scoring

Before composite scoring exists, print a full raw-metrics report locally. Verify calculations against ClashPerk exports.

### Step 8 - scoring

Implement the smallest transparent scoring model described in `docs/REPORT_SPEC.md`.

Put weights and thresholds in config.

### Step 9 - Discord rendering

Render concise Top Performers / Needs Review / New Members / Departed Members output.

### Step 10 - GitHub Actions

Add manual and monthly scheduled execution.

## First pull request target

A good first PR should **not** try to finish the bot.

Target:

> Scaffold the Python project, implement configuration + Discord REST history pagination, and add a command that downloads raw messages from one configured channel to JSON with tests for pagination / date filtering.

This creates the foundation needed to capture real ClashPerk payloads before guessing at parser formats.

## Definition of quality

- tests before parser expansion
- no hidden coupling to one player's name
- no spreadsheet-specific row assumptions
- no magic Discord channel names in business logic
- no silent parser failures
- no giant `main.py`
- no premature database
- no Clash of Clans API client except the deferred duplicate-name exception in `AGENTS.md`

## References

- `README.md`
- `ROADMAP.md`
- `docs/ARCHITECTURE.md`
- `docs/CLASHPERK_SETUP.md`
- `docs/DATA_CONTRACT.md`
- `docs/REPORT_SPEC.md`
- `docs/DEVELOPMENT.md`
