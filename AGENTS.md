# Agent Guide

Shared instructions for humans and coding agents working on **clash-reporter**, a monthly
Clash of Clans clan report built on ClashPerk's Discord logs.

Read `docs/CODING_AGENT_BRIEF.md` before writing code. It contains the hard constraints
(no Gateway bot, no database, player tag is the identity; the Clash of Clans API is
an identity-only clan roster, see **Known deferred decisions** below).

## Work is orchestrated through GitHub issues

GitHub issues are the unit of work for this repository. One issue describes one shippable
slice; the roadmap phase it belongs to is a label, not a separate tracker.

Rules:

1. **Start from an issue.** Before writing code, pick the issue you are implementing. If no
   issue covers the work, open one first and link it.
2. **One issue, one branch, one pull request.** Keep the PR inside a single architectural
   layer wherever possible (see `CONTRIBUTING.md`).
3. **Close by reference.** Every PR body must contain `Closes #<number>` for the issue it
   completes, or `Refs #<number>` when it only advances it.
4. **Respect `depends_on`.** An issue that is blocked lists its blockers in its Dependencies
   section. Do not start blocked work; comment on the blocker instead.
5. **Discovered work becomes a new issue.** Do not silently widen a PR's scope. File a
   follow-up issue and mention it in the PR.
6. **Report status on the issue.** Findings that change the plan (an unexpected ClashPerk
   payload shape, a wrong assumption in the docs) belong in an issue comment, not only in
   the PR description.
7. **Filed issues are the source of truth.** `.github/backlog/` only seeds the tracker; once
   an issue exists on GitHub, edit it there.

### Label taxonomy

Labels are declared in `.github/labels.yml`.

- `phase-0` … `phase-6` - the `ROADMAP.md` phase the work belongs to.
- `area:discord`, `area:parsers`, `area:aggregation`, `area:scoring`, `area:reporting`,
  `area:ci` - the module boundary from `docs/ARCHITECTURE.md` being touched.
- `agent-ready` - unblocked, fully specified, safe for an agent to pick up.
- `needs-fixtures` - cannot be finished until real ClashPerk payloads are captured.
- `human-task` - requires Discord/ClashPerk admin access a coding agent does not have.
- `epic` - tracking issue that links other issues.

### Seeding the tracker

The V1 backlog lives in `.github/backlog/` as one Markdown file per issue. To create the
GitHub issues and labels from those files:

```bash
python scripts/backlog.py validate     # check front matter, labels, dependencies
python scripts/backlog.py plan         # show what would be created
python scripts/backlog.py sync         # create labels + issues via the gh CLI
```

`sync` is idempotent: it skips labels and issues that already exist and never edits an
existing issue. It requires a `gh` login with write access to the repository.

## Pull requests are published, not proposed

Code review happens on GitHub. Chat is for deciding what to build; the pull request is where
the work is judged. So:

1. **Every turn that changes code ends with an open pull request.** Commit, push, and open
   the PR before you write your summary. Never leave finished work sitting on a branch, and
   never wait for a "go ahead" in chat before opening it.
2. **Open PRs ready for review, not as drafts.** A draft says "not ready to look at", which
   is the opposite of the handoff being made.
3. **The description carries the review context.** What changed, why, how it was verified,
   and anything the reviewer should push back on. Assume the reviewer reads only GitHub.
4. **End the turn by saying the PR is open and waiting for review, with the link.** That
   sentence is the handoff. Do not bury it under a summary of the work.
5. **Decide rather than ask.** If an implementation choice is ambiguous, pick the option most
   consistent with the docs in this repository, ship it, and record the alternative you
   rejected in the PR description so it can be argued with in review.
6. **Keep the PR current.** If you change anything after opening it - including in response
   to review - push and update the description in the same turn.

If the PR tool reports that creation was only registered for approval rather than completed,
say so plainly and give the branch name, because that is an account-level Cloud Agent
setting the repository cannot override.

## Environment and commands

Python 3.12+. The virtualenv lives in `.venv` and is created by `.cursor/install.sh`.

```bash
bash .cursor/install.sh            # create .venv and install the project with dev extras
source .venv/bin/activate

pytest                             # tests
ruff check .                       # lint
ruff format --check .              # formatting
mypy                               # types (strict)

python -m clash_reporter report --input tests/fixtures/normalized/monthly_players.sample.json --dry-run
```

`clash-reporter normalize` reads a `fetch` directory, parses every channel file
that is present (`members`, `wars`, `cwl`, `clan-games`, `capital`, `donations`),
reconstructs membership, and writes a `MonthlyDataset` that `report --dry-run`
accepts. A missing channel file leaves that family's metrics `None` (unknown),
never an observed zero. See `docs/DEVELOPMENT.md`.

Run `ruff check .`, `mypy`, and `pytest` before opening a pull request.

## Code expectations

- Keep Discord transport, ClashPerk parsing, aggregation, scoring, and rendering in separate
  modules. No Discord payload parsing in scoring code; no business logic in the HTTP client.
- Parsers and scoring are pure functions driven by fixtures. Add a fixture before adding a
  parser branch.
- `None` means unknown, `0` means observed zero. Never substitute one for the other.
- Never log `DISCORD_BOT_TOKEN`; never commit tokens or unsanitized payloads.
- Scoring weights and thresholds belong in `clash_reporter.config`, not in call sites.

## Known deferred decisions

### Name-only ClashPerk logs — clan roster is a supplemental identity index

Most ClashPerk Discord logs identify a player by **display name only**. A player tag
appears only in per-player member logs (join / leave / role / name) and per-player capital
logs, in the embed title `\u200e{name} ({tag})`. War and CWL attacks, missed attacks,
lineup changes, Clan Games, capital weekly summaries, and donations are name-only.

Player tag remains the canonical identity. Attribution order:

1. Build name→tag from tag-bearing logs in the reporting window (members
   join/leave/role/name, per-player capital).
2. When `COC_API_TOKEN` and `COC_CLAN_TAG` are set, fetch the current clan member
   list and fill names that are still unmatched, if that roster name maps to one tag.
3. The Clash of Clans API is **identity only**. Do not pull wars, Clan Games, capital,
   donations, or any other metric from it. Scoring stays ClashPerk Discord-only.
4. Ambiguous names (two tags) and names absent from both indexes stay diagnostics
   (`None` ≠ zero). Never invent a tag.
5. Departed mid-month players may be missing from tonight's roster. Their Discord
   tags remain required.
6. A missing token, a missing clan tag, or an API error is a data note. Discord-only
   attribution still runs.

`.github/backlog/12-name-only-log-tag-attribution.md` (API only for a known duplicate)
is superseded. See `docs/DATA_CONTRACT.md` (Identity) and GitHub issue #32.

## Cursor Cloud specific instructions

- There is no Discord access from CI or from a Cloud Agent sandbox. Verify changes with
  `pytest` and with offline CLI runs against fixtures under `tests/fixtures/`.
- Exercise the Discord client and the CoC roster client with mocked `httpx` transports.
  Tests must not call the live Clash of Clans API.
- The GitHub token available to Cloud Agents is read-only, so agents cannot file issues
  themselves. Add the issue to `.github/backlog/` and tell the user to run
  `python scripts/backlog.py sync`.
