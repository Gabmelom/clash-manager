---
title: "CI: run ruff, mypy, and pytest on every pull request"
labels: ["area:ci", agent-ready]
---

## Context

The repository configures `ruff`, `mypy --strict`, and `pytest` in `pyproject.toml`, but
nothing runs them automatically - there is no `.github/workflows/` directory. With most of
the remaining work planned as parser and aggregation pull requests, and much of it done by
agents, an automated gate is worth more here than usual.

## Scope

- `.github/workflows/ci.yml` triggered on `pull_request` and on pushes to `main`.
- Python 3.12, pip cache keyed on `pyproject.toml`, `pip install -e '.[dev]'`.
- Steps: `ruff check .`, `ruff format --check .`, `mypy`, `pytest --cov=clash_reporter`.
- No secrets, and no step that can reach Discord.
- A status badge in `README.md`.

## Out of scope

The scheduled monthly report workflow, which needs secrets and is tracked separately.

## Acceptance criteria

- [ ] The workflow passes on the current `main`, or any pre-existing lint and type failures
      it exposes are fixed in the same pull request.
- [ ] A failing test or lint error fails the job.
- [ ] The workflow declares read-only permissions.
- [ ] Total runtime stays reasonable, with dependencies cached.
- [ ] The badge in `README.md` points at the workflow.

## Dependencies

None. This can land immediately and makes every later pull request cheaper to review.

## References

- `pyproject.toml` - the tool configuration to reuse
- `docs/DEVELOPMENT.md` - "GitHub Actions"
