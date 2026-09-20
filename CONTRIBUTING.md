# Contributing

This is currently a small personal automation project. Keep contributions incremental and easy to verify.

## Pull request expectations

- Keep PRs focused on one architectural layer where possible.
- Add or update tests for parsing, aggregation, and scoring behavior.
- Add real sanitized fixtures when supporting a new ClashPerk message format.
- Update documentation when configuration or report behavior changes.
- Avoid combining parser changes with unrelated scoring changes in the same PR.

## Commit useful fixtures

Sanitized Discord JSON payloads are valuable test assets because ClashPerk message structure is the main integration contract.

Before committing a fixture:

- remove bot tokens or authorization headers
- consider replacing guild / user IDs if privacy matters
- preserve Discord message / embed structure
- preserve player tags if they are needed to test parsing, or replace them consistently

## Breaking changes

Treat changes to normalized event models and scoring configuration as explicit changes. Update:

- tests
- `docs/DATA_CONTRACT.md`
- `docs/REPORT_SPEC.md`

when those contracts change.
