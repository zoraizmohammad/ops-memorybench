"""Long running sync worker.

In production the integrations would run continuously rather than as a one shot CLI
sync. This worker is the entrypoint for that: it loops over the configured
integrations, runs each sync on an interval, and persists cursors so each cycle picks
up only new data. Idempotent appends and deterministic event ids make re running safe.

For the proof of concept this runs against the synthetic fixtures, so a single pass is
a no op after the first. The structure is what matters: it is the seam where a real
deployment plugs in scheduling, backpressure, and rate limit handling.
"""

from __future__ import annotations

import time

from ...config import Config, load_config
from ...integrations.registry import DEFAULT_APPS, build_integration
from ...logging import get_logger
from ...storage import open_store

log = get_logger("worker")


def run_once(config: Config | None = None) -> dict[str, int]:
    """Run one sync cycle over all registered integrations. Returns new events per app.

    Draws the app list from the shared integration registry, so a newly registered
    app is synced by the worker automatically with no change here.
    """
    config = config or load_config()
    store = open_store(config)
    try:
        results: dict[str, int] = {}
        for name in DEFAULT_APPS:
            integ = build_integration(name, store, config)
            result = integ.run_sync()
            results[integ.app.value] = result.events_new
        return results
    finally:
        store.close()


def run_forever(config: Config | None = None, *, interval_seconds: float = 60.0) -> None:  # pragma: no cover
    """Run sync cycles forever on an interval. The production worker loop."""
    config = config or load_config()
    log.info("sync worker starting, interval %ss", interval_seconds)
    while True:
        try:
            results = run_once(config)
            log.info("sync cycle complete, new events %s", results)
        except Exception as exc:
            log.warning("sync cycle failed: %s", exc)
        time.sleep(interval_seconds)


if __name__ == "__main__":  # pragma: no cover
    print(run_once())
