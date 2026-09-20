# ClashPerk and Discord Setup

This document defines the channel contract expected by the monthly reporter.

ClashPerk supports enabling logs per clan and routing each log to a channel or thread with:

```text
/setup clan-logs clan:#CLAN_TAG channel:#channel
```

Reference: https://docs.clashperk.com/features/logs

## 1. Create category and channels

Create a private category:

```text
CLASHPERK DATA
```

Create:

```text
#cp-members
#cp-wars
#cp-cwl
#cp-capital
#cp-games
#cp-donations
```

Create the output channel separately:

```text
#clan-reports
```

`#cp-donations` is optional for V1.

## 2. Confirm the clan is linked to ClashPerk

If needed:

```text
/setup clan clan:#CLAN_TAG
```

Reference: https://docs.clashperk.com/overview/getting-set-up

## 3. Configure `#cp-members`

Run:

```text
/setup clan-logs clan:#CLAN_TAG channel:#cp-members
```

Enable:

- Member Join/Leave Log
- Role Change Log
- Name Change Log

Purpose:

- reconstruct join / leave dates
- prevent partial-month members from being scored unfairly
- keep display names current while using player tag as identity
- record promotions / demotions for reporting context

## 4. Configure `#cp-wars`

Run:

```text
/setup clan-logs clan:#CLAN_TAG channel:#cp-wars
```

Enable:

- War Attack Log
- War Missed Attacks Log
- War Embed Log

Purpose:

- attacks made
- attacks missed
- war participation
- stars
- destruction where available
- final war context

The per-attack and missed-attack messages are the primary source. The War Embed is supporting context and validation.

## 5. Configure `#cp-cwl`

Run:

```text
/setup clan-logs clan:#CLAN_TAG channel:#cp-cwl
```

Enable:

- CWL Attack Log
- CWL Missed Attacks Log
- CWL Embed Log
- CWL Lineup Change Log

Optional:

- CWL Monthly Summary Log

Purpose:

- separate CWL performance from regular wars
- identify CWL attacks used and missed
- understand round-level participation / lineup changes

Do not mix CWL into regular war calculations unless a future scoring policy explicitly chooses to do so.

## 6. Configure `#cp-capital`

Run:

```text
/setup clan-logs clan:#CLAN_TAG channel:#cp-capital
```

Enable:

- Clan Capital Weekly Summary Log
- Capital Gold Contribution Log
- Capital Gold Raid Log

Purpose:

- track capital contribution
- track raid participation
- retain weekly summary context

## 7. Configure `#cp-games`

Run:

```text
/setup clan-logs clan:#CLAN_TAG channel:#cp-games
```

Enable:

- Clan Games Embed Log

ClashPerk updates one leaderboard message during the Clan Games event. The monthly job should parse the final visible state.

Reference: https://docs.clashperk.com/features/logs

## 8. Configure `#cp-donations` - optional

Run:

```text
/setup clan-logs clan:#CLAN_TAG channel:#cp-donations
```

Enable:

- Donation Log -> Daily

Why Daily:

- gives calendar-day data that can be aggregated exactly for the reporting month
- ClashPerk's Monthly donation log posts on the last Monday, which does not map cleanly to calendar-month boundaries

Donations were not part of the original spreadsheet, so this channel can be deferred.

## 9. Do not rely on Last Seen for V1

ClashPerk's Last Seen Embed Log maintains one continuously updated message. It is useful operationally but not a durable month-long event history.

The ClashPerk FAQ also defines an Activity Score, but the public log documentation does not state that a durable numeric Activity Score is emitted in Discord messages.

For V1:

- do not create an Activity Score dependency
- do not attempt to reimplement ClashPerk's activity tracking
- revisit this only if real server messages expose a stable numeric value we can collect

References:

- https://docs.clashperk.com/features/logs
- https://docs.clashperk.com/faq

## 10. Reporter bot permissions

In each `#cp-*` channel:

- View Channel
- Read Message History

In `#clan-reports`:

- View Channel
- Send Messages
- Embed Links
- Attach Files, optional

Avoid granting:

- Administrator
- Manage Roles
- Kick Members
- Ban Members
- Manage Channels

## 11. Data validation workflow

During development, keep ClashPerk's manual exports available as an audit source.

Useful manual exports can be compared to calculated results, but exports should not be a runtime dependency of the monthly job.

## Expected channel contract

| Channel | Required for V1 | Primary data |
|---|---:|---|
| `#cp-members` | Yes | joins, leaves, names, roles |
| `#cp-wars` | Yes | regular war attacks and misses |
| `#cp-cwl` | Yes | CWL attacks, misses, lineups |
| `#cp-capital` | Yes | capital contribution / raids |
| `#cp-games` | Yes | Clan Games leaderboard |
| `#cp-donations` | No | donation summaries |
| `#clan-reports` | Yes | generated monthly report |
