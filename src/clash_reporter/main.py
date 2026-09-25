"""Command-line entry point.

Three commands exist today:

``report``
    Renders a monthly report from a normalized dataset JSON file. Parse-free,
    secret-free, and deterministic, so it runs in CI and locally without Discord.

``fetch``
    Downloads raw ClashPerk payloads for a reporting month into JSON files so
    parsers can be developed offline from real fixtures.

``normalize``
    Reads a fetch directory, runs the members parser, and writes a
    ``MonthlyDataset`` plus events and parser diagnostics. This is a members-only
    slice of issue #11: war/CWL/games/capital/donation fields stay missing.

Each command stays thin: window resolution, transport, capture, parsing, and
aggregation live in their own modules.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from clash_reporter import __version__
from clash_reporter.aggregation import NormalizeError, normalize_capture
from clash_reporter.aggregation.normalize import DEFAULT_NORMALIZED_OUTPUT, window_from_manifest
from clash_reporter.collection import ChannelCaptureError, capture_channels
from clash_reporter.collection.capture import MANIFEST_FILENAME
from clash_reporter.config import DATA_CHANNELS, Settings
from clash_reporter.discord_client import DiscordClient, DiscordError
from clash_reporter.models import MonthlyDataset
from clash_reporter.reporting import render_report
from clash_reporter.scoring import rank_players
from clash_reporter.window import InvalidMonthError, ReportingWindow, resolve_month

DEFAULT_RAW_OUTPUT = Path("./artifacts/raw")


def _load_dataset(path: Path) -> MonthlyDataset:
    return MonthlyDataset.model_validate_json(path.read_text(encoding="utf-8"))


def _fail(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return 2


def _cmd_report(args: argparse.Namespace) -> int:
    settings = Settings()
    dataset = _load_dataset(args.input)
    if args.month:
        try:
            window = resolve_month(args.month, timezone=settings.report_timezone)
        except InvalidMonthError as exc:
            return _fail(str(exc))
        dataset = dataset.model_copy(update={"month_label": window.month_label})
    ranked = rank_players(dataset, settings.scoring)
    report = render_report(dataset, ranked, top_n=args.top)
    if args.dry_run:
        print(report)
        return 0
    try:
        settings.require_discord()
    except RuntimeError as exc:
        return _fail(str(exc))
    print("Posting to Discord is not implemented yet; use --dry-run.", file=sys.stderr)
    return 2


def _cmd_fetch(args: argparse.Namespace) -> int:
    settings = Settings()
    try:
        window = resolve_month(args.month, timezone=settings.report_timezone)
        token = settings.require_bot_token()
        channels = settings.require_data_channels(args.channel)
    except (InvalidMonthError, RuntimeError) as exc:
        return _fail(str(exc))

    print(
        f"Fetching {window.month_label} ({window.month_key}) in {window.timezone}"
        + ("" if window.is_complete() else " - month still in progress, capture is partial")
    )
    with DiscordClient(token, base_url=settings.discord_api_base_url) as client:
        try:
            run = capture_channels(
                client,
                channels=channels,
                window=window,
                output_dir=args.output,
                sanitize=args.sanitize,
            )
        except (ChannelCaptureError, DiscordError) as exc:
            return _fail(str(exc))

    for capture in run.channels:
        print(f"  {capture.name}: {capture.message_count} messages -> {capture.path}")
    print(f"Manifest: {run.manifest_path}")
    return 0


def _cmd_normalize(args: argparse.Namespace) -> int:
    settings = Settings()
    try:
        window = _resolve_normalize_window(args, settings.report_timezone)
        result = normalize_capture(args.input, args.output, window=window)
    except (InvalidMonthError, NormalizeError) as exc:
        return _fail(str(exc))

    print(
        f"Normalizing {result.window.month_label} ({result.window.month_key}) "
        f"in {result.window.timezone} from {args.input}"
    )
    print(
        f"  {result.event_count} member events, {result.player_count} players "
        f"-> {result.dataset_path}"
    )
    print(f"  Events: {result.events_path}")
    print(f"  Diagnostics ({result.ignored_count} ignored messages): {result.diagnostics_path}")
    return 0


def _resolve_normalize_window(args: argparse.Namespace, timezone: str) -> ReportingWindow:
    if args.month:
        return resolve_month(args.month, timezone=timezone)
    window = window_from_manifest(args.input / MANIFEST_FILENAME, timezone=timezone)
    if window is None:
        raise NormalizeError(
            "Month is required when the input directory has no fetch manifest. "
            "Pass --month YYYY-MM (or 'previous' / 'current'), or normalize a "
            "`clash-reporter fetch` output directory."
        )
    return window


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
    report.add_argument(
        "--month",
        help="Label the report from a reporting window: YYYY-MM, 'previous', or 'current'.",
    )
    report.add_argument("--top", type=int, default=5, help="Number of top performers to show.")
    report.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the report instead of posting to Discord.",
    )
    report.set_defaults(func=_cmd_report)

    fetch = subparsers.add_parser(
        "fetch",
        help="Download raw ClashPerk messages for a month into JSON files.",
    )
    fetch.add_argument(
        "--month",
        default="previous",
        help=(
            "Reporting month: YYYY-MM, 'previous', or 'current'. "
            "'current' captures the month so far."
        ),
    )
    fetch.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_RAW_OUTPUT,
        help=f"Directory to write channel JSON files into (default: {DEFAULT_RAW_OUTPUT}).",
    )
    fetch.add_argument(
        "--channel",
        action="append",
        choices=list(DATA_CHANNELS),
        help="Capture only this channel. Repeatable. Defaults to every configured channel.",
    )
    fetch.add_argument(
        "--sanitize",
        action="store_true",
        help="Pseudonymize guild and Discord user IDs consistently across the capture.",
    )
    fetch.add_argument(
        "--verbose",
        action="store_true",
        help="Log each channel as it is captured, plus rate-limit and retry activity.",
    )
    fetch.set_defaults(func=_cmd_fetch)

    normalize = subparsers.add_parser(
        "normalize",
        help=(
            "Parse #cp-members from a fetch directory into a MonthlyDataset. "
            "Members-only: war/CWL/games/capital/donation fields stay missing."
        ),
    )
    normalize.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_RAW_OUTPUT,
        help=f"Fetch output directory containing cp-members.json (default: {DEFAULT_RAW_OUTPUT}).",
    )
    normalize.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_NORMALIZED_OUTPUT,
        help=(
            "Directory to write events.json, monthly_players.json, and "
            f"diagnostics/parser_warnings.json (default: {DEFAULT_NORMALIZED_OUTPUT})."
        ),
    )
    normalize.add_argument(
        "--month",
        help=(
            "Reporting month: YYYY-MM, 'previous', or 'current'. "
            "Defaults to the month recorded in the fetch manifest."
        ),
    )
    normalize.set_defaults(func=_cmd_normalize)

    parser.set_defaults(verbose=False)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
