# Data Contract

This document describes normalized data after Discord / ClashPerk parsing.

The exact parser implementation will depend on real message payload fixtures. Do not lock parser logic to assumptions from screenshots or documentation alone.

## Identity

### Canonical player key

```text
player_tag
```

Example:

```text
#R22YRC0UY
```

Player name is mutable and must not be used as the primary key.

### Deferred: name-only log attribution

Most ClashPerk log families carry a display name and no player tag. Only per-player member
events (join, leave, role, name change) and per-player capital logs include a tag, in the
embed title `\u200e{name} ({tag})`.

**Policy — table a general resolver until a real duplicate display name appears:**

- Canonical identity remains `player_tag`. Display name is never the primary key.
- When a resolver is built, the default path is an in-window index from those tag-bearing
  logs. Do not call any external game API for the common case.
- The Clash of Clans / Supercell API may be used **only** to disambiguate a known duplicate
  display name that Discord logs cannot separate. It is not a data-collection source and
  must not be called for every player, preemptively, or as a general identity layer.
- Until that rare case is implemented, do not add a CoC API client. Unresolved or ambiguous
  names are diagnostics (`null` / `None`), never an invented tag and never a silent zero.

This is the decision, not a design. Collision handling (renames, reused names, map position)
belongs with the deferred implementation. See `AGENTS.md`, "Known deferred decisions", and
`.github/backlog/12-name-only-log-tag-attribution.md`.

## Normalized event types

Suggested event models follow.

### MemberJoined

```text
player_tag
player_name
occurred_at
source_message_id
metadata
```

### MemberLeft

```text
player_tag
player_name
occurred_at
source_message_id
metadata
```

### PlayerNameChanged

```text
player_tag
old_name
new_name
occurred_at
source_message_id
```

### PlayerRoleChanged

```text
player_tag
old_role
new_role
occurred_at
source_message_id
```

### WarAttack

```text
war_id_or_key
player_tag
player_name
occurred_at
stars
destruction_percent
attacker_th
 defender_th
target_position
source_message_id
```

Fields that ClashPerk does not reliably expose should be optional.

### WarMissedAttacks

One Discord message may contain multiple players.

Normalize to one event per player:

```text
war_id_or_key
player_tag
missed_count
occurred_at
source_message_id
```

### CwlAttack

Same basic structure as `WarAttack`, plus:

```text
round_number
```

if reliably available.

### CwlMissedAttack

```text
cwl_season_or_key
round_number
player_tag
missed_count
occurred_at
source_message_id
```

### CwlLineupChange

```text
cwl_season_or_key
round_number
player_tag
change_type   # added | removed
occurred_at
source_message_id
```

### CapitalContribution

```text
player_tag
amount
occurred_at
source_message_id
```

### CapitalRaidAttack

```text
player_tag
occurred_at
raid_weekend_key
metadata
source_message_id
```

### ClanGamesResult

The Clan Games leaderboard is a final-state snapshot rather than a stream of individual scoring events.

Normalize each leaderboard row:

```text
player_tag          # null on name-only ClashPerk rows; never invented
player_name
points
occurrence_key      # Clan Games season id (YYYY-MM)
source_message_id
message_edited_at
```

`occurrence_key` is the Clan Games occurrence from the scoreboard title / button
`season`. Month attribution uses `message_edited_at` (the snapshot), not the
message creation timestamp. The parser framework's de-duplication key remains
`<message_id>:ClanGamesResult:<player_tag>:<row_index>` on the event's
`event_key` property; it is a different field from this occurrence id.

### DonationSummary

Optional V1 model:

```text
player_tag
donated
received
summary_date
source_message_id
```

## Source metadata

Every normalized record should retain enough source information for debugging:

```text
source_channel_id
source_message_id
source_message_timestamp
source_message_edited_timestamp
parser_name
parser_version
```

Do not store only calculated values. A ranking should be traceable back to its source messages.

## MonthlyPlayerSummary

Suggested aggregate model:

```text
player_tag
current_display_name

membership:
  first_seen_at
  joined_at
  left_at
  eligible_days
  ranking_eligible

regular_war:
  wars_participated
  attacks_available
  attacks_used
  attacks_missed
  attack_usage_percent
  total_stars
  average_stars
  average_destruction_percent

cwl:
  rounds_in_lineup
  attacks_available
  attacks_used
  attacks_missed
  attack_usage_percent
  total_stars
  average_stars

clan_games:
  points

capital:
  contribution
  raid_attacks

donations:
  donated
  received

roles:
  role_at_start
  role_at_end
  changes

data_quality:
  warnings
```

Not every field must be populated in V1.

## Missing data semantics

This distinction is critical:

```text
0     = observed zero
null  = not known / not available
```

Examples:

- Clan Games leaderboard explicitly shows 0 -> `0`
- Clan Games message missing / inaccessible -> `null`
- No regular wars occurred -> `wars_participated = 0`, but this should not be a performance penalty
- War parser cannot identify player -> warning, not an invented zero

The members-only `normalize` command (partial issue #11) has not parsed war/CWL/games/capital/donation
logs yet. Those per-player metrics must stay `null` until those parsers land. See `docs/DEVELOPMENT.md`.

## Reporting eligibility

Do not equate membership with ranking eligibility.

Example configuration:

```text
MIN_ELIGIBLE_DAYS = 14
```

A player can appear in New Members without being included in Top / Review rankings.

Potential eligibility conditions:

- member for at least `MIN_ELIGIBLE_DAYS`
- not departed before the minimum exposure window
- enough available performance data for the metrics being scored

Final thresholds belong in scoring configuration, not parser code.

## Event inclusion rules

### Membership events

Use event timestamp.

### Regular war / CWL

Prefer associating attacks and misses to a war / round, then attribute that war to a reporting month using a documented rule.

Recommended rule:

```text
include war in the month in which the war ended
```

This avoids splitting one war across two reports.

If ClashPerk payloads do not provide a stable war end timestamp, define and test a fallback based on the final embed / missed-attacks message.

### Clan Games

Attribute the completed Clan Games event to the month in which the event ended.

### Capital

Daily / event-style contributions can be included by event timestamp. Weekly summaries are validation data rather than the primary source when detailed events are available.

## Deduplication

Discord history pagination and parser retries must not double-count messages.

Use Discord message ID as the first deduplication key.

For parsers that emit multiple normalized rows from one message, use a deterministic composite event key such as:

```text
<message_id>:<event_type>:<player_tag>:<index>
```

## Data-quality diagnostics

Examples:

- unknown ClashPerk embed layout
- player name found but no player tag available
- duplicate conflicting event
- missed-attack record without corresponding war context
- Clan Games leaderboard missing expected rows
- member left with no known prior join event

Diagnostics should be included in workflow artifacts and summarized in logs.
