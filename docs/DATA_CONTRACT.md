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
player_tag          # None on name-only ClashPerk logs; never invented
player_name
occurred_at
stars
destruction_percent
attacker_th
defender_th
target_position
ended_at            # war end, used for month attribution
reporting_month     # YYYY-MM of ended_at (UTC)
source_message_id
```

Fields that ClashPerk does not reliably expose should be optional. Absent
destruction or town hall is `None`, not `0`. `0` is reserved for an observed
zero (for example three empty-star emojis, or `` `0%` ``).

### War identity (`war_id_or_key`)

Attacks and misses from the same war must share one key.

1. **Primary:** `war:{id}` from the War Embed Log Attack/Defense button
   `custom_id` JSON (`cmd: "war"`, `war_id: <int>`).
2. **Fallback** (no embed, or embed without `war_id`):
   `fallback:{home_clan_tag}:{opponent_clan_tag}:{YYYY-MM-DD}` from the War
   Missed Attacks Log, which ClashPerk posts at `warEnded`. The date is the UTC
   calendar day of that message. Attacks in the window before that message
   inherit the same key.

### WarMissedAttacks

One Discord message may contain multiple players.

Normalize to one event per player:

```text
war_id_or_key
player_tag          # None on name-only logs
player_name
missed_count
occurred_at
source_message_id
```

ClashPerk missed-attacks and lineup lines include a map-position emoji. The
parser reads it to split the line, but V1 event models do not store it.
Preserve that if identity or aggregation later needs map order (issues #11 / #12).

### CwlAttack

Same basic structure as `WarAttack`, plus:

```text
cwl_season_or_key
round_number
```

`round_number` is taken from `(CWL Round N)` / footer `Round #N` when those
strings are present. The CWL Attack Log content does not include a round; the
parser fills `round_number` only after joining the attack to a CWL embed or
missed-attacks message in the same channel.

Regular war and CWL are distinct event types and are never merged.

CWL missed-attacks embeds are distinguished from regular-war missed-attacks by
`(CWL Round N)` in the description. That is the only payload cue; parsers do
not inspect Discord channel names. `#wars` vs `#cwl` is the operational
routing guarantee if that round string is ever absent.

### CWL season key

```text
cwl:{home_clan_tag}:{YYYY-MM}
```

`YYYY-MM` is the UTC calendar month of that round's end timestamp (missed-attacks
message or CWL embed `ended` timestamp). Rounds of one CWL almost always share a
month, so this groups a season.

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
player_tag          # present on per-player capital logs
player_name
amount              # raw gold; no parser-side cap or clan-relative scaling
occurred_at
source_message_id
```

### CapitalRaidAttack

```text
player_tag          # present on per-player capital logs
player_name
occurred_at
raid_weekend_key    # ClashPerk weekId: Friday YYYY-MM-DD of the raid weekend
looted              # raw gold when the log exposes it
attacks_used
attacks_available
source_message_id
```

### CapitalWeeklySummaryRow

Validation context from the Clan Capital Weekly Summary Log, not a primary
scoring source. One Discord message lists several players by **name only**.

```text
player_tag          # null; never invented
player_name
kind                # raid | contribution
amount              # raw looted gold (raid) or contributed gold (contribution)
attacks_used        # raid rows only
attacks_available   # raid rows only
raid_weekend_key
source_message_id
```

Per-player contribution and raid logs remain the primary source. Aggregation
must not double-count these rows with `CapitalContribution` / `CapitalRaidAttack`.

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

Optional V1 model, display-only. Must not feed the composite score.

ClashPerk's daily/weekly/monthly donation log is **name-only**.

```text
player_tag          # null on name-only ClashPerk rows; never invented
player_name
donated
received
summary_date        # UTC date of the range start (`<t:unix>` in the embed)
interval            # daily | weekly | monthly
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

Rule:

```text
include war in the month in which the war ended
```

`reporting_month` is `YYYY-MM` of `ended_at` in UTC. This avoids splitting one
war across two reports. A war that starts on 31 July and ends on 1 August is
an August war.

If ClashPerk payloads do not provide a stable war end timestamp, the fallback is
the War Missed Attacks / CWL Missed Attacks message posted at `warEnded`.

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
- missed-attack / war-attack record without corresponding war context
  (warning on an emitted event; the row is not dropped)
- Clan Games leaderboard missing expected rows
- member left with no known prior join event

Diagnostics should be included in workflow artifacts and summarized in logs.
