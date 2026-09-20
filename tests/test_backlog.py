"""Tests for the issue-seeding tooling in ``scripts/backlog.py``.

The script is deliberately dependency-free and lives outside the package, so it is loaded
by path rather than imported.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_backlog_module() -> ModuleType:
    path = REPO_ROOT / "scripts" / "backlog.py"
    spec = importlib.util.spec_from_file_location("backlog_script", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolves annotations through sys.modules, so register before executing.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


backlog = _load_backlog_module()


class FakeGh(backlog.GhCli):  # type: ignore[misc, name-defined]
    """Records gh invocations and replays canned responses."""

    def __init__(
        self,
        *,
        labels: list[str] | None = None,
        issues: dict[str, int] | None = None,
    ) -> None:
        self.labels = labels or []
        self.issues = issues or {}
        self.calls: list[tuple[list[str], str | None]] = []
        self._next_number = 100

    def run(self, args: Any, stdin: str | None = None) -> str:
        args = list(args)
        self.calls.append((args, stdin))
        if args[:2] == ["label", "list"]:
            return json.dumps([{"name": name} for name in self.labels])
        if args[:2] == ["issue", "list"]:
            return json.dumps(
                [{"number": number, "title": title} for title, number in self.issues.items()]
            )
        if args[:2] == ["label", "create"]:
            self.labels.append(args[2])
            return ""
        if args[:2] == ["issue", "create"]:
            self._next_number += 1
            return f"https://github.com/Gabmelom/clash-manager/issues/{self._next_number}\n"
        raise AssertionError(f"unexpected gh call: {args}")


def _issue(
    issue_id: str,
    *,
    labels: list[str] | None = None,
    depends_on: list[str] | None = None,
    tracks: list[str] | None = None,
    body: str = "## Acceptance criteria\n- [ ] done\n\n## Dependencies\nNone\n",
) -> Any:
    return backlog.BacklogIssue(
        id=issue_id,
        title=f"Title for {issue_id}",
        labels=labels if labels is not None else ["enhancement"],
        depends_on=depends_on or [],
        tracks=tracks or [],
        body=body,
        path=Path(f"{issue_id}.md"),
    )


# --------------------------------------------------------------------------------------
# Front matter parsing
# --------------------------------------------------------------------------------------


def test_parse_mapping_handles_scalars_inline_and_block_lists() -> None:
    parsed = backlog.parse_mapping(
        'title: "Discord REST client: pagination"\n'
        'labels: [phase-1, "area:discord", agent-ready]\n'
        "tracks:\n"
        "  - one\n"
        "  - two\n"
    )
    assert parsed["title"] == "Discord REST client: pagination"
    assert parsed["labels"] == ["phase-1", "area:discord", "agent-ready"]
    assert parsed["tracks"] == ["one", "two"]


def test_parse_mapping_rejects_unsupported_syntax() -> None:
    with pytest.raises(backlog.BacklogError):
        backlog.parse_mapping("nested:\n  key: value\n")


def test_load_issue_derives_id_from_filename(tmp_path: Path) -> None:
    path = tmp_path / "07-some-issue.md"
    path.write_text(
        "---\ntitle: Some issue\nlabels: [enhancement]\n---\n\n## Body\n",
        encoding="utf-8",
    )
    assert backlog.load_issue(path).id == "some-issue"


def test_load_issue_requires_front_matter(tmp_path: Path) -> None:
    path = tmp_path / "01-broken.md"
    path.write_text("no front matter here\n", encoding="utf-8")
    with pytest.raises(backlog.BacklogError):
        backlog.load_issue(path)


# --------------------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------------------


def test_committed_backlog_is_valid() -> None:
    issues = backlog.load_backlog()
    labels = backlog.load_labels()
    assert backlog.validate(issues, labels) == []
    assert len(issues) >= 2


def test_committed_backlog_has_an_epic_tracking_every_issue() -> None:
    issues = backlog.load_backlog()
    epics = [issue for issue in issues if issue.is_epic]
    assert len(epics) == 1
    tracked = set(epics[0].tracks)
    assert tracked == {issue.id for issue in issues} - {epics[0].id}


def test_validate_rejects_undeclared_label() -> None:
    errors = backlog.validate([_issue("a", labels=["made-up"])], backlog.load_labels())
    assert any("not declared" in error for error in errors)


def test_validate_rejects_unknown_dependency() -> None:
    errors = backlog.validate([_issue("a", depends_on=["ghost"])], backlog.load_labels())
    assert any("unknown issue id" in error for error in errors)


def test_validate_rejects_agent_ready_with_open_dependency() -> None:
    issues = [_issue("a", labels=["agent-ready"], depends_on=["b"]), _issue("b")]
    errors = backlog.validate(issues, backlog.load_labels())
    assert any("agent-ready but blocked" in error for error in errors)


def test_validate_requires_acceptance_criteria() -> None:
    errors = backlog.validate([_issue("a", body="## Dependencies\nNone\n")], backlog.load_labels())
    assert any("Acceptance criteria" in error for error in errors)


def test_validate_detects_dependency_cycle() -> None:
    issues = [_issue("a", depends_on=["b"]), _issue("b", depends_on=["a"])]
    errors = backlog.validate(issues, backlog.load_labels())
    assert any("cycle" in error for error in errors)


def test_validate_rejects_placeholder_for_unknown_issue() -> None:
    body = "## Acceptance criteria\n- [ ] {{issue:nope}}\n\n## Dependencies\nNone\n"
    errors = backlog.validate([_issue("a", body=body)], backlog.load_labels())
    assert any("placeholder for unknown issue" in error for error in errors)


# --------------------------------------------------------------------------------------
# Ordering
# --------------------------------------------------------------------------------------


def test_creation_order_places_dependencies_first() -> None:
    ordered = backlog.creation_order(backlog.load_backlog())
    positions = {issue.id: index for index, issue in enumerate(ordered)}
    for issue in ordered:
        for dependency in issue.depends_on:
            assert positions[dependency] < positions[issue.id], issue.id


def test_epic_is_created_last_so_it_can_link_numbers() -> None:
    ordered = backlog.creation_order(backlog.load_backlog())
    assert ordered[-1].is_epic


# --------------------------------------------------------------------------------------
# Sync
# --------------------------------------------------------------------------------------


def test_sync_creates_only_missing_labels_that_are_used() -> None:
    labels = [
        backlog.Label("phase-1", "c2e0c6", "phase one"),
        backlog.Label("agent-ready", "0e8a16", "ready"),
        backlog.Label("unused", "ffffff", "never applied"),
    ]
    gh = FakeGh(labels=["phase-1"])
    result = backlog.sync([_issue("a", labels=["phase-1", "agent-ready"])], labels, gh)
    assert result.created_labels == ["agent-ready"]


def test_sync_skips_issues_that_already_exist() -> None:
    issues = [_issue("a"), _issue("b")]
    gh = FakeGh(issues={"Title for a": 7})
    result = backlog.sync(issues, backlog.load_labels(), gh)
    assert result.skipped_issues == ["a"]
    assert [issue_id for issue_id, _ in result.created_issues] == ["b"]


def test_sync_resolves_placeholders_to_real_issue_numbers() -> None:
    epic_body = "## Tracked issues\n- [ ] {{issue:dep}}\n\n## Acceptance criteria\n- [ ] shipped\n"
    issues = [
        _issue("dep"),
        _issue("epic", labels=["epic"], tracks=["dep"], body=epic_body),
    ]
    gh = FakeGh()
    backlog.sync(issues, backlog.load_labels(), gh)

    created = [(args, stdin) for args, stdin in gh.calls if args[:2] == ["issue", "create"]]
    assert len(created) == 2
    dep_number = 101
    epic_args, epic_body_sent = created[1]
    assert "--title" in epic_args
    assert epic_body_sent is not None
    assert f"#{dep_number}" in epic_body_sent
    assert "{{issue:" not in epic_body_sent


def test_sync_dry_run_makes_no_changes() -> None:
    gh = FakeGh()
    result = backlog.sync([_issue("a")], backlog.load_labels(), gh, dry_run=True)
    assert [issue_id for issue_id, _ in result.created_issues] == ["a"]
    assert all(args[:2] not in (["issue", "create"], ["label", "create"]) for args, _ in gh.calls)


def test_render_marks_unfiled_references_instead_of_leaving_placeholders() -> None:
    body = "## Acceptance criteria\n- [ ] {{issue:dep}}\n\n## Dependencies\nNone\n"
    rendered = _issue("a", body=body).render({})
    assert "{{issue:" not in rendered
    assert "`dep` (not filed yet)" in rendered
