# Roadmap

The project should be built incrementally. Do not start by implementing every ClashPerk message type or a complex scoring formula.

## Phase 0 - Discord and ClashPerk setup

### Tasks

- Create dedicated ClashPerk data channels.
- Configure the required ClashPerk logs.
- Create a Discord application and bot user for the monthly reporter.
- Give the reporter read-only access to data channels.
- Give the reporter send access to `#clan-reports`.
- Allow at least several days of representative ClashPerk messages to accumulate.

### Done when

- Each expected ClashPerk log type appears in its intended channel.
- The reporting bot can read historical messages from those channels.
- The reporting bot can post a test message to `#clan-reports`.

---

## Phase 1 - Fixture capture and parser foundation

Build against real Discord message payloads before building scoring.

### Tasks

- Implement Discord REST client for `GET /channels/{channel.id}/messages`.
- Add pagination support.
- Add a development command that saves raw channel payloads to local JSON fixtures.
- Redact or avoid committing sensitive Discord IDs if desired.
- Define normalized models in `models.py`.
- Implement parsers one channel at a time:
  1. members
  2. regular wars
  3. CWL
  4. Clan Games
  5. capital
  6. donations, optional
- Store unknown / unparsed messages in parser diagnostics rather than silently dropping them.

### Done when

- Every captured fixture is either parsed or explicitly classified as ignored / unsupported.
- Parser tests use real payload structures.
- A player tag can be extracted reliably wherever ClashPerk exposes one.

---

## Phase 2 - Monthly aggregation

### Tasks

- Implement reporting window calculation using `REPORT_TIMEZONE`.
- Reconstruct membership intervals from join / leave events.
- Track name changes without changing player identity.
- Track role changes separately from performance.
- Build a `MonthlyPlayerSummary` for every player observed in the window.
- Aggregate regular war and CWL separately.
- Aggregate Clan Games and Capital data.
- Add completeness / data-quality warnings.

### Important rules

- Player tag is the canonical identifier.
- Reporting month boundaries are timezone-aware.
- Regular war and CWL are separate datasets.
- Do not penalize a player for data that cannot be attributed reliably.

### Done when

- A local run can produce normalized monthly JSON for a set of fixtures.
- Join / leave edge cases have tests.
- Cross-month war edge cases have defined behavior.

---

## Phase 3 - Metrics and rankings

Start with transparent metrics. Avoid a complicated composite score until the raw report is trusted.

### Tasks

- Calculate:
  - days in clan
  - ranking eligibility
  - wars participated
  - regular war attacks available / used / missed
  - regular war attack usage %
  - regular war average stars
  - CWL attacks available / used / missed
  - CWL attack usage %
  - CWL average stars
  - Clan Games points
  - Capital contribution / participation
  - donations, if enabled
- Define configurable minimum eligibility thresholds.
- Produce Top Performers using a documented scoring formula.
- Produce Review Candidates using documented warning rules.
- Explain each player's ranking using component metrics.

### Guardrails

- No automatic kick / promotion actions.
- Avoid ranking brand-new members against full-month members.
- Require more than one negative signal before flagging someone for review where practical.
- Keep scoring constants in configuration, not hardcoded throughout the codebase.

### Done when

- Rankings are deterministic.
- Every score can be explained from displayed component metrics.
- Tests cover ties, new members, missing data, zero wars, and partial-month membership.

---

## Phase 4 - Discord report rendering

### Tasks

- Render a concise Discord-friendly monthly report.
- Include:
  - month summary
  - Top Performers
  - Review / Needs Attention
  - New Members
  - Departed Members
  - optional full CSV / JSON attachment
- Split output safely if Discord message / embed limits are exceeded.
- Add a dry-run mode that prints output without posting it.

### Done when

- A local dry-run produces the expected report.
- A test run posts successfully to a development Discord channel.

---

## Phase 5 - Scheduled execution

### Tasks

- Add GitHub Actions workflow with:
  - `workflow_dispatch`
  - monthly cron schedule
- Store Discord token and channel IDs in GitHub secrets / variables.
- Calculate the previous calendar month automatically.
- Save raw input JSON, normalized JSON, and diagnostics as workflow artifacts.
- Fail safely if a required channel is inaccessible.
- Do not post a partial report unless explicitly configured.

### Suggested schedule

Run on the first day of each month after midnight in a stable UTC time that safely falls on the first day in `REPORT_TIMEZONE`.

Because GitHub Actions cron is UTC, the application itself should determine the actual previous month using `REPORT_TIMEZONE` rather than assuming the cron timezone.

### Done when

- Manual workflow run succeeds end-to-end.
- Scheduled job can run without any persistent infrastructure.

---

## Phase 6 - Validation against ClashPerk exports

Use ClashPerk exports as an audit tool, not as a runtime dependency.

### Tasks

- Compare monthly report values with `/export season` and `/export wars` for the same period.
- Document expected differences caused by message-edit behavior or polling limitations.
- Add regression fixtures when discrepancies expose parser bugs.

### Done when

- Core values match exports closely enough to trust the automated report.
- Known mismatches are explained rather than ignored.

---

## Later ideas

Only consider these after V1 is stable:

- Configurable promotion / demotion recommendation policies
- Month-over-month trend section
- Multi-clan support
- Persisted historical summaries
- Google Sheet export for archival purposes
- Web dashboard
- Activity Score support if ClashPerk exposes a durable numeric value
- More sophisticated war-quality metrics such as target difficulty
