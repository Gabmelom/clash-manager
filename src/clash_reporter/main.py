"""Command-line entry point.

V1 exposes an offline ``report`` command that renders a monthly report from a
normalized dataset JSON file. This is the first useful milestone from the README:
parse-free, secret-free, and deterministic, so it runs in CI and locally without
Discord access. Discord fetching (``fetch``/``run``) is added on top of this.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from clash_reporter import __version__
from clash_reporter.config import Settings
from clash_reporter.models import MonthlyDataset
from clash_reporter.reporting import render_report
from clash_reporter.scoring import rank_players


def _load_dataset(path: Path) -> MonthlyDataset:
    return MonthlyDataset.model_validate_json(path.read_text(encoding="utf-8"))


def _cmd_report(args: argparse.Namespace) -> int:
    settings = Settings()
    dataset = _load_dataset(args.input)
    ranked = rank_players(dataset, settings.scoring)
    report = render_report(dataset, ranked, top_n=args.top)
    if args.dry_run:
        print(report)
        return 0
    try:
        settings.require_discord()
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print("Posting to Discord is not implemented yet; use --dry-run.", file=sys.stderr)
    return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="clash-reporter", description=__doc__)
    parser.add_argument("--version", action="version", version=f"clash-reporter {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    report = subparsers.add_parser(
        "report", help="Render a monthly report from a normalized dataset JSON file."
    )
    report.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Path to a normalized MonthlyDataset JSON file.",
    )
    report.add_argument("--top", type=int, default=5, help="Number of top performers to show.")
    report.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the report instead of posting to Discord.",
    )
    report.set_defaults(func=_cmd_report)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
