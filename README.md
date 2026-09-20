# ClashPerk Monthly Reporter

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

## Documentation

- [`ROADMAP.md`](ROADMAP.md) - implementation phases and acceptance criteria
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) - system design and boundaries
- [`docs/CLASHPERK_SETUP.md`](docs/CLASHPERK_SETUP.md) - required Discord / ClashPerk channel configuration
- [`docs/DATA_CONTRACT.md`](docs/DATA_CONTRACT.md) - normalized models and reporting-window rules
- [`docs/REPORT_SPEC.md`](docs/REPORT_SPEC.md) - initial report and ranking behavior
- [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) - development and testing conventions
- [`docs/CODING_AGENT_BRIEF.md`](docs/CODING_AGENT_BRIEF.md) - concise implementation brief for a coding agent

## External documentation

- ClashPerk logs: https://docs.clashperk.com/features/logs
- ClashPerk setup: https://docs.clashperk.com/overview/getting-set-up
- ClashPerk FAQ / activity tracking: https://docs.clashperk.com/faq
- Discord message API: https://docs.discord.com/developers/resources/message
- Discord permissions: https://docs.discord.com/developers/topics/permissions

## Status

**Planning / bootstrap.** No production code exists yet.
