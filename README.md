# ClashPerk Monthly Reporter

[![CI](https://github.com/Gabmelom/clash-manager/actions/workflows/ci.yml/badge.svg)](https://github.com/Gabmelom/clash-manager/actions/workflows/ci.yml)

A lightweight monthly Discord reporting job for Clash of Clans clan management.

The project relies on **ClashPerk** to collect and aggregate Clash of Clans data. It does **not** query the Supercell API directly and does **not** run as a 24/7 Discord bot.

Once per month, the job:

1. Authenticates to Discord using a bot token.
2. Reads the previous month's ClashPerk messages from dedicated data channels.
3. Parses those messages into normalized player and event records.
4. Calculates monthly performance metrics.
5. Produces Top Performers and Review / Worst Performers sections.
6. Posts the report to a Discord reporting channel.
7. Exits.

## Goals

- Keep ClashPerk as the source of truth for game-data aggregation.
- Avoid direct Supercell API integration.
- Avoid an always-running Discord process.
- Eliminate manual ClashPerk export -> Google Sheets -> calculation workflows.
- Make report calculations transparent and testable.
- Handle members joining, leaving, renaming, and changing roles during the month.
- Keep V1 small enough to run as a scheduled GitHub Actions job.

## Non-goals

- Replacing ClashPerk.
- Real-time moderation or notifications.
- Continuously tracking players ourselves.
- Automatically kicking, promoting, or demoting members.
- Maintaining a web dashboard.
- Running a long-lived Discord Gateway connection.

## Proposed stack

- **Python 3.12+**
- **httpx** for Discord REST API calls
- **pydantic** for normalized models and validation
- **pytest** for parser and metric tests
- **GitHub Actions** for monthly scheduling and manual runs

A Discord library such as `discord.py` is intentionally not required for V1. The job only needs the Discord HTTP API to read channel history and post a report.

## Discord channel layout

```text
CLASHPERK DATA
├── #cp-members
├── #cp-wars
├── #cp-cwl
├── #cp-capital
├── #cp-games
└── #cp-donations      # optional for V1

CLAN MANAGEMENT
└── #clan-reports      # monthly output from this project
```

See [`docs/CLASHPERK_SETUP.md`](docs/CLASHPERK_SETUP.md) for the exact ClashPerk logs to enable.

## High-level flow

```text
ClashPerk automatic messages
            |
            v
Dedicated Discord data channels
            |
            v
Monthly GitHub Actions job
            |
            +--> fetch channel history
            +--> keep messages in reporting window
            +--> parse ClashPerk message types
            +--> normalize events by player tag
            +--> build monthly player summaries
            +--> calculate metrics / rankings
            +--> render Discord report
            |
            v
       #clan-reports
```

## Initial monthly metrics

The first scoring model should stay close to the existing Google Sheet while using richer ClashPerk events where useful.

Candidate metrics:

- Regular war participation
- Regular war attacks used %
- Regular war missed attacks
- Average war stars
- Average destruction, if reliably available
- CWL participation
- CWL attacks used %
- CWL average stars
- Clan Games points
- Capital contribution / raid participation
- Donations, optional
- Days eligible in clan during the reporting month

ClashPerk Activity Score is intentionally **not a V1 dependency** until we confirm that the numeric score is available in durable Discord messages.

## Membership-aware reporting

Performance should be interpreted relative to how long someone was actually in the clan.

Examples:

- A member who joined on the 28th should not be ranked as a full-month low performer.
- A member who left mid-month may be included in a separate Departed Members section.
- A configurable minimum number of eligible days should apply before Top / Review rankings.

Player tag is the canonical player identity. Display names are mutable and should never be used as the primary key.

## Suggested project layout

```text
src/
  clash_reporter/
    discord_client.py
    config.py
    models.py
    collection/
      fetch_messages.py
    parsers/
      members.py
      wars.py
      cwl.py
      capital.py
      clan_games.py
      donations.py
    aggregation/
      membership.py
      monthly_summary.py
    scoring/
      metrics.py
      rankings.py
    reporting/
      discord_report.py
    main.py

tests/
  fixtures/
  parsers/
  scoring/

docs/
```

## Configuration

Expected environment variables:

```text
DISCORD_BOT_TOKEN=
DISCORD_GUILD_ID=
DISCORD_CP_MEMBERS_CHANNEL_ID=
DISCORD_CP_WARS_CHANNEL_ID=
DISCORD_CP_CWL_CHANNEL_ID=
DISCORD_CP_CAPITAL_CHANNEL_ID=
DISCORD_CP_GAMES_CHANNEL_ID=
DISCORD_CP_DONATIONS_CHANNEL_ID=
DISCORD_REPORT_CHANNEL_ID=
REPORT_TIMEZONE=America/Toronto
```

Optional:

```text
DISCORD_API_BASE_URL=   # defaults to https://discord.com/api; override for a local stub
```

Do not commit bot tokens or secrets.

## Discord permissions

The reporting bot should have:

### ClashPerk data channels

- View Channel
- Read Message History

### `#clan-reports`

- View Channel
- Send Messages
- Embed Links
- Attach Files, optional

It does not need permission to manage members, roles, channels, or messages.

## First implementation target

The first useful milestone is intentionally narrow:

> Given saved JSON fixtures containing real ClashPerk messages, parse member, war, CWL, capital, and Clan Games data into a normalized monthly player summary and generate a text report locally.

Only after that works should Discord fetching and GitHub Actions scheduling be added.

## Commands

### Render a report from a normalized dataset

```bash
clash-reporter report --input tests/fixtures/normalized/monthly_players.sample.json --dry-run
clash-reporter report --input ./artifacts/normalized/monthly_players.json --month previous --dry-run
clash-reporter report --input ./artifacts/normalized/monthly_players.json --post
```

`--month` accepts `YYYY-MM`, `previous`, or `current` and labels the report from the reporting window instead of trusting the label stored in the dataset. `--dry-run` and `--post` are mutually exclusive. `--post` sends the report to `DISCORD_REPORT_CHANNEL_ID` and attaches a CSV of ranking-eligible members. A report over Discord's 2000-character limit is split on section boundaries.

### Run one month end to end

```bash
clash-reporter run --month previous
clash-reporter run --month previous --post
```

`run` fetches raw logs, normalizes them, and renders the report. `--post` delivers that report. Without `--post`, the report is printed and nothing is posted. Fetch still needs `DISCORD_BOT_TOKEN` and the data-channel IDs.

`#cp-members`, `#cp-wars`, `#cp-cwl`, `#cp-capital`, and `#cp-games` must be configured and readable. An inaccessible required channel fails the run before anything is posted. A readable `#cp-games` channel with no Clan Games event is still a valid month. `--allow-partial` posts anyway; it is off by default, and the monthly workflow does not pass it.

The scheduled job is [`.github/workflows/monthly-report.yml`](.github/workflows/monthly-report.yml): manual `workflow_dispatch` (optional `month`) and 05:00 UTC on the 1st. Month selection stays in the app (`REPORT_TIMEZONE`), not in the cron clock. See [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md).

### Capture raw ClashPerk payloads

`fetch` downloads the raw Discord messages for a reporting month so parsers can be built from real payloads. It downloads and writes only; it never parses.

```bash
clash-reporter fetch --month 2026-08 --output ./artifacts/raw
clash-reporter fetch --month current --output ./artifacts/raw            # the month so far
clash-reporter fetch --month previous --channel cp-wars --sanitize
```

- `--month` - `YYYY-MM`, `previous`, or `current`. Months are resolved in `REPORT_TIMEZONE`, and `current` captures a partial, still-open month, which is the fastest way to get usable fixtures from a freshly configured server.
- `--output` - directory for the capture. Defaults to `./artifacts/raw`.
- `--channel` - capture one channel (`cp-members`, `cp-wars`, `cp-cwl`, `cp-capital`, `cp-games`, `cp-donations`). Repeatable. Defaults to every channel with a configured ID.
- `--sanitize` - pseudonymize guild and Discord user IDs consistently across the capture. Message IDs, timestamps, embed structure, and player tags are preserved.

Each run writes one file per channel plus a `manifest.json` recording the channel IDs, window, message counts, capture time, and Discord API version. Output is deterministic (sorted keys, chronological order), so re-capturing the same messages produces byte-identical files. A channel the bot cannot read fails the run with the channel name and leaves no file behind for it.

Requires `DISCORD_BOT_TOKEN` and at least one `DISCORD_CP_*_CHANNEL_ID`. See [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) for how to promote a captured file into `tests/fixtures/`.

### Normalize a fetch directory (members-only)

`normalize` turns a `fetch` directory into the `MonthlyDataset` JSON that `report --dry-run` already consumes. Today it only parses `#cp-members` (partial issue #11). War, CWL, Clan Games, capital, and donation metrics stay missing (`null`), not zero.

```bash
clash-reporter normalize --input ./artifacts/raw --output ./artifacts/normalized
clash-reporter report --input ./artifacts/normalized/monthly_players.json --dry-run
```

`--month` defaults to the fetch manifest. Pass `--month YYYY-MM` when there is no manifest. See [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md), "Members-only `normalize`".

## Expected ClashPerk payloads

ClashPerk is open source, so the exact shape of every log message can be read from its log builders in [clashperk/clashperk](https://github.com/clashperk/clashperk) (`src/core/clan-log.ts`, `clan-war-log.ts`, `capital-log.ts`, `clan-games-log.ts`, `donation-log.ts`). Parser work does not have to wait for a month of live Discord history.

`tests/fixtures/` already contains one message per log family, synthesized from those builders with sanitized IDs; [`tests/fixtures/README.md`](tests/fixtures/README.md) records the provenance of each file. A real capture always wins over a synthetic fixture where the two disagree. See [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md), "ClashPerk's source is the payload reference".

## Documentation

- [`ROADMAP.md`](ROADMAP.md) - implementation phases and acceptance criteria
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) - system design and boundaries
- [`docs/CLASHPERK_SETUP.md`](docs/CLASHPERK_SETUP.md) - required Discord / ClashPerk channel configuration
- [`docs/DATA_CONTRACT.md`](docs/DATA_CONTRACT.md) - normalized models and reporting-window rules
- [`docs/REPORT_SPEC.md`](docs/REPORT_SPEC.md) - initial report and ranking behavior
- [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) - development and testing conventions
- [`docs/CODING_AGENT_BRIEF.md`](docs/CODING_AGENT_BRIEF.md) - concise implementation brief for a coding agent
- [`AGENTS.md`](AGENTS.md) - how work is orchestrated through GitHub issues, plus the commands to run

## External documentation

- ClashPerk logs: https://docs.clashperk.com/features/logs
- ClashPerk setup: https://docs.clashperk.com/overview/getting-set-up
- ClashPerk FAQ / activity tracking: https://docs.clashperk.com/faq
- Discord message API: https://docs.discord.com/developers/resources/message
- Discord permissions: https://docs.discord.com/developers/topics/permissions

## Status

**Early implementation.** Scoring, ranking, and report rendering work offline against a
normalized dataset. `#cp-members` can also be parsed from a `fetch` directory into that
dataset (members-only; other activity fields stay missing):

```bash
python -m clash_reporter report --input tests/fixtures/normalized/monthly_players.sample.json --dry-run
python -m clash_reporter normalize --input ./artifacts/raw --output ./artifacts/normalized
python -m clash_reporter report --input ./artifacts/normalized/monthly_players.json --dry-run
```

Reading Discord works too: `clash-reporter fetch` resolves a timezone-aware reporting month
and captures raw ClashPerk payloads to JSON.

`clash-reporter report --post` delivers that report to `#clan-reports`, and
`clash-reporter run --month previous --post` runs fetch, normalize, report, and
post together. The monthly GitHub Action is `.github/workflows/monthly-report.yml`.
It fails closed: a required channel the bot cannot read is not posted.
`--allow-partial` is the explicit override and is not used by the workflow.

Still missing: wiring the war/CWL/games/capital/donation parsers into aggregation.
The remaining V1 work is tracked in GitHub issues, seeded from
[`.github/backlog/`](.github/backlog).
