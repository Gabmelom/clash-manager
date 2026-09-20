---
title: "Attribute name-only ClashPerk logs to player tags"
labels: [phase-2, "area:aggregation", needs-fixtures]
depends_on: [parser-framework-members]
---

## Context

Discovered while grounding the fixture corpus in ClashPerk's source
([clashperk/clashperk](https://github.com/clashperk/clashperk), `src/core/*-log.ts`): most
log families never emit a player tag.

| Log | Builder | Identifies a player by |
| --- | --- | --- |
| member join / leave / role / name change | `clan-log.ts` `getPlayerLogEmbed` | name **and tag** (embed title `\u200e{name} ({tag})`) |
| capital contribution / raid | `clan-log.ts` `getPlayerLogEmbed` | name **and tag** |
| war and CWL attacks | `clan-war-log.ts` `getAttackLogMessage` | **name only**, in message `content` |
| missed attacks | `clan-war-log.ts` `getRemaining` | **name only**, plus map position |
| CWL lineup changes | `clan-war-log.ts` `getLineupChangeEmbed` | **name only**, plus map position |
| Clan Games leaderboard | `clan-games.helper.ts` | **name only** |
| capital weekly summary | `capital-log.ts` | **name only** |
| donations | `donation-log.ts` | **name only** |

The project's first hard constraint is that the player tag is the canonical identity, and
`docs/DATA_CONTRACT.md` models every war, Clan Games, and capital event with a
`player_tag`. Those tags are not in the payloads, so something has to resolve them.

This is not a blocker for the `fetch` command, and it does not change the reporting window
or the Discord client. It does change what the war, Clan Games, capital, and donation
parsers can promise, so it should be settled before those parsers assert a tag.

## Scope

Decide and implement how a display name in a name-only log becomes a player tag, or
becomes an explicit diagnostic when it cannot.

Starting points to evaluate:

- Build a name to tag index from `#cp-members` events, which do carry tags, and from any
  other tag-bearing log in the window.
- Handle the collisions the index will have: two members with the same display name, a
  name reused after someone leaves, and a rename mid-month (the name-change log gives both
  the old and the new name against one tag).
- Decide what happens for a player who never appears in a tag-bearing log during the
  window. `None` is not zero: an unattributable war attack is a diagnostic, not a
  performance record, and must not silently become somebody else's.
- Consider whether map position plus roster ordering in the war embed can disambiguate
  within a single war.
- `/export wars` and `/export season` do carry tags
  (`src/commands/export/export-*.ts`), but they are manual Google Sheet exports, so they
  belong to phase 6 validation rather than to the runtime path.

## Out of scope

Calling the Supercell API to resolve a name. The project does not talk to Supercell.

## Acceptance criteria

- [ ] A documented rule in `docs/DATA_CONTRACT.md` for turning a display name into a player
      tag, including the ambiguity cases above.
- [ ] Ambiguous or unresolvable names produce a diagnostic naming the message and the
      display name, and never an invented or guessed tag.
- [ ] Tests cover: duplicate display names, a rename inside the window, a name seen only in
      a name-only log, and a name belonging to someone who left earlier in the month.
- [ ] Aggregation attributes a war attack to a tag only when the mapping is unambiguous.

## Dependencies

- Parser framework and members parser, which produce the tag-bearing events the index is
  built from.

## References

- `docs/DATA_CONTRACT.md` - identity, deduplication, diagnostics
- `docs/DEVELOPMENT.md` - "ClashPerk's source is the payload reference"
- `tests/fixtures/README.md` - which fixture demonstrates each shape
