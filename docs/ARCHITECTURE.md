# Architecture

## Core principle

ClashPerk is the data collector. Discord is the durable event / message store. This project is a short-lived monthly batch processor.

ClashPerk Discord logs are the source of wars, CWL, Clan Games, capital, and donations.
The Clash of Clans API is used only to read the current clan roster (tag and name) so
name-only logs can be attributed. It is not a metrics source.

## Components

```text
                 Clash of Clans
                       |
                       | handled by ClashPerk
                       v
                   ClashPerk
                       |
          automatic Discord log messages
                       |
       +---------------+----------------+
       |               |                |
       v               v                v
   #wars          #members         other data channels
       \               |                /
        \              |               /
         +-------------+--------------+
                       |
                  Discord REST API
                       |
                       v
              Monthly Reporter Job
                       |
        +--------------+---------------+
        |              |               |
        v              v               v
      Parse         Aggregate        Score
        \              |               /
         +-------------+--------------+
                       |
                       v
                Render report
                       |
                       v
                 #clan-reports
```

## Why REST instead of a normal online bot

The project does not need real-time Gateway events.

A monthly job can:

1. start,
2. call Discord's HTTP API,
3. retrieve message history,
4. calculate the report,
5. post the report,
6. exit.

This keeps hosting costs and operational complexity close to zero.

## Runtime target

V1 should run in GitHub Actions.

Reasons:

- native cron scheduling
- manual `workflow_dispatch`
- secret storage
- logs
- downloadable workflow artifacts
- no persistent compute

The implementation should not depend on GitHub Actions internals so it can later run as an Azure Container Apps Job, local cron job, or other scheduled container.

## Module boundaries

### Discord client

Responsibilities:

- authenticate using bot token
- fetch channel history with pagination
- respect Discord rate limits
- post messages / embeds
- upload optional report attachments

It should know nothing about ClashPerk semantics.

### Collectors

Responsibilities:

- fetch all relevant messages for a channel / reporting window
- preserve original payloads
- return raw Discord message objects

### Parsers

Responsibilities:

- identify supported ClashPerk message formats
- extract structured fields from content / embeds
- emit normalized domain events
- record unsupported formats explicitly

Each parser should target one log family.

### Aggregation

Responsibilities:

- group events by player tag
- reconstruct membership intervals
- convert raw events into monthly player summaries
- resolve mutable names to a display name while keeping the tag stable

### Scoring

Responsibilities:

- calculate transparent metrics
- determine ranking eligibility
- calculate composite score, if enabled
- produce reasons for high / low ranking

Scoring should operate only on normalized summaries. It must not parse Discord payloads.

### Reporting

Responsibilities:

- render human-friendly Discord content
- enforce Discord message / embed limits
- generate optional CSV / JSON exports

## Data retention

V1 does not require a database.

For each workflow run, keep temporary artifacts such as:

```text
artifacts/
  raw/
    members.json
    wars.json
    cwl.json
    capital.json
    clan-games.json
  normalized/
    events.json
    monthly_players.json
  diagnostics/
    parser_warnings.json
  report/
    report.md
    report.csv
```

These can be uploaded as GitHub Actions artifacts for debugging and then expire automatically.

## Reporting window

The application should calculate a half-open interval:

```text
[start_of_month, start_of_next_month)
```

in `REPORT_TIMEZONE`.

For the automated monthly run, select the previous calendar month.

Example:

```text
run date: 2026-09-01
REPORT_TIMEZONE: America/Toronto
window: 2026-08-01 00:00:00 through 2026-09-01 00:00:00
```

Internally, convert boundaries to UTC for Discord timestamp comparison.

## Message edits

Some ClashPerk logs use a single message that is updated over time, including Clan Games leaderboards and war embeds.

That is acceptable when the final state is what the monthly report needs, but it has consequences:

- The message creation timestamp may be earlier than the last edit.
- The current Discord message payload contains the latest state, not historical intermediate states.
- Event-style logs such as attack messages are preferable when exact history matters.

Parsers should use detailed event logs as the primary source when available and summary embeds as validation / supplemental context.

## Failure policy

The monthly report should fail closed for missing critical data.

Examples:

- `#members` inaccessible: fail report
- `#wars` inaccessible: fail report if war metrics are part of scoring
- `#clan-games` has no Clan Games event that month: valid if no event occurred
- one unknown ClashPerk message format: record diagnostic, continue unless it affects a required metric

Do not silently replace missing values with zero when zero would imply poor performance.

## Security

- Bot token only via environment variable / GitHub secret.
- Bot has read-only permissions in data channels.
- Bot has send permission only where needed.
- Do not grant Manage Roles, Kick Members, Ban Members, or Administrator.
- Never log the bot token.

## External references

- ClashPerk logs: https://docs.clashperk.com/features/logs
- Discord message API: https://docs.discord.com/developers/resources/message
- Discord permissions: https://docs.discord.com/developers/topics/permissions
