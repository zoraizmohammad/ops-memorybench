"""Per app sandbox APIs.

Each integration exposes a small tool surface tuned to the operations the benchmark
uses, backed by the seeded :class:`~ombench.replay.sandbox.Sandbox`. The functions
here build the :class:`ToolSpec` list the agent sees and a tool executor that routes
each call to the right read or write against the sandbox. Reads resolve seeded state;
writes record a :class:`WriteAction` and return a fake ok response with app refs so
the trajectory links to the entities the agent touched.

The surface is deliberately small and semantic rather than a full SaaS API: get and
update a calendar event, post a Slack message, route to a channel, create and read a
document. That is enough to run the fifteen benchmark tasks while keeping the sandbox
honest and deterministic.
"""

from __future__ import annotations

from typing import Any

from ..llm.base import ToolSpec
from ..traces.schema import AppRef
from .sandbox import Sandbox

# -- tool specifications --------------------------------------------------

SLACK_TOOLS = [
    ToolSpec(
        name="slack.list_channels",
        description="List the Slack channels available in the workspace.",
        input_schema={"type": "object", "properties": {}},
    ),
    ToolSpec(
        name="slack.post_message",
        description="Post a message to a Slack channel by name or id.",
        input_schema={
            "type": "object",
            "properties": {
                "channel": {"type": "string", "description": "Channel name or id"},
                "text": {"type": "string"},
            },
            "required": ["channel", "text"],
        },
    ),
    ToolSpec(
        name="slack.send_dm",
        description="Send a direct message to a single user instead of posting publicly.",
        input_schema={
            "type": "object",
            "properties": {
                "user": {"type": "string"},
                "text": {"type": "string"},
            },
            "required": ["user", "text"],
        },
    ),
]

GCAL_TOOLS = [
    ToolSpec(
        name="gcal.get_event",
        description="Get a calendar event by id.",
        input_schema={
            "type": "object",
            "properties": {"event_id": {"type": "string"}},
            "required": ["event_id"],
        },
    ),
    ToolSpec(
        name="gcal.update_event",
        description="Update a calendar event, for example its start time.",
        input_schema={
            "type": "object",
            "properties": {
                "event_id": {"type": "string"},
                "start": {"type": "string", "description": "New start time"},
            },
            "required": ["event_id"],
        },
    ),
    ToolSpec(
        name="gcal.create_event",
        description="Create a calendar event with a summary, start, and attendees.",
        input_schema={
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "start": {"type": "string"},
                "attendees": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["summary"],
        },
    ),
    ToolSpec(
        name="gcal.respond_event",
        description="Respond to a calendar invitation, accept or decline.",
        input_schema={
            "type": "object",
            "properties": {
                "event_id": {"type": "string"},
                "response": {"type": "string", "enum": ["accepted", "declined", "tentative"]},
            },
            "required": ["event_id", "response"],
        },
    ),
]

GDOCS_TOOLS = [
    ToolSpec(
        name="gdocs.create_document",
        description="Create a Google Doc with a given name and optional body.",
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["name"],
        },
    ),
    ToolSpec(
        name="gdocs.get_document",
        description="Read a Google Doc by id.",
        input_schema={
            "type": "object",
            "properties": {"document_id": {"type": "string"}},
            "required": ["document_id"],
        },
    ),
    ToolSpec(
        name="gdocs.update_document",
        description="Update the body of an existing Google Doc by id.",
        input_schema={
            "type": "object",
            "properties": {
                "document_id": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["document_id"],
        },
    ),
]

ALL_TOOLS = SLACK_TOOLS + GCAL_TOOLS + GDOCS_TOOLS


