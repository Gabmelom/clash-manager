from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest

from clash_reporter.collection import IdSanitizer

Message = Callable[[str], dict[str, Any]]


@pytest.fixture
def join(clashperk_message: Message) -> dict[str, Any]:
    return clashperk_message("members/join.json")


def test_message_identity_and_timestamps_are_preserved(join: dict[str, Any]) -> None:
    sanitized = IdSanitizer().sanitize(join)
    assert sanitized["id"] == join["id"]
    assert sanitized["timestamp"] == join["timestamp"]
    assert sanitized["edited_timestamp"] is None
    assert sanitized["channel_id"] == join["channel_id"]


def test_player_tags_and_embed_structure_are_untouched(
    clashperk_message: Message,
) -> None:
    sanitizer = IdSanitizer()
    for path in (
        "members/join.json",
        "wars/attack.json",
        "wars/missed-attacks.json",
        "clan-games/final-leaderboard.json",
        "capital/weekly-summary.json",
        "donations/monthly-summary.json",
    ):
        original = clashperk_message(path)
        sanitized = sanitizer.sanitize(original)
        assert sanitized["embeds"] == original["embeds"], path
        assert sanitized["content"] == original["content"], path
        assert sanitized["components"] == original["components"], path


def test_webhook_and_author_ids_are_replaced_together(join: dict[str, Any]) -> None:
    sanitized = IdSanitizer().sanitize(join)
    # ClashPerk posts through a webhook, so author.id is the webhook's snowflake.
    assert sanitized["webhook_id"] != join["webhook_id"]
    assert sanitized["author"]["id"] == sanitized["webhook_id"]
    assert sanitized["author"]["username"] == "ClashPerk"


def test_the_same_source_id_maps_to_the_same_replacement_within_a_run(
    clashperk_message: Message,
) -> None:
    sanitizer = IdSanitizer()
    first, second = sanitizer.sanitize_all(
        [clashperk_message("members/join.json"), clashperk_message("members/leave.json")]
    )
    assert first["author"]["id"] == second["author"]["id"]
    assert first["webhook_id"] == second["webhook_id"]


def test_separate_runs_are_individually_deterministic(clashperk_message: Message) -> None:
    payload = clashperk_message("capital/contribution.json")
    assert IdSanitizer().sanitize_all([payload]) == IdSanitizer().sanitize_all([payload])


def test_sanitize_does_not_mutate_the_input(join: dict[str, Any]) -> None:
    before = json.dumps(join, sort_keys=True)
    IdSanitizer().sanitize(join)
    assert json.dumps(join, sort_keys=True) == before


# The REST message object ClashPerk logs produce carries no guild_id and no mentions.
# A capture can still contain either - a reply carries message_reference.guild_id, and a
# human message can mention a user - so both are covered with explicit payloads.


def test_guild_ids_are_pseudonymized_wherever_they_appear(join: dict[str, Any]) -> None:
    payload = {
        **join,
        "guild_id": "820000000000000001",
        "message_reference": {
            "type": 0,
            "channel_id": join["channel_id"],
            "guild_id": "820000000000000001",
            "message_id": "1000000000000000001",
        },
    }
    sanitized = IdSanitizer().sanitize(payload)

    assert sanitized["guild_id"] != "820000000000000001"
    assert sanitized["message_reference"]["guild_id"] == sanitized["guild_id"]
    assert sanitized["message_reference"]["message_id"] == "1000000000000000001"


def test_user_mentions_are_rewritten_consistently(join: dict[str, Any]) -> None:
    payload = {
        **join,
        "content": "<@850000000000000003> <@!850000000000000003> please review #2Y0LRPV8Q",
        "mentions": [{"id": "850000000000000003", "username": "gabriel"}],
    }
    sanitized = IdSanitizer().sanitize(payload)
    replacement = sanitized["mentions"][0]["id"]

    assert replacement != "850000000000000003"
    assert sanitized["content"] == f"<@{replacement}> <@!{replacement}> please review #2Y0LRPV8Q"


def test_ids_embedded_in_urls_are_rewritten_whole(join: dict[str, Any]) -> None:
    payload = {
        **join,
        "guild_id": "820000000000000001",
        "content": "guild 820000000000000001 and unrelated 8200000000000000012",
        "embeds": [
            {
                "type": "rich",
                "url": f"https://discord.com/channels/820000000000000001/{join['channel_id']}/1",
            }
        ],
    }
    sanitized = IdSanitizer().sanitize(payload)
    guild = sanitized["guild_id"]

    assert sanitized["embeds"][0]["url"] == (
        f"https://discord.com/channels/{guild}/{join['channel_id']}/1"
    )
    assert sanitized["content"] == f"guild {guild} and unrelated 8200000000000000012"


def test_nested_user_objects_are_sanitized(join: dict[str, Any]) -> None:
    payload = {
        **join,
        "referenced_message": {
            "id": "999",
            "author": {"id": join["author"]["id"], "username": "ClashPerk"},
        },
    }
    sanitized = IdSanitizer().sanitize(payload)

    assert sanitized["referenced_message"]["id"] == "999"
    assert sanitized["referenced_message"]["author"]["id"] == sanitized["author"]["id"]
