from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest

from clash_reporter import main as cli
from clash_reporter.config import DATA_CHANNELS
from clash_reporter.discord_client import DiscordClient

SAMPLE_DATASET = Path(__file__).parent / "fixtures" / "normalized" / "monthly_players.sample.json"
TOKEN = "not-a-real-token-abc123"  # noqa: S105 - dummy value for mocked transports

MEMBERS_CHANNEL = "400000000000000001"
WARS_CHANNEL = "400000000000000002"


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for variable in (
        "DISCORD_API_BASE_URL",
        "DISCORD_BOT_TOKEN",
        "DISCORD_GUILD_ID",
        "DISCORD_REPORT_CHANNEL_ID",
        "REPORT_TIMEZONE",
        *(f"DISCORD_{name.replace('-', '_').upper()}_CHANNEL_ID" for name in DATA_CHANNELS),
    ):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.chdir(Path(__file__).parent)  # keep a stray .env out of the way


@dataclass
class DiscordStub:
    """What the CLI asked for, recorded behind a mocked transport."""

    requests: list[httpx.Request]
    client_kwargs: list[dict[str, Any]]


@pytest.fixture
def discord_stub(
    monkeypatch: pytest.MonkeyPatch,
    clashperk_message: Callable[[str], dict[str, Any]],
) -> Iterator[DiscordStub]:
    """Install a mocked transport serving real ClashPerk history to the CLI's client."""
    stub = DiscordStub(requests=[], client_kwargs=[])
    # cp-members answers with one page of history, then runs out.
    responses: dict[str, httpx.Response] = {
        MEMBERS_CHANNEL: httpx.Response(
            200,
            json=[
                clashperk_message("members/leave.json"),  # 2026-08-19
                clashperk_message("members/join.json"),  # 2026-08-03
            ],
        )
    }

    def handler(request: httpx.Request) -> httpx.Response:
        stub.requests.append(request)
        channel_id = request.url.path.split("/")[-2]
        response = responses.pop(channel_id, None)
        return response if response is not None else httpx.Response(200, json=[])

    def build(token: str, **kwargs: Any) -> DiscordClient:
        assert token == TOKEN
        stub.client_kwargs.append(kwargs)
        return DiscordClient(
            token,
            transport=httpx.MockTransport(handler),
            sleep=lambda seconds: None,
            **kwargs,
        )

    monkeypatch.setattr(cli, "DiscordClient", build)
    yield stub


def test_report_still_renders_without_a_month(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["report", "--input", str(SAMPLE_DATASET), "--dry-run"]) == 0
    assert "August 2026" in capsys.readouterr().out


