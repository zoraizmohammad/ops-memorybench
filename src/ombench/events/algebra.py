"""Constructors for the canonical event algebra.

Integration normalizers should build events through these helpers rather than
instantiating :class:`AppEvent` directly. The helpers enforce the right ``op`` for
each kind of change and keep the call sites readable, which matters because every
integration funnels through this same vocabulary.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .schema import App, AppEvent, Op


def upsert_entity(
    *,
    app: App | str,
    entity_type: str,
    entity_id: str,
    payload: dict[str, Any],
    valid_at: datetime,
    ingested_at: datetime,
    actor_ref: str | None = None,
    parent_entity_ref: str | None = None,
    source_cursor: str | None = None,
    provenance: dict[str, Any] | None = None,
) -> AppEvent:
    """Create or update an entity's current state."""
    return AppEvent(
        app=App(app),
        entity_type=entity_type,
        entity_id=entity_id,
        op=Op.UPSERT_ENTITY,
        payload=payload,
        valid_at=valid_at,
        ingested_at=ingested_at,
        actor_ref=actor_ref,
        parent_entity_ref=parent_entity_ref,
        source_cursor=source_cursor,
        provenance=provenance or {},
    )


def delete_entity(
    *,
    app: App | str,
    entity_type: str,
    entity_id: str,
    valid_at: datetime,
    ingested_at: datetime,
    actor_ref: str | None = None,
    source_cursor: str | None = None,
    provenance: dict[str, Any] | None = None,
) -> AppEvent:
    """Mark an entity deleted as of ``valid_at``.

    Deletes are represented as events, never as row removals, because incremental
    sync feeds report deletions and a faithful history must keep them.
    """
    return AppEvent(
        app=App(app),
        entity_type=entity_type,
        entity_id=entity_id,
        op=Op.DELETE_ENTITY,
        payload={},
        valid_at=valid_at,
        ingested_at=ingested_at,
        actor_ref=actor_ref,
        source_cursor=source_cursor,
        provenance=provenance or {},
    )


def append_version(
    *,
    app: App | str,
    entity_type: str,
    entity_id: str,
    payload: dict[str, Any],
    valid_at: datetime,
    ingested_at: datetime,
    actor_ref: str | None = None,
    source_cursor: str | None = None,
    provenance: dict[str, Any] | None = None,
) -> AppEvent:
    """Append a new content version, for example a Docs export snapshot.

    The latest version wins in the fold, but every version is retained in the log
    so historical content is reconstructable.
    """
    return AppEvent(
        app=App(app),
        entity_type=entity_type,
        entity_id=entity_id,
        op=Op.APPEND_VERSION,
        payload=payload,
        valid_at=valid_at,
        ingested_at=ingested_at,
        actor_ref=actor_ref,
        source_cursor=source_cursor,
        provenance=provenance or {},
    )


def upsert_edge(
    *,
    app: App | str,
    entity_type: str,
    entity_id: str,
    edge_kind: str,
    edge_target: str,
    valid_at: datetime,
    ingested_at: datetime,
    payload: dict[str, Any] | None = None,
    actor_ref: str | None = None,
    source_cursor: str | None = None,
    provenance: dict[str, Any] | None = None,
) -> AppEvent:
    """Create or update a relationship such as membership or attendance."""
    return AppEvent(
        app=App(app),
        entity_type=entity_type,
        entity_id=entity_id,
        op=Op.UPSERT_EDGE,
        edge_kind=edge_kind,
        edge_target=edge_target,
        payload=payload or {},
        valid_at=valid_at,
        ingested_at=ingested_at,
        actor_ref=actor_ref,
        source_cursor=source_cursor,
        provenance=provenance or {},
    )


def delete_edge(
    *,
    app: App | str,
    entity_type: str,
    entity_id: str,
    edge_kind: str,
    edge_target: str,
    valid_at: datetime,
    ingested_at: datetime,
    actor_ref: str | None = None,
    source_cursor: str | None = None,
    provenance: dict[str, Any] | None = None,
) -> AppEvent:
    """Remove a relationship as of ``valid_at``."""
    return AppEvent(
        app=App(app),
        entity_type=entity_type,
        entity_id=entity_id,
        op=Op.DELETE_EDGE,
        edge_kind=edge_kind,
        edge_target=edge_target,
        payload={},
        valid_at=valid_at,
        ingested_at=ingested_at,
        actor_ref=actor_ref,
        source_cursor=source_cursor,
        provenance=provenance or {},
    )


def status_change(
    *,
    app: App | str,
    entity_type: str,
    entity_id: str,
    payload: dict[str, Any],
    valid_at: datetime,
    ingested_at: datetime,
    actor_ref: str | None = None,
    source_cursor: str | None = None,
    provenance: dict[str, Any] | None = None,
) -> AppEvent:
    """Record a status transition such as an RSVP or a task state change."""
    return AppEvent(
        app=App(app),
        entity_type=entity_type,
        entity_id=entity_id,
        op=Op.STATUS_CHANGE,
        payload=payload,
        valid_at=valid_at,
        ingested_at=ingested_at,
        actor_ref=actor_ref,
        source_cursor=source_cursor,
        provenance=provenance or {},
    )
