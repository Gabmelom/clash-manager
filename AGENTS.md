# Agent Guide

Shared instructions for humans and coding agents working on **clash-reporter**, a monthly
Clash of Clans clan report built on ClashPerk's Discord logs.

Read `docs/CODING_AGENT_BRIEF.md` before writing code. It contains the hard constraints
(no Supercell API, no Gateway bot, no database, player tag is the identity).

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

Run `ruff check .`, `mypy`, and `pytest` before opening a pull request.

## Code expectations

- Keep Discord transport, ClashPerk parsing, aggregation, scoring, and rendering in separate
  modules. No Discord payload parsing in scoring code; no business logic in the HTTP client.
- Parsers and scoring are pure functions driven by fixtures. Add a fixture before adding a
  parser branch.
- `None` means unknown, `0` means observed zero. Never substitute one for the other.
- Never log `DISCORD_BOT_TOKEN`; never commit tokens or unsanitized payloads.
- Scoring weights and thresholds belong in `clash_reporter.config`, not in call sites.

## Cursor Cloud specific instructions

- There is no Discord access from CI or from a Cloud Agent sandbox. Verify changes with
  `pytest` and with offline CLI runs against fixtures under `tests/fixtures/`.
- Exercise the Discord client with mocked `httpx` transports rather than live API calls.
- The GitHub token available to Cloud Agents is read-only, so agents cannot file issues
  themselves. Add the issue to `.github/backlog/` and tell the user to run
  `python scripts/backlog.py sync`.
