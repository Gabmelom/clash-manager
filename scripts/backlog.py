#!/usr/bin/env python3
"""Seed the GitHub issue tracker from the backlog files in ``.github/backlog``.

Work on this repository is orchestrated through GitHub issues (see ``AGENTS.md``). Backlog
files are a seeding mechanism only: ``sync`` never edits an issue that already exists, so
once an issue is filed, GitHub is the source of truth.

    python scripts/backlog.py validate    # front matter, labels, dependencies
    python scripts/backlog.py plan        # creation order, offline
    python scripts/backlog.py render <id> # the exact body that would be posted
    python scripts/backlog.py sync        # create labels and issues through the gh CLI

Standard library only, so it runs before the project is installed.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKLOG_DIR = REPO_ROOT / ".github" / "backlog"
LABELS_FILE = REPO_ROOT / ".github" / "labels.yml"

# Labels GitHub creates with every repository; they need no definition of our own.
DEFAULT_GITHUB_LABELS = frozenset(
    {
        "bug",
        "documentation",
        "duplicate",
        "enhancement",
        "good first issue",
        "help wanted",
        "invalid",
        "question",
        "wontfix",
    }
)

PLACEHOLDER = re.compile(r"\{\{issue:([a-z0-9-]+)\}\}")
ID_PREFIX = re.compile(r"^\d+-")


class BacklogError(Exception):
    """Raised for malformed backlog input or a failed gh invocation."""


# --------------------------------------------------------------------------------------
# Minimal YAML
#
# The backlog uses a deliberately tiny subset - scalars, inline lists, and block lists - so
# that this script has no third-party dependency. Anything outside that subset is an error
# rather than a silent misparse.
# --------------------------------------------------------------------------------------


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _parse_inline_list(value: str) -> list[str]:
    inner = value[1:-1].strip()
    if not inner:
        return []
    return [_strip_quotes(item.strip()) for item in inner.split(",") if item.strip()]


def parse_mapping(text: str) -> dict[str, str | list[str]]:
    """Parse a flat mapping whose values are scalars, inline lists, or block lists."""
    result: dict[str, str | list[str]] = {}
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[:1].isspace():
            raise BacklogError(f"unexpected indentation: {line!r}")
        if ":" not in line:
            raise BacklogError(f"expected 'key: value': {line!r}")
        key, _, raw = line.partition(":")
        key = key.strip()
        value = raw.strip()
        if value.startswith("[") and value.endswith("]"):
            result[key] = _parse_inline_list(value)
        elif value:
            result[key] = _strip_quotes(value)
        else:
            items: list[str] = []
            while index < len(lines) and lines[index].lstrip().startswith("- "):
                items.append(_strip_quotes(lines[index].lstrip()[2:].strip()))
                index += 1
            result[key] = items
    return result


def parse_sequence_of_mappings(text: str) -> list[dict[str, str]]:
    """Parse a block sequence of flat mappings, as used by ``.github/labels.yml``."""
    entries: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- "):
            current = {}
            entries.append(current)
            stripped = stripped[2:].strip()
        if current is None:
            raise BacklogError(f"value outside of a list item: {line!r}")
        if ":" not in stripped:
            raise BacklogError(f"expected 'key: value': {line!r}")
        key, _, value = stripped.partition(":")
        current[key.strip()] = _strip_quotes(value.strip())
    return entries


# --------------------------------------------------------------------------------------
# Backlog model
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Label:
    name: str
    color: str
    description: str


@dataclass(frozen=True)
class BacklogIssue:
    id: str
    title: str
    labels: list[str]
    depends_on: list[str]
    tracks: list[str]
    body: str
    path: Path

    @property
    def is_epic(self) -> bool:
        return "epic" in self.labels

    def render(self, numbers: dict[str, int]) -> str:
        """Substitute ``{{issue:<id>}}`` placeholders with real issue references."""

        def replace(match: re.Match[str]) -> str:
            issue_id = match.group(1)
            number = numbers.get(issue_id)
            return f"#{number}" if number else f"`{issue_id}` (not filed yet)"

        return PLACEHOLDER.sub(replace, self.body)


def _as_list(value: str | list[str] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    raise BacklogError(f"expected a list, got {value!r}")


def load_labels(path: Path = LABELS_FILE) -> list[Label]:
    entries = parse_sequence_of_mappings(path.read_text(encoding="utf-8"))
    labels: list[Label] = []
    for entry in entries:
        if "name" not in entry:
            raise BacklogError(f"label without a name in {path}: {entry!r}")
        labels.append(
            Label(
                name=entry["name"],
                color=entry.get("color", "ededed"),
                description=entry.get("description", ""),
            )
        )
    return labels


def load_issue(path: Path) -> BacklogIssue:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise BacklogError(f"{path.name}: missing YAML front matter")
    _, _, remainder = text.partition("---\n")
    front_matter, separator, body = remainder.partition("\n---\n")
    if not separator:
        raise BacklogError(f"{path.name}: unterminated front matter")
    meta = parse_mapping(front_matter)
    title = meta.get("title")
    if not isinstance(title, str) or not title:
        raise BacklogError(f"{path.name}: front matter needs a title")
    return BacklogIssue(
        id=ID_PREFIX.sub("", path.stem),
        title=title,
        labels=_as_list(meta.get("labels")),  # type: ignore[arg-type]
        depends_on=_as_list(meta.get("depends_on")),  # type: ignore[arg-type]
        tracks=_as_list(meta.get("tracks")),  # type: ignore[arg-type]
        body=body.strip() + "\n",
        path=path,
    )


def load_backlog(directory: Path = BACKLOG_DIR) -> list[BacklogIssue]:
    return [load_issue(path) for path in sorted(directory.glob("*.md"))]


# --------------------------------------------------------------------------------------
# Validation and ordering
# --------------------------------------------------------------------------------------


def _edges(issue: BacklogIssue) -> list[str]:
    """Issues that must exist before this one is created."""
    return [*issue.depends_on, *issue.tracks]


def validate(issues: Sequence[BacklogIssue], labels: Sequence[Label]) -> list[str]:
    errors: list[str] = []
    known_labels = {label.name for label in labels} | DEFAULT_GITHUB_LABELS
    known_ids = {issue.id for issue in issues}

    seen_titles: dict[str, str] = {}
    for issue in issues:
        where = issue.path.name
        if issue.title in seen_titles:
            errors.append(f"{where}: duplicate title, also used by {seen_titles[issue.title]}")
        seen_titles[issue.title] = where

        if not issue.labels:
            errors.append(f"{where}: no labels")
        for label in issue.labels:
            if label not in known_labels:
                errors.append(f"{where}: label {label!r} is not declared in .github/labels.yml")

        for reference in _edges(issue):
            if reference not in known_ids:
                errors.append(f"{where}: references unknown issue id {reference!r}")
        for match in PLACEHOLDER.finditer(issue.body):
            if match.group(1) not in known_ids:
                errors.append(f"{where}: placeholder for unknown issue id {match.group(1)!r}")

        if "agent-ready" in issue.labels and issue.depends_on:
            errors.append(
                f"{where}: labelled agent-ready but blocked by {', '.join(issue.depends_on)}"
            )

        required = ["## Acceptance criteria"]
        required.append("## Tracked issues" if issue.is_epic else "## Dependencies")
        for section in required:
            if section not in issue.body:
                errors.append(f"{where}: missing a {section!r} section")

    try:
        creation_order(issues)
    except BacklogError as exc:
        errors.append(str(exc))
    return errors


def creation_order(issues: Sequence[BacklogIssue]) -> list[BacklogIssue]:
    """Order issues so a dependency is always created before its dependents."""
    by_id = {issue.id: issue for issue in issues}
    ordered: list[BacklogIssue] = []
    placed: set[str] = set()
    remaining = list(issues)
    while remaining:
        ready = [
            issue
            for issue in remaining
            if all(ref not in by_id or ref in placed for ref in _edges(issue))
        ]
        if not ready:
            stuck = ", ".join(sorted(issue.id for issue in remaining))
            raise BacklogError(f"dependency cycle among: {stuck}")
        for issue in ready:
            ordered.append(issue)
            placed.add(issue.id)
        remaining = [issue for issue in remaining if issue.id not in placed]
    return ordered


# --------------------------------------------------------------------------------------
# gh CLI
# --------------------------------------------------------------------------------------


class GhCli:
    """Thin wrapper around the gh executable, injectable so tests never shell out."""

    def __init__(self, executable: str = "gh") -> None:
        self.executable = executable

    def run(self, args: Sequence[str], stdin: str | None = None) -> str:
        completed = subprocess.run(
            [self.executable, *args],
            input=stdin,
            capture_output=True,
            text=True,
            # Issue bodies contain arrows and box drawing. Without this, Windows encodes
            # stdin as cp1252 and the write fails.
            encoding="utf-8",
            check=False,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            raise BacklogError(f"gh {' '.join(args)} failed: {detail}")
        return completed.stdout


@dataclass
class SyncResult:
    created_labels: list[str] = field(default_factory=list)
    created_issues: list[tuple[str, str]] = field(default_factory=list)
    skipped_issues: list[str] = field(default_factory=list)


def _existing_labels(gh: GhCli) -> set[str]:
    payload = json.loads(gh.run(["label", "list", "--limit", "200", "--json", "name"]) or "[]")
    return {entry["name"] for entry in payload}


def _existing_issues(gh: GhCli) -> dict[str, int]:
    payload = json.loads(
        gh.run(["issue", "list", "--state", "all", "--limit", "500", "--json", "number,title"])
        or "[]"
    )
    return {entry["title"]: entry["number"] for entry in payload}


def _issue_number(output: str) -> int | None:
    match = re.search(r"/issues/(\d+)", output)
    return int(match.group(1)) if match else None


def sync(
    issues: Sequence[BacklogIssue],
    labels: Sequence[Label],
    gh: GhCli,
    *,
    dry_run: bool = False,
) -> SyncResult:
    result = SyncResult()
    used = {label for issue in issues for label in issue.labels}
    present = _existing_labels(gh)
    for label in labels:
        if label.name not in used or label.name in present:
            continue
        result.created_labels.append(label.name)
        if not dry_run:
            gh.run(
                [
                    "label",
                    "create",
                    label.name,
                    "--color",
                    label.color,
                    "--description",
                    label.description,
                ]
            )

    numbers = dict(_existing_issues(gh))
    for issue in creation_order(issues):
        if issue.title in numbers:
            # Map the id too, so an issue created by an earlier run can still be referenced
            # by placeholders in one created now.
            numbers[issue.id] = numbers[issue.title]
            result.skipped_issues.append(issue.id)
            continue
        args = ["issue", "create", "--title", issue.title, "--body-file", "-"]
        for label in issue.labels:
            args += ["--label", label]
        result.created_issues.append((issue.id, issue.title))
        if dry_run:
            continue
        created = gh.run(args, stdin=issue.render(numbers))
        number = _issue_number(created)
        if number is None:
            raise BacklogError(f"could not read the new issue number from: {created.strip()}")
        numbers[issue.title] = number
        numbers[issue.id] = number
    return result


# --------------------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------------------


def _print_errors(errors: Iterable[str]) -> None:
    for error in errors:
        print(f"  error: {error}", file=sys.stderr)


def _cmd_validate(_: argparse.Namespace) -> int:
    issues = load_backlog()
    labels = load_labels()
    errors = validate(issues, labels)
    if errors:
        print(f"{len(errors)} problem(s) in {len(issues)} backlog file(s):", file=sys.stderr)
        _print_errors(errors)
        return 1
    print(f"{len(issues)} backlog issues and {len(labels)} labels are valid.")
    return 0


def _cmd_plan(_: argparse.Namespace) -> int:
    issues = load_backlog()
    labels = load_labels()
    errors = validate(issues, labels)
    if errors:
        _print_errors(errors)
        return 1
    print(f"Creation order for {len(issues)} issues:\n")
    for position, issue in enumerate(creation_order(issues), start=1):
        blocked = ", ".join(issue.depends_on) or "-"
        print(f"{position:>2}. {issue.title}")
        print(f"    id       {issue.id}")
        print(f"    labels   {', '.join(issue.labels)}")
        print(f"    blocked  {blocked}")
    ready = [i.id for i in issues if "agent-ready" in i.labels]
    print(f"\nUnblocked and ready to pick up: {', '.join(ready) or 'none'}")
    return 0


def _cmd_render(args: argparse.Namespace) -> int:
    issues = {issue.id: issue for issue in load_backlog()}
    issue = issues.get(args.id)
    if issue is None:
        print(f"unknown issue id {args.id!r}; known: {', '.join(sorted(issues))}", file=sys.stderr)
        return 1
    print(f"# {issue.title}")
    print(f"labels: {', '.join(issue.labels)}\n")
    print(issue.render({}))
    return 0


def _cmd_sync(args: argparse.Namespace) -> int:
    issues = load_backlog()
    labels = load_labels()
    errors = validate(issues, labels)
    if errors:
        _print_errors(errors)
        return 1
    result = sync(issues, labels, GhCli(), dry_run=args.dry_run)
    verb = "Would create" if args.dry_run else "Created"
    print(
        f"{verb} {len(result.created_labels)} label(s): {', '.join(result.created_labels) or '-'}"
    )
    print(f"{verb} {len(result.created_issues)} issue(s):")
    for _, title in result.created_issues:
        print(f"  {title}")
    if result.skipped_issues:
        print(f"Skipped {len(result.skipped_issues)} existing: {', '.join(result.skipped_issues)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="backlog", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_cmd = subparsers.add_parser("validate", help="Check the backlog files.")
    validate_cmd.set_defaults(func=_cmd_validate)

    plan_cmd = subparsers.add_parser("plan", help="Show the creation order without calling gh.")
    plan_cmd.set_defaults(func=_cmd_plan)

    render_cmd = subparsers.add_parser("render", help="Print one rendered issue body.")
    render_cmd.add_argument("id")
    render_cmd.set_defaults(func=_cmd_render)

    sync_cmd = subparsers.add_parser("sync", help="Create missing labels and issues via gh.")
    sync_cmd.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be created without creating anything.",
    )
    sync_cmd.set_defaults(func=_cmd_sync)
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        # Rendered bodies are UTF-8; the default Windows console encoding is not.
        stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except BacklogError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
