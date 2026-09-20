from __future__ import annotations

from typing import Any

from clash_reporter.collection import IdSanitizer


def message(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": "123456789012345678",
        "channel_id": "222",
        "guild_id": "900",
        "timestamp": "2026-08-20T18:00:00+00:00",
        "edited_timestamp": None,
        "webhook_id": "600",
        "author": {"id": "700", "username": "ClashPerk", "discriminator": "0", "bot": True},
        "content": "Aurora (#R22YRC0UY) reached 3 stars",
        "embeds": [],
        "mentions": [],
    }
    payload.update(overrides)
    return payload


def test_message_identity_and_timestamps_are_preserved() -> None:
    sanitized = IdSanitizer().sanitize(message())
    assert sanitized["id"] == "123456789012345678"
    assert sanitized["timestamp"] == "2026-08-20T18:00:00+00:00"
    assert sanitized["edited_timestamp"] is None
    assert sanitized["channel_id"] == "222"


def test_player_tags_and_embed_structure_are_untouched() -> None:
    embeds = [
        {
            "title": "War Ended",
            "fields": [
                {"name": "Aurora (#R22YRC0UY)", "value": "2 attacks", "inline": True},
                {"name": "Borealis (#9LP0YQ8G)", "value": "1 attack", "inline": True},
            ],
            "footer": {"text": "ClashPerk"},
        }
    ]
    sanitized = IdSanitizer().sanitize(message(embeds=embeds))
    assert sanitized["embeds"] == embeds
    assert sanitized["content"] == "Aurora (#R22YRC0UY) reached 3 stars"


def test_guild_user_and_webhook_ids_are_replaced() -> None:
    sanitized = IdSanitizer().sanitize(message())
    assert sanitized["guild_id"] != "900"
    assert sanitized["author"]["id"] != "700"
    assert sanitized["webhook_id"] != "600"
    assert sanitized["author"]["username"] == "ClashPerk"


def test_the_same_source_id_maps_to_the_same_replacement_within_a_run() -> None:
    sanitizer = IdSanitizer()
    first, second = sanitizer.sanitize_all(
        [
            message(id="1", mentions=[{"id": "800", "username": "gabriel"}], content="<@800> hi"),
            message(id="2", mentions=[{"id": "800", "username": "gabriel"}], content="<@!800> yo"),
        ]
    )
    replacement = first["mentions"][0]["id"]
    assert second["mentions"][0]["id"] == replacement
    assert first["content"] == f"<@{replacement}> hi"
    # The legacy nickname-mention form keeps its shape; only the ID changes.
    assert second["content"] == f"<@!{replacement}> yo"
    assert first["author"]["id"] == second["author"]["id"]


def test_separate_runs_do_not_share_a_mapping_but_are_individually_deterministic() -> None:
    payload = message()
    first = IdSanitizer().sanitize_all([payload])
    second = IdSanitizer().sanitize_all([payload])
    assert first == second


def test_ids_embedded_in_urls_are_rewritten_whole() -> None:
    sanitized = IdSanitizer().sanitize(
        message(
            embeds=[{"url": "https://discord.com/channels/900/222/123456789012345678"}],
            content="guild 900 and unrelated 9001",
        )
    )
    guild = sanitized["guild_id"]
    assert sanitized["embeds"][0]["url"] == (
        f"https://discord.com/channels/{guild}/222/123456789012345678"
    )
    assert sanitized["content"] == f"guild {guild} and unrelated 9001"


def test_sanitize_does_not_mutate_the_input() -> None:
    payload = message()
    IdSanitizer().sanitize(payload)
    assert payload["guild_id"] == "900"
    assert payload["author"]["id"] == "700"


def test_nested_referenced_messages_are_sanitized() -> None:
    sanitizer = IdSanitizer()
    sanitized = sanitizer.sanitize(
        message(referenced_message={"id": "999", "author": {"id": "700", "username": "ClashPerk"}})
    )
    assert sanitized["referenced_message"]["id"] == "999"
    assert sanitized["referenced_message"]["author"]["id"] == sanitized["author"]["id"]