def test_report_month_relabels_the_output(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = cli.main(
        ["report", "--input", str(SAMPLE_DATASET), "--month", "2026-11", "--dry-run"]
    )
    assert exit_code == 0
    output = capsys.readouterr().out
    assert "November 2026" in output
    assert "August 2026" not in output


def test_report_rejects_an_invalid_month(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = cli.main(
        ["report", "--input", str(SAMPLE_DATASET), "--month", "2026-13", "--dry-run"]
    )
    assert exit_code == 2
    assert "Invalid month" in capsys.readouterr().err


def test_fetch_writes_channel_files_and_a_manifest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    discord_stub: DiscordStub,
) -> None:
    monkeypatch.setenv("DISCORD_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("DISCORD_CP_MEMBERS_CHANNEL_ID", MEMBERS_CHANNEL)

    exit_code = cli.main(
        ["fetch", "--month", "2026-08", "--output", str(tmp_path), "--channel", "cp-members"]
    )

    assert exit_code == 0
    written = json.loads((tmp_path / "cp-members.json").read_text(encoding="utf-8"))
    assert [message["timestamp"] for message in written] == [
        "2026-08-03T18:12:44.281000+00:00",
        "2026-08-19T02:41:09.553000+00:00",
    ]
    assert written[0]["embeds"][0]["title"] == "\u200eAurora (#2Y0LRPV8Q)"
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["window"]["month_key"] == "2026-08"
    assert manifest["channels"][0]["message_count"] == 2
    out = capsys.readouterr().out
    assert "cp-members: 2 messages" in out
    assert "Manifest:" in out


def test_fetch_uses_the_configured_api_base_url(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    discord_stub: DiscordStub,
) -> None:
    monkeypatch.setenv("DISCORD_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("DISCORD_CP_MEMBERS_CHANNEL_ID", MEMBERS_CHANNEL)
    monkeypatch.setenv("DISCORD_API_BASE_URL", "http://127.0.0.1:8787/api")

    assert cli.main(["fetch", "--month", "2026-08", "--output", str(tmp_path)]) == 0
    assert discord_stub.client_kwargs == [{"base_url": "http://127.0.0.1:8787/api"}]
    assert str(discord_stub.requests[0].url).startswith("http://127.0.0.1:8787/api/v10/channels/")


def test_fetch_defaults_to_the_public_discord_api(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    discord_stub: DiscordStub,
) -> None:
    monkeypatch.setenv("DISCORD_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("DISCORD_CP_MEMBERS_CHANNEL_ID", MEMBERS_CHANNEL)

    assert cli.main(["fetch", "--month", "2026-08", "--output", str(tmp_path)]) == 0
    assert discord_stub.client_kwargs == [{"base_url": "https://discord.com/api"}]


def test_fetch_current_month_reports_a_partial_capture(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    discord_stub: DiscordStub,
) -> None:
    monkeypatch.setenv("DISCORD_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("DISCORD_CP_MEMBERS_CHANNEL_ID", MEMBERS_CHANNEL)

    exit_code = cli.main(["fetch", "--month", "current", "--output", str(tmp_path)])

    assert exit_code == 0
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["window"]["complete"] is False
    assert "capture is partial" in capsys.readouterr().out


def test_fetch_captures_every_configured_channel_by_default(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    discord_stub: DiscordStub,
) -> None:
    monkeypatch.setenv("DISCORD_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("DISCORD_CP_MEMBERS_CHANNEL_ID", MEMBERS_CHANNEL)
    monkeypatch.setenv("DISCORD_CP_WARS_CHANNEL_ID", WARS_CHANNEL)

    assert cli.main(["fetch", "--month", "2026-08", "--output", str(tmp_path)]) == 0
    assert (tmp_path / "cp-members.json").exists()
    assert (tmp_path / "cp-wars.json").exists()
    assert not (tmp_path / "cp-cwl.json").exists()


def test_fetch_without_a_token_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("DISCORD_CP_MEMBERS_CHANNEL_ID", MEMBERS_CHANNEL)
    exit_code = cli.main(["fetch", "--month", "2026-08", "--output", str(tmp_path)])
    assert exit_code == 2
    assert "DISCORD_BOT_TOKEN" in capsys.readouterr().err
    assert not list(tmp_path.iterdir())


def test_fetch_without_channel_configuration_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("DISCORD_BOT_TOKEN", TOKEN)
    exit_code = cli.main(["fetch", "--month", "2026-08", "--output", str(tmp_path)])
    assert exit_code == 2
    assert "No ClashPerk data channels configured" in capsys.readouterr().err


def test_fetch_names_a_requested_channel_that_is_not_configured(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("DISCORD_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("DISCORD_CP_MEMBERS_CHANNEL_ID", MEMBERS_CHANNEL)
    exit_code = cli.main(
        ["fetch", "--month", "2026-08", "--output", str(tmp_path), "--channel", "cp-wars"]
    )
    assert exit_code == 2
    assert "DISCORD_CP_WARS_CHANNEL_ID" in capsys.readouterr().err


def test_fetch_reports_an_unreadable_channel_by_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("DISCORD_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("DISCORD_CP_WARS_CHANNEL_ID", WARS_CHANNEL)

    def build(token: str, **kwargs: Any) -> DiscordClient:
        return DiscordClient(
            token,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(403, json={"message": "Missing Access"})
            ),
            sleep=lambda seconds: None,
            **kwargs,
        )

    monkeypatch.setattr(cli, "DiscordClient", build)
    exit_code = cli.main(["fetch", "--month", "2026-08", "--output", str(tmp_path)])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "cp-wars" in captured.err
    assert TOKEN not in captured.err
    assert not (tmp_path / "cp-wars.json").exists()


def test_fetch_sanitize_flag_pseudonymizes_ids(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    discord_stub: DiscordStub,
) -> None:
    monkeypatch.setenv("DISCORD_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("DISCORD_CP_MEMBERS_CHANNEL_ID", MEMBERS_CHANNEL)

    assert cli.main(["fetch", "--month", "2026-08", "--output", str(tmp_path), "--sanitize"]) == 0
    written = json.loads((tmp_path / "cp-members.json").read_text(encoding="utf-8"))
    assert written[0]["webhook_id"] != "300000000000000001"
    assert written[0]["author"]["id"] == written[0]["webhook_id"]
    assert "#2Y0LRPV8Q" in json.dumps(written)
    assert json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))["sanitized"]


def test_fetch_rejects_an_unknown_channel_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DISCORD_BOT_TOKEN", TOKEN)
    with pytest.raises(SystemExit):
        cli.main(["fetch", "--channel", "cp-nonsense", "--output", str(tmp_path)])


def test_fetch_rejects_an_invalid_month(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("DISCORD_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("DISCORD_CP_MEMBERS_CHANNEL_ID", MEMBERS_CHANNEL)
    exit_code = cli.main(["fetch", "--month", "august", "--output", str(tmp_path)])
    assert exit_code == 2
    assert "Invalid month" in capsys.readouterr().err
