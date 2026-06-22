# Gmail integration design (future path)

Gmail is not part of the proof of concept, but it fits the bitemporal substrate
without any change to the core. This document records how it would be built so the
integration is a small, well understood addition rather than a redesign.

## Acquisition model

Gmail provides partial synchronization keyed by a monotonic `historyId`:

1. **Full sync (once).** List the mailbox (or a label scoped subset), fetch each
   message with `users.messages.get`, and record the largest `historyId` seen.
2. **Incremental sync.** Call `users.history.list` with `startHistoryId` set to the
   stored value. The response is a list of history records describing
   `messagesAdded`, `messagesDeleted`, `labelsAdded`, and `labelsRemoved` since
   then. Advance the stored `historyId` to the response's `historyId`.
3. **Expiry reset.** If the stored `historyId` is older than the server retains, the
   API returns an error indicating the id is too old. The handler clears the cursor
   and performs a full sync, exactly analogous to the Calendar `410 GONE` reset that
   `GCalSync` already implements.

The stored `historyId` lives in `sync_cursors` under `(app='gmail', stream='mailbox')`,
the same mechanism every other integration uses.

## Event mapping

| Gmail concept | Canonical op | Entity |
|---|---|---|
| Thread | `upsert_entity` | `thread` |
| Message | `upsert_entity` | `message`, parented to its thread |
| Message added | `upsert_entity` | `message` |
| Message deleted | `delete_entity` | `message` |
| Label added or removed | `status_change` | `message` with the label delta in the payload |

`valid_at` is the message internal date (when it took effect in the mailbox).
`ingested_at` is the sync time. This is identical to the pattern used for Slack
messages and Calendar events, so time travel and snapshotting work unchanged.

## Privacy

Email bodies are sensitive. Capture would store only headers, snippets, and label
state by default, with full body capture behind an explicit opt in. The existing
redaction pass applies to all stored payloads, and ACL tagging would mark Gmail
memory as personal namespace by default.

## Why it is left as a stub

The proof of concept already demonstrates messaging (Slack), calendar (Calendar),
and documents (Docs), which cover the three structurally distinct acquisition models
(event stream, sync token, and self owned content snapshots). Gmail's `historyId`
model is a variant of the sync token model already implemented for Calendar, so it
adds breadth without exercising a new class of problem. The adapter scaffold in
`ombench.integrations.gmail.sync` implements the event mapping against a fixture so
the design is concrete and testable.
