---
title: "Discord REST client: authenticated history pagination and rate limiting"
labels: [phase-1, "area:discord", agent-ready]
---

## Context

This is the blocking dependency for the entire project. Parsers must be written against real
ClashPerk payloads rather than screenshots, and no payload can be captured until something
can read channel history. `docs/CODING_AGENT_BRIEF.md` names this as the first pull request
target.

`GET /channels/{channel.id}/messages` returns at most 100 messages per call, so a month of a
busy war log needs backwards pagination, and Discord will rate limit a naive loop.

## Scope

New module `src/clash_reporter/discord_client.py`:

- `DiscordClient` wrapping `httpx.Client` with the `Bot <token>` authorization header, a
  descriptive user agent, and a configurable base URL and API version.
- `get_channel_messages(channel_id, *, before=None, after=None, limit=100)` returning raw
  message dicts, unmodified.
- `iter_channel_history(channel_id, *, until)` generating messages newest-first, paginating
  with `before`, and stopping once it crosses `until`.
- Centralized rate-limit handling: honor `Retry-After` and `X-RateLimit-Reset-After` on 429,
  bounded retries with backoff on 5xx, and a clear typed error for 401/403/404 so a missing
  channel permission fails loudly.
- An injectable sleep function so tests do not actually wait.

New module `src/clash_reporter/collection/fetch_messages.py`:

- `collect_channel(client, channel_id, window) -> list[dict]` returning every message inside
  a `ReportingWindow`, de-duplicated by message ID.

## Out of scope

- Posting messages and uploading attachments (separate issue).
- Any ClashPerk semantics. This layer must not know what a war log looks like.
- Discord Gateway. V1 never opens a websocket.

## Acceptance criteria

- [ ] Pagination is driven by `httpx.MockTransport`, with no live API calls in tests.
- [ ] A three-page history is walked correctly and stops at the window boundary instead of
      draining the channel.
- [ ] A 429 response with `Retry-After` is retried once and then succeeds, and the injected
      sleep is asserted to have been called with the header value.
- [ ] Repeated messages across page boundaries are de-duplicated by message ID.
- [ ] 401/403/404 raise distinct, typed errors; the token never appears in an error message,
      a log line, or a repr. Add a test that asserts the token string is absent from the
      exception text.
- [ ] The client knows nothing about channel names or ClashPerk message shapes.

## Dependencies

None that block starting. The collector helper needs the reporting window type, so land that
issue first or fold it into the same pull request.

## References

- `docs/ARCHITECTURE.md` - "Discord client"
- `docs/DEVELOPMENT.md` - "Discord pagination", "Rate limits"
- `docs/CODING_AGENT_BRIEF.md` - step 2
- https://docs.discord.com/developers/resources/message#get-channel-messages
