"""Command-line entry point.

Four commands exist today:

``report``
    Renders a monthly report from a normalized dataset JSON file. ``--dry-run``
    prints it and never touches the network. ``--post`` sends it to
    ``#clan-reports``.

``fetch``
    Downloads raw ClashPerk payloads for a reporting month into JSON files so
    parsers can be developed offline from real fixtures.

``normalize``
    Reads a fetch directory, runs the members parser, and writes a
    ``MonthlyDataset`` plus events and parser diagnostics. This is a members-only
    slice of issue #11: war/CWL/games/capital/donation fields stay missing.

``run``
    Fetches, normalizes, and renders one month. ``--post`` also delivers the
    report. Without it, the report is printed and nothing is posted. A required
    channel that cannot be read aborts before posting unless ``--allow-partial``
    is set. An empty ``#clan-games`` history is a month with no Clan Games event.

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
from clash_reporter.completeness import posting_blockers
from clash_reporter.config import DATA_CHANNELS, Settings
from clash_reporter.discord_client import DiscordClient, DiscordError
from clash_reporter.models import MonthlyDataset
from clash_reporter.reporting import (
    ReportPostError,
    ReportSplitError,
    post_monthly_report,
    render_csv,
    render_report,
)
from clash_reporter.scoring import rank_players
from clash_reporter.window import InvalidMonthError, ReportingWindow, resolve_month

DEFAULT_RAW_OUTPUT = Path("./artifacts/raw")
DEFAULT_REPORT_OUTPUT = Path("./artifacts/report")


def _load_dataset(path: Path) -> MonthlyDataset:
    return MonthlyDataset.model_validate_json(path.read_text(encoding="utf-8"))


def _fail(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return 2


def _ranked_report(dataset: MonthlyDataset, settings: Settings, top_n: int) -> tuple[str, str]:
    ranked = rank_players(dataset, settings.scoring)
    return render_report(dataset, ranked, top_n=top_n), render_csv(ranked)


def _post_report(settings: Settings, client: DiscordClient, report: str, csv_text: str) -> int:
    channel_id = settings.discord_report_channel_id
    if not channel_id:
        return _fail("Missing required Discord configuration: DISCORD_REPORT_CHANNEL_ID")
    try:
        messages = post_monthly_report(client, channel_id, report, csv_text)
    except ReportPostError as exc:
        return _fail(str(exc))
    except (DiscordError, ReportSplitError) as exc:
        return _fail(str(exc))
    print(f"Posted {len(messages)} message(s) to channel {channel_id}.")
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    settings = Settings()
    dataset = _load_dataset(args.input)
    if args.month:
        try:
            window = resolve_month(args.month, timezone=settings.report_timezone)
        except InvalidMonthError as exc:
            return _fail(str(exc))
        dataset = dataset.model_copy(update={"month_label": window.month_label})
    report, csv_text = _ranked_report(dataset, settings, args.top)
    if args.dry_run:
        print(report)
        return 0
    try:
        settings.require_discord()
        token = settings.require_bot_token()
    except RuntimeError as exc:
        return _fail(str(exc))
    with DiscordClient(token, base_url=settings.discord_api_base_url) as client:
        return _post_report(settings, client, report, csv_text)


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


def _cmd_run(args: argparse.Namespace) -> int:
    settings = Settings()
    try:
        window = resolve_month(args.month, timezone=settings.report_timezone)
        if args.post:
            settings.require_discord()
        token = settings.require_bot_token()
        channels = settings.channels_for_run(allow_partial=args.allow_partial)
    except (InvalidMonthError, RuntimeError) as exc:
        return _fail(str(exc))

    print(
        f"Running {window.month_label} ({window.month_key}) in {window.timezone}"
        + ("" if window.is_complete() else " - month still in progress")
    )
    with DiscordClient(token, base_url=settings.discord_api_base_url) as client:
        try:
            capture = capture_channels(
                client,
                channels=channels,
                window=window,
                output_dir=args.raw_output,
                sanitize=False,
                allow_partial=args.allow_partial,
            )
            result = normalize_capture(args.raw_output, args.normalized_output, window=window)
        except (ChannelCaptureError, DiscordError, NormalizeError) as exc:
            return _fail(str(exc))
        for channel in capture.channels:
            print(f"  {channel.name}: {channel.message_count} messages -> {channel.path}")
        for failure in capture.failures:
            print(f"  {failure.name}: not captured ({failure.reason})", file=sys.stderr)
        print(f"  {result.player_count} players -> {result.dataset_path}")
        dataset = result.dataset.model_copy(update={"month_label": window.month_label})
        report, csv_text = _ranked_report(dataset, settings, args.top)
        _write_rendered_report(args.report_output, report, csv_text)
        blockers = posting_blockers(
            [channel.name for channel in capture.channels],
            {failure.name: failure.reason for failure in capture.failures},
        )
        if blockers and not args.allow_partial:
            return _fail(
                "Refusing to post an incomplete report. "
                + " ".join(blockers)
                + " Pass --allow-partial to post anyway."
            )
        if blockers:
            print(
                "warning: posting a partial report. " + " ".join(blockers),
                file=sys.stderr,
            )
        if not args.post:
            print(report)
            return 0
        return _post_report(settings, client, report, csv_text)


def _write_rendered_report(output_dir: Path, report: str, csv_text: str) -> None:
    """Persist the rendered report so a failed post still leaves an artifact."""
    output_dir.mkdir(parents=True, exist_ok=True)
    text = report if report.endswith("\n") else f"{report}\n"
    (output_dir / "report.md").write_text(text, encoding="utf-8")
    (output_dir / "report.csv").write_text(csv_text, encoding="utf-8")


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
    mode = report.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the report. Does not contact Discord.",
    )
    mode.add_argument(
        "--post",
        action="store_true",
        help="Post the report and a CSV attachment to DISCORD_REPORT_CHANNEL_ID.",
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
            "Parse #members from a fetch directory into a MonthlyDataset. "
            "Members-only: war/CWL/games/capital/donation fields stay missing."
        ),
    )
    normalize.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_RAW_OUTPUT,
        help=f"Fetch output directory containing members.json (default: {DEFAULT_RAW_OUTPUT}).",
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

    run = subparsers.add_parser(
        "run",
        help="Fetch, normalize, and render one month. Pass --post to deliver it.",
    )
    run.add_argument(
        "--month",
        default="previous",
        help="Reporting month: YYYY-MM, 'previous', or 'current'. Defaults to previous.",
    )
    run.add_argument(
        "--raw-output",
        type=Path,
        default=DEFAULT_RAW_OUTPUT,
        help=f"Directory for raw channel JSON (default: {DEFAULT_RAW_OUTPUT}).",
    )
    run.add_argument(
        "--normalized-output",
        type=Path,
        default=DEFAULT_NORMALIZED_OUTPUT,
        help=(f"Directory for the normalized dataset (default: {DEFAULT_NORMALIZED_OUTPUT})."),
    )
    run.add_argument(
        "--report-output",
        type=Path,
        default=DEFAULT_REPORT_OUTPUT,
        help=f"Directory for report.md and report.csv (default: {DEFAULT_REPORT_OUTPUT}).",
    )
    run.add_argument("--top", type=int, default=5, help="Number of top performers to show.")
    run.add_argument(
        "--post",
        action="store_true",
        help=(
            "Post the report and a CSV attachment. Without this flag the report is "
            "printed and nothing is posted."
        ),
    )
    run.add_argument(
        "--allow-partial",
        action="store_true",
        help=(
            "Post even when a required channel is missing or inaccessible. "
            "Off by default: an incomplete report is not posted."
        ),
    )
    run.set_defaults(func=_cmd_run)

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
