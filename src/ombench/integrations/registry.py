"""Integration registry.

A single source of truth for the apps the platform knows how to sync. Adding a new
app is a drop in: implement an :class:`~ombench.integrations.base.Integration`
subclass, add one row here with its fixture path, and it is immediately available to
the sync CLI, the sync worker, and the demo. Nothing else needs to change.

Each entry pairs the integration class with the location of its bundled synthetic
fixture, so the keyless path can sync it. A live deployment supplies a real client to
the integration instead of a fixture path; that path is selected by the integration
itself based on the configured credentials.
"""

from __future__ import annotations

from dataclasses import dataclass

from .base import Integration
from .gcal.sync import GCalSync
from .gdocs.sync import GDocsSync
from .gmail.sync import GmailSync
from .slack.sync import SlackSync


@dataclass(frozen=True)
class IntegrationSpec:
    """How to construct one integration from a fixture."""

    name: str
    cls: type[Integration]
    fixture_subdir: str
    fixture_file: str


# The registry. To add an app, append one IntegrationSpec.
REGISTRY: dict[str, IntegrationSpec] = {
    "slack": IntegrationSpec("slack", SlackSync, "slack", "workspace.json"),
    "gcal": IntegrationSpec("gcal", GCalSync, "gcal", "calendar.json"),
    "gdocs": IntegrationSpec("gdocs", GDocsSync, "gdocs", "docs.json"),
    "gmail": IntegrationSpec("gmail", GmailSync, "gmail", "mailbox.json"),
}

# The default set synced by ``omb sync run all`` and the worker. Gmail is included so
# the registry, the CLI, and the worker all agree on the available apps. It can be
# excluded per deployment by passing an explicit app list.
DEFAULT_APPS: tuple[str, ...] = ("slack", "gcal", "gdocs", "gmail")


def build_integration(name: str, store, config):
    """Build an integration by name from its bundled fixture."""
    from ..events.store import EventStore

    spec = REGISTRY[name]
    fixtures_path = config.fixtures_dir / spec.fixture_subdir / spec.fixture_file
    return spec.cls(EventStore(store.backend, store.blobs), fixtures_path=fixtures_path)
