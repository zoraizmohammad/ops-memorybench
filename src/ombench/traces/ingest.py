"""Trajectory ingestion pipeline.

Takes a :class:`~ombench.traces.schema.TraceRun`, redacts its span payloads, offloads
large inputs and outputs to the content addressed blob store, and persists the run,
its spans, and their app references into the relational backend. Ingestion is
idempotent on ``trace_id`` and ``span_id`` so re running capture on the same session
is safe.

The persisted ``span_app_refs`` rows are the index the benchmark miner and memory
compiler use to connect agent behavior to the SaaS entities it touched.
"""

from __future__ import annotations

from ..storage import Store
from ..timeutil import to_iso, utcnow
from .redact import Redactor
from .schema import TraceRun, TraceSpan


class TrajectoryIngestor:
    """Persists trajectories into the store with redaction and blob offloading."""

    def __init__(self, store: Store, redactor: Redactor | None = None) -> None:
        self.store = store
        self.redactor = redactor or Redactor()

    def ingest(self, run: TraceRun) -> str:
        """Ingest one run. Returns its ``trace_id``.

        Idempotent on equal or thinner content, and content aware on richer content:
        if a run already exists for this trace id and the incoming run has more
        spans, it replaces the stored one. This matters because the same session can
        be finalized from two sources, the incremental hook log and the full
        transcript, and the richer transcript should win regardless of which arrives
        first rather than being discarded.
        """
        backend = self.store.backend
        existing = backend.query_one(
            "SELECT trace_id FROM trace_runs WHERE trace_id = ?", (run.trace_id,)
        )
        if existing:
            stored = backend.query_one(
                "SELECT COUNT(*) AS c FROM trace_spans WHERE trace_id = ?", (run.trace_id,)
            )
            stored_spans = int(stored["c"]) if stored else 0
            if len(run.spans) <= stored_spans:
                return run.trace_id
            # The incoming run is richer; remove the thinner stored version first.
            self._delete_run(run.trace_id)

        with backend.transaction():
            # Insert the run row first so the span foreign key is satisfied, then
            # persist spans (which populates each span's redactions list via the
            # offload step), then store the trajectory document built from the
            # updated spans so the reconstructed document reflects redaction, and
            # finally point the run row at that document blob.
            backend.insert(
                "trace_runs",
                {
                    "trace_id": run.trace_id,
                    "group_id": run.group_id,
                    "workflow_name": run.workflow_name,
                    "agent": run.agent,
                    "started_at": to_iso(run.started_at) if run.started_at else None,
                    "ended_at": to_iso(run.ended_at) if run.ended_at else None,
                    "user_ref": run.user_ref,
                    "task_ref": run.task_ref,
                    "status": run.status.value,
                    "payload_hash": None,
                    "ingested_at": to_iso(utcnow()),
                },
            )
            for span in run.spans:
                self._persist_span(run.trace_id, span)
            redacted_doc, _ = self.redactor.redact(run.model_dump(mode="json"))
            payload_hash = self.store.blobs.put_json(redacted_doc)
            backend.execute(
                "UPDATE trace_runs SET payload_hash = ? WHERE trace_id = ?",
                (payload_hash, run.trace_id),
            )
        return run.trace_id

    def _delete_run(self, trace_id: str) -> None:
        """Remove a stored run and its spans so a richer version can replace it.

        Blobs are left in the content addressed store; they are immutable and
        deduplicated, so orphaned blobs are harmless and a future garbage collection
        sweep can reclaim them.
        """
        backend = self.store.backend
        with backend.transaction():
            span_rows = backend.query(
                "SELECT span_id FROM trace_spans WHERE trace_id = ?", (trace_id,)
            )
            for row in span_rows:
                backend.execute(
                    "DELETE FROM span_app_refs WHERE span_id = ?", (row["span_id"],)
                )
            backend.execute("DELETE FROM trace_spans WHERE trace_id = ?", (trace_id,))
            backend.execute("DELETE FROM trace_runs WHERE trace_id = ?", (trace_id,))

    def _persist_span(self, trace_id: str, span: TraceSpan) -> None:
        backend = self.store.backend
        if backend.query_one(
            "SELECT span_id FROM trace_spans WHERE span_id = ?", (span.span_id,)
        ):
            return

        redaction_hits: set[str] = set(span.redactions)
        if span.input is not None:
            input_ref, hits = self._offload(span.input)
            redaction_hits |= hits
        else:
            input_ref = span.input_ref
        if span.output is not None:
            output_ref, hits = self._offload(span.output)
            redaction_hits |= hits
        else:
            output_ref = span.output_ref
        # Record what redaction removed on the span so the privacy posture of the
        # stored span is auditable, which is the whole point of capturing it.
        object.__setattr__(span, "redactions", sorted(redaction_hits))
        attributes_hash = (
            self.store.blobs.put_json(span.attributes) if span.attributes else None
        )

        backend.insert(
            "trace_spans",
            {
                "span_id": span.span_id,
                "trace_id": trace_id,
                "parent_id": span.parent_id,
                "kind": span.kind.value,
                "name": span.name,
                "started_at": to_iso(span.started_at) if span.started_at else None,
                "ended_at": to_iso(span.ended_at) if span.ended_at else None,
                "status": span.status.value,
                "input_ref": input_ref,
                "output_ref": output_ref,
                "tool_name": span.tool_name,
                "attributes_hash": attributes_hash,
                "tokens": span.tokens,
                "cost_usd": span.cost_usd,
            },
        )
        for ref in span.app_refs:
            backend.insert(
                "span_app_refs",
                {
                    "span_id": span.span_id,
                    "app": ref.app,
                    "entity_type": ref.entity_type,
                    "entity_id": ref.entity_id,
                },
            )

    def _offload(self, value: object) -> tuple[str, set[str]]:
        """Redact then store a span payload, returning its blob reference and hits.

        Every payload is content addressed so identical inputs across spans
        deduplicate to one blob. Redaction happens here so nothing sensitive ever
        reaches the blob store unscrubbed, and the set of rule names that fired is
        returned so the caller can record it on the span.
        """
        redacted, hits = self.redactor.redact(value)
        return self.store.blobs.put_json(redacted), hits

    # -- read back --------------------------------------------------------

    def load(self, trace_id: str) -> TraceRun | None:
        """Reconstruct a run from its stored trajectory document blob."""
        row = self.store.backend.query_one(
            "SELECT payload_hash FROM trace_runs WHERE trace_id = ?", (trace_id,)
        )
        if not row or not row["payload_hash"]:
            return None
        doc = self.store.blobs.get_json(row["payload_hash"])
        return TraceRun.model_validate(doc)

    def list_runs(self, *, agent: str | None = None) -> list[dict]:
        """List stored runs as rows, most recent first."""
        if agent:
            return self.store.backend.query(
                "SELECT * FROM trace_runs WHERE agent = ? ORDER BY ingested_at DESC",
                (agent,),
            )
        return self.store.backend.query(
            "SELECT * FROM trace_runs ORDER BY ingested_at DESC"
        )

    def spans_touching(self, app: str, entity_type: str, entity_id: str) -> list[dict]:
        """Return span rows that reference a given SaaS entity.

        This is the trajectory side of the join between agent behavior and app
        state, used by the benchmark miner.
        """
        return self.store.backend.query(
            "SELECT s.* FROM trace_spans s "
            "JOIN span_app_refs r ON r.span_id = s.span_id "
            "WHERE r.app = ? AND r.entity_type = ? AND r.entity_id = ?",
            (app, entity_type, entity_id),
        )
