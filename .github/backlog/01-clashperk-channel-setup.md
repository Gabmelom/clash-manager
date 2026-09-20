---
title: "Phase 0: stand up ClashPerk data channels and the reporter bot"
labels: [phase-0, human-task, "area:discord"]
---

## Context

Every parser in this project is written against real ClashPerk payloads, so nothing
downstream can start until ClashPerk is actually logging into dedicated channels and a
reporter bot can read them. This is the one piece of V1 a coding agent cannot do: it needs
Discord server administration and a ClashPerk subscription.

It also needs lead time. Parsers cannot be written from a single day of messages, so the
channels must accumulate a representative sample: at least one regular war, ideally a CWL
season, a Clan Games event, and a Raid Weekend.

## Scope

- Create the `CLASHPERK DATA` category with `#cp-members`, `#cp-wars`, `#cp-cwl`,
  `#cp-capital`, `#cp-games`, and optionally `#cp-donations`.
- Create `#clan-reports` under clan management.
- Enable the ClashPerk logs listed in `docs/CLASHPERK_SETUP.md`, each pointed at its channel.
- Create a Discord application and bot user for the reporter, and invite it with:
  - data channels: View Channel, Read Message History
  - `#clan-reports`: View Channel, Send Messages, Embed Links, Attach Files
- Record the guild ID, channel IDs, and bot token as repository secrets/variables using the
  names in `.env.example`.

## Out of scope

Any code. This issue produces configuration and a populated Discord server.

## Acceptance criteria

- [ ] Each expected ClashPerk log type appears in its intended channel.
- [ ] The reporter bot can read history in every data channel.
- [ ] The reporter bot can post a test message to `#clan-reports`.
- [ ] The bot has no Manage Roles, Kick, Ban, or Administrator permission.
- [ ] At least one full regular war, one Clan Games event, and one Raid Weekend have been
      logged, so fixture capture has something representative to work with.
- [ ] Secrets and variables from `.env.example` exist in the repository settings.

## Dependencies

None. This blocks fixture capture and every parser.

## References

- `docs/CLASHPERK_SETUP.md`
- `ROADMAP.md` phase 0
- https://docs.clashperk.com/features/logs
- https://docs.discord.com/developers/topics/permissions
