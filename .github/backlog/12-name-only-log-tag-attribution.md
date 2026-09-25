---
title: "Attribute name-only ClashPerk logs to player tags (deferred)"
labels: [phase-2, "area:aggregation"]
depends_on: [parser-framework-members]
---

## Status

**Superseded by GitHub issue #32.** Do not implement this file's policy.

The decision recorded here — call the Clash of Clans API only to split a known duplicate
display name, and do not build a roster client — is no longer in force. Current policy is
in `docs/DATA_CONTRACT.md` (Identity), `AGENTS.md` ("Known deferred decisions"), and
`docs/CODING_AGENT_BRIEF.md`: the current clan roster is a supplemental name→tag index on
every run, and it is identity only. This file stays as history of the old decision.

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

The player tag is still the canonical identity, and `docs/DATA_CONTRACT.md` models every
war, Clan Games, and capital event with a `player_tag`. Those tags are not in most payloads,
so something will have to resolve them — later.

This is not a blocker for `fetch`, the reporting window, or the Discord client. Name-only
parsers should emit the display name plus a diagnostic when no tag is present; they must
not invent a tag.

## Policy (decided)

1. **Default path:** resolve names from tag-bearing logs in the same reporting window
   (members join/leave/role/name, per-player capital). Do not call any external game API
   for the common case.
2. **Clash of Clans / Supercell API is allowed only** when there is a **known duplicate
   display name** that cannot be disambiguated from Discord logs alone. Never call it
   preemptively, for every player, or as the primary identity source.
3. Until that rare case is needed, **do not** build a general CoC-API identity layer.
   Document the collision risk and move on.
4. Ambiguous or unresolvable names stay diagnostics (`None` ≠ zero). Never invent a tag.

## Future scope (when a real duplicate appears)

- Build a name→tag index from `#members` events and any other tag-bearing log in the
  window.
- Handle collisions the index will have: two members with the same display name, a name
  reused after someone leaves, and a rename mid-month (the name-change log gives both the
  old and the new name against one tag).
- Decide what happens for a player who never appears in a tag-bearing log during the
  window. An unattributable war attack is a diagnostic, not a performance record, and must
  not silently become somebody else's.
- Consider whether map position plus roster ordering in the war embed can disambiguate
  within a single war.
- Call the Clash of Clans API **only** for a known duplicate name that the index cannot
  split. Do not introduce a general CoC-API data path.
- `/export wars` and `/export season` do carry tags
  (`src/commands/export/export-*.ts`), but they are manual Google Sheet exports, so they
  belong to phase 6 validation rather than to the runtime path.

## Out of scope until then

- Implementing name→tag resolution.
- Adding a Clash of Clans / Supercell API client of any kind, including a "just in case"
  identity layer.
- Changing parsers beyond recording a diagnostic when a log has a name and no tag.

## Acceptance criteria

Immediate (documentation; already the point of recording this issue):

- [x] The deferred policy is written in `AGENTS.md` ("Known deferred decisions"),
      `docs/CODING_AGENT_BRIEF.md` (hard constraint 1), and `docs/DATA_CONTRACT.md`
      (Identity). Agents must not start a resolver from this issue as it stands.

Future (only after a real duplicate forces the work, and this issue is explicitly
un-deferred):

- [ ] A documented rule in `docs/DATA_CONTRACT.md` for turning a display name into a player
      tag, including duplicate names, renames, and names seen only in name-only logs.
- [ ] The default resolver uses in-window tag-bearing logs. The CoC API is used only for a
      known duplicate that those logs cannot disambiguate, never as the primary identity
      source.
- [ ] Ambiguous or unresolvable names produce a diagnostic naming the message and the
      display name, and never an invented or guessed tag.
- [ ] Tests cover: duplicate display names, a rename inside the window, a name seen only in
      a name-only log, a name belonging to someone who left earlier in the month, and "CoC
      API is not called on an unambiguous name".
- [ ] Aggregation attributes a war attack to a tag only when the mapping is unambiguous.

## Dependencies

- Parser framework and members parser, which produce the tag-bearing events the index is
  built from. That dependency is why this stays off `agent-ready` even after parsers exist:
  the policy is to wait for a real duplicate, not to start the day members parsing lands.

## References

- `AGENTS.md` - "Known deferred decisions"
- `docs/CODING_AGENT_BRIEF.md` - hard constraint 1
- `docs/DATA_CONTRACT.md` - identity, missing-data semantics, diagnostics
- clashperk/clashperk `src/core/*-log.ts` - which log families emit a tag
