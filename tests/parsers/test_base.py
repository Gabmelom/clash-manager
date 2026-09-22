from __future__ import annotations

import ast
from pathlib import Path

from clash_reporter.events import MemberJoined, SourceMetadata
from clash_reporter.parsers.base import (
    extract_player_tag,
    is_valid_player_tag,
    make_event_key,
    normalize_player_tag,
    parse_player_title,
)
from clash_reporter.window import parse_iso_timestamp

PARSERS_ROOT = Path("src/clash_reporter/parsers")


def test_normalize_player_tag_matches_clashofclans_js_format_tag() -> None:
    # clashofclans.js Util.formatTag("PccVqqGO") → "#PCCVQQG0"
    assert normalize_player_tag("PccVqqGO") == "#PCCVQQG0"
    assert normalize_player_tag("#2y0lrpv8q") == "#2Y0LRPV8Q"
    assert normalize_player_tag("2Y0LRPV8Q") == "#2Y0LRPV8Q"
    assert normalize_player_tag("#2Y0LRPV8Q") == "#2Y0LRPV8Q"


def test_letter_o_becomes_zero() -> None:
    assert normalize_player_tag("#2YOLRPV8Q") == "#2Y0LRPV8Q"
    assert normalize_player_tag("pccvqqgo") == "#PCCVQQG0"


def test_spaces_are_stripped() -> None:
    assert normalize_player_tag("#2Y0 LRPV 8Q") == "#2Y0LRPV8Q"


def test_is_valid_player_tag_rejects_non_alphabet() -> None:
    assert is_valid_player_tag("#2Y0LRPV8Q")
    assert not is_valid_player_tag("#")
    assert not is_valid_player_tag("AB")
    assert not is_valid_player_tag("#PLAYER")


def test_parse_player_title_strips_lrm_and_extracts_tag() -> None:
    name, tag = parse_player_title("\u200eAurora (#2Y0LRPV8Q)")
    assert name == "Aurora"
    assert tag == "#2Y0LRPV8Q"
    assert extract_player_tag("\u200eBorealis (#8QCU29VJ0)") == "#8QCU29VJ0"


def test_parse_player_title_normalizes_letter_o_in_tag() -> None:
    name, tag = parse_player_title("\u200eAurora (#PccVqqGO)")
    assert name == "Aurora"
    assert tag == "#PCCVQQG0"


def test_parse_player_title_name_without_tag() -> None:
    name, tag = parse_player_title("\u200eAurora")
    assert name == "Aurora"
    assert tag is None
    assert extract_player_tag("Aurora") is None


def test_make_event_key_shape() -> None:
    assert make_event_key("123", "MemberJoined", "#2Y0LRPV8Q") == "123:MemberJoined:#2Y0LRPV8Q:0"
    assert make_event_key("123", "MemberJoined", "#2Y0LRPV8Q", 2) == "123:MemberJoined:#2Y0LRPV8Q:2"


def test_event_key_matches_helper() -> None:
    source = SourceMetadata(
        channel_id="400000000000000001",
        message_id="1533900443745917698",
        message_timestamp=parse_iso_timestamp("2026-08-03T18:12:44.281000+00:00"),
        message_edited_timestamp=None,
        parser_name="members",
        parser_version="1",
    )
    event = MemberJoined(
        player_tag="#2Y0LRPV8Q",
        player_name="Aurora",
        occurred_at=source.message_timestamp,
        source=source,
    )
    assert event.event_key == make_event_key(source.message_id, event.event_type, event.player_tag)


def test_parser_modules_are_pure() -> None:
    forbidden_modules = {"httpx", "requests", "urllib", "pathlib", "os", "socket"}
    for path in PARSERS_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        assert not imported & forbidden_modules, f"{path} imports {imported & forbidden_modules}"
        source = path.read_text(encoding="utf-8")
        assert "datetime.now" not in source
        assert "datetime.utcnow" not in source
        assert "time.time" not in source
