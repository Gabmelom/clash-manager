# Monthly Report Specification

The report should help clan leadership quickly answer two questions:

1. Who contributed consistently this month?
2. Who should be reviewed because of repeated low participation or missed obligations?

It should not automatically perform promotions, demotions, or kicks.

## Sections

### 1. Header / month summary

Example:

```text
🏰 Clan Monthly Report - August 2026

42 ranking-eligible members
5 new members
3 departed members
8 regular wars
7 CWL rounds
Clan Games completed
4 Raid Weekends
```

### 2. Top Performers

Keep the main Discord output short, ideally top 3 to top 5.

Example:

```text
🏆 Top Performers

1. Player A - 91.4
   War: 100% attacks used | 2.71 avg stars
   CWL: 7/7 attacks | 2.43 avg stars
   Games: 4,000 | Capital: 71,500

2. Player B - 88.2
   ...
```

The score should always be accompanied by enough component data to explain it.

### 3. Needs Review

Use evidence, not just a low opaque number.

Example:

```text
⚠️ Needs Review

Player X
- 3 regular war attacks missed
- 71% attack usage
- 800 Clan Games points

Player Y
- 2 CWL attacks missed
- No Raid Weekend participation recorded
```

Avoid flagging a player solely because they were new for most of the month.

### 4. New Members

Example:

```text
🆕 New Members
- Player Q - joined Aug 24 - not ranking eligible
- Player R - joined Aug 29 - not ranking eligible
```

### 5. Departed Members

Example:

```text
👋 Departed Members
- Player Z - left Aug 12
```

Whether departed members remain in rankings should be configurable. Recommended V1 behavior: list separately and exclude from promotion / review rankings.

### 6. Data-quality note

Only show this section when needed.

Example:

```text
ℹ️ Data notes
- 1 ClashPerk message used an unsupported layout and was ignored.
- Capital contribution data was unavailable for Aug 9.
```

## Initial scoring philosophy

Do not start by reproducing the old spreadsheet as one exact formula.

V1 should first calculate trustworthy raw metrics. Then apply a small, transparent weighted score.

Suggested starting categories:

```text
Reliability / participation    40%
War + CWL performance          30%
Clan Games contribution        15%
Capital contribution           15%
```

These weights are placeholders and should live in configuration.

Donations can be displayed without affecting the score until clan leadership decides they should matter.

## Reliability

Candidate inputs:

- regular war attack usage %
- regular war missed attacks
- CWL attack usage %
- CWL missed attacks

Reliability should normally matter more than a small difference in average stars.

## War performance

Candidate inputs:

- average regular war stars
- average CWL stars
- destruction %, if reliably available

Avoid rewarding a player simply for participating in more wars if participation itself is already scored separately.

## Clan Games

Potential normalization:

```text
min(points / 4000, 1.0)
```

If game rules or thresholds change, make the cap configurable.

## Capital

Raw contribution is often highly skewed.

Prefer a clan-relative score such as percentile or normalized rank rather than letting one very large absolute value dominate the composite score.

Example options to evaluate later:

- percentile among ranking-eligible members
- winsorized min-max normalization
- fixed contribution thresholds

## Review rules

The Review section should not simply be "bottom N".

Prefer rules such as:

```text
eligible member
AND
at least 2 negative signals
```

Possible negative signals:

- regular war attack usage below threshold
- CWL missed attack
- Clan Games below threshold
- no capital participation
- multiple missed attacks

A score can help sort review candidates but should not be the only reason they appear.

## Ranking exclusions

Suggested V1 exclusions:

- member has fewer than `MIN_ELIGIBLE_DAYS`
- member left before the end of the month
- critical source data for that player is missing

Do not treat missing source data as poor performance.

## Full-data attachment

The Discord report should stay concise. Optionally attach a CSV containing all eligible members.

Suggested columns:

```text
Player Tag
Player Name
Eligible Days
Overall Score
Regular Wars
Regular Attacks Used
Regular Attacks Missed
Regular Attack Usage %
Regular Avg Stars
CWL Rounds
CWL Attacks Used
CWL Attacks Missed
CWL Attack Usage %
CWL Avg Stars
Clan Games Points
Capital Contribution
Raid Attacks
Donated
Received
Flags
```

## Deterministic output

Given the same normalized monthly dataset and configuration, the report must always produce the same score and ordering.

Tie-breakers should be explicit, for example:

1. overall score descending
2. reliability score descending
3. player tag ascending