class SandboxToolRouter:
    """Routes agent tool calls to reads and writes against a sandbox."""

    def __init__(self, sandbox: Sandbox) -> None:
        self.sandbox = sandbox

    def tools(self) -> list[ToolSpec]:
        return list(ALL_TOOLS)

    def execute(self, name: str, args: dict[str, Any]) -> tuple[Any, list[AppRef]]:
        """Execute one tool call. Returns the result payload and touched app refs."""
        handler = getattr(self, f"_{name.replace('.', '_')}", None)
        if handler is None:
            return {"error": f"unknown tool {name}"}, []
        return handler(args)

    # -- slack ------------------------------------------------------------

    def _slack_list_channels(self, args: dict[str, Any]):
        channels = self.sandbox.entities("slack", "channel")
        names = [c["payload"].get("name") for c in channels]
        refs = [
            AppRef(app="slack", entity_type="channel", entity_id=c["payload"]["id"], role="read")
            for c in channels
            if c["payload"].get("id")
        ]
        return {"channels": names}, refs

    def _slack_post_message(self, args: dict[str, Any]):
        channel = args.get("channel", "")
        target = self._resolve_channel(channel)
        # Record the channel the agent named (its intent) plus the resolved id, so
        # validation reflects the decision the agent made rather than the lookup.
        result = self.sandbox.apply_write(
            "slack",
            "post_message",
            {"channel": channel, "channel_id": target, "text": args.get("text", "")},
        ).result
        refs = [AppRef(app="slack", entity_type="channel", entity_id=target, role="write")]
        return result, refs

    def _resolve_channel(self, channel: str) -> str:
        """Map a channel name to its id when possible, else pass through."""
        for c in self.sandbox.entities("slack", "channel"):
            payload = c["payload"]
            if payload.get("name") == channel or payload.get("id") == channel:
                return payload.get("id", channel)
        return channel

    def _slack_send_dm(self, args: dict[str, Any]):
        user = args.get("user", "")
        result = self.sandbox.apply_write(
            "slack", "send_dm", {"user": user, "text": args.get("text", "")}
        ).result
        refs = [AppRef(app="slack", entity_type="user", entity_id=user, role="write")]
        return result, refs

    # -- calendar ---------------------------------------------------------

    def _gcal_get_event(self, args: dict[str, Any]):
        eid = args.get("event_id", "")
        entity = self.sandbox.get_entity("gcal", "event", eid)
        refs = [AppRef(app="gcal", entity_type="event", entity_id=eid, role="read")]
        return (entity["payload"] if entity else {"error": "not found"}), refs

    def _gcal_update_event(self, args: dict[str, Any]):
        eid = args.get("event_id", "")
        result = self.sandbox.apply_write("gcal", "update_event", dict(args)).result
        refs = [AppRef(app="gcal", entity_type="event", entity_id=eid, role="write")]
        return result, refs

    def _gcal_create_event(self, args: dict[str, Any]):
        result = self.sandbox.apply_write("gcal", "create_event", dict(args)).result
        refs = [AppRef(app="gcal", entity_type="event", entity_id=args.get("summary", "new"), role="write")]
        return result, refs

    def _gcal_respond_event(self, args: dict[str, Any]):
        eid = args.get("event_id", "")
        result = self.sandbox.apply_write("gcal", "respond_event", dict(args)).result
        refs = [AppRef(app="gcal", entity_type="event", entity_id=eid, role="write")]
        return result, refs

    # -- docs -------------------------------------------------------------

    def _gdocs_create_document(self, args: dict[str, Any]):
        name = args.get("name", "")
        payload = {"name": name}
        if "body" in args:
            payload["body"] = args["body"]
        result = self.sandbox.apply_write("gdocs", "create_document", payload).result
        refs = [AppRef(app="gdocs", entity_type="document", entity_id=name, role="write")]
        return result, refs

    def _gdocs_update_document(self, args: dict[str, Any]):
        did = args.get("document_id", "")
        result = self.sandbox.apply_write("gdocs", "update_document", dict(args)).result
        refs = [AppRef(app="gdocs", entity_type="document", entity_id=did, role="write")]
        return result, refs

    def _gdocs_get_document(self, args: dict[str, Any]):
        did = args.get("document_id", "")
        entity = self.sandbox.get_entity("gdocs", "document", did)
        refs = [AppRef(app="gdocs", entity_type="document", entity_id=did, role="read")]
        return (entity["payload"] if entity else {"error": "not found"}), refs
