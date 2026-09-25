# Fixtures

## `normalized/`

Hand-written `MonthlyDataset` input for scoring and reporting tests.

## ClashPerk log fixtures

`members/`, `wars/`, `cwl/`, `capital/`, `clan-games/`, and `donations/` hold raw Discord
message objects shaped like the ones ClashPerk posts. Each file is one message, exactly as
`GET /channels/{channel.id}/messages` returns it.

### Provenance

These are **synthetic but faithful**: the embeds, content strings, emoji IDs, colors, and
field ordering are transcribed from ClashPerk's own log builders in
[clashperk/clashperk](https://github.com/clashperk/clashperk) at commit `c78b459`.

| Fixture | Built by |
| --- | --- |
| `members/join.json`, `members/leave.json` | `src/core/clan-log.ts` - `getPlayerLogEmbed`, `JOINED` / `LEFT` |
| `members/role-change.json` | `src/core/clan-log.ts` - `getPlayerLogEmbed`, `PROMOTED` |
| `members/name-change.json` | `src/core/clan-log.ts` - `getPlayerLogEmbed`, `NAME_CHANGE` |
| `wars/attack.json`, `cwl/attack.json` | `src/core/clan-war-log.ts` - `getAttackLogMessage` |
| `wars/attack-missing-fields.json` | same builder; destruction / TH emojis omitted to pin `None` ≠ `0` |
| `wars/missed-attacks.json`, `cwl/missed-attacks.json` | `src/core/clan-war-log.ts` - `getRemaining` |
| `wars/embed-final.json` | `src/core/clan-war-log.ts` - `getRegularWarEmbed`, `warEnded` |
| `cwl/embed-round.json` | `src/core/clan-war-log.ts` - `getLeagueWarEmbed`, `warEnded`, footer `Round #N` |
| `cwl/lineup-change.json` | `src/core/clan-war-log.ts` - `getLineupChangeEmbed` |
| `wars/unknown-layout.json`, `cwl/unknown-layout.json` | not a ClashPerk builder; unknown-layout diagnostics |
| `capital/contribution.json`, `capital/raid-attack.json` | `src/core/clan-log.ts` - `CAPITAL_GOLD_CONTRIBUTION` / `CAPITAL_GOLD_RAID` |
| `capital/weekly-summary.json` | `src/core/capital-log.ts` - `capitalAttacks` |
| `clan-games/final-leaderboard.json` | `src/helper/clan-games.helper.ts` - `clanGamesEmbedMaker` |
| `donations/monthly-summary.json` | `src/core/donation-log.ts` - `rangeDonation` |

Emoji IDs, embed colors, and role names come from `src/util/emojis.ts` and
`src/util/constants.ts` (`COLOR_CODES`, `PLAYER_ROLES_MAP`).

### What is invented

Only the identities and the numbers:

- Clan `Maple Legends (#2QP9VL8C)`, rival `Northern Lights (#8LQJ2CGU)`.
- Players `Aurora (#2Y0LRPV8Q)`, `Borealis (#8QCU29VJ0)`, `Cascade (#9YLG2PJRQ)`,
  `Dune`, `Everest`. Tags use the real Clash of Clans tag alphabet.
- Channel IDs `4000000000000000xx` and webhook IDs `3000000000000000xx`, matching the
  pseudonym style `clash-reporter fetch --sanitize` produces.
- Message IDs are real snowflakes whose embedded timestamp matches the message
  `timestamp`, so window and pagination logic can be exercised against them.
- Timestamps sit in August 2026 (a complete month), except the donation summary, which
  ClashPerk posts just after the period it covers.

### Structural facts these fixtures pin down

- Every log is posted through a **webhook**, so `webhook_id` is set and `author.id` is the
  same snowflake. `guild_id` is absent: the REST message object does not carry it.
- The war and CWL **attack logs are plain `content`, not embeds**, and they identify
  players by **name only** - no player tag.
- Missed-attack, lineup-change, Clan Games, capital summary, and donation embeds are also
  **name-only**. Tags appear only in the per-player member and capital logs, whose embed
  title is `\u200e{name} ({tag})`.
- Clan Games and war embeds are **edited in place**, so `edited_timestamp` is set and the
  payload holds the final state rather than history.

### Replacing these with real captures

These exist so parser work can start before a live capture. Once
`clash-reporter fetch --sanitize` has run against the real server, prefer a captured
message: promote it as described in `docs/DEVELOPMENT.md` and delete or supersede the
synthetic file if the real shape differs. A difference between the two is a finding worth
recording on the issue, not something to paper over.
