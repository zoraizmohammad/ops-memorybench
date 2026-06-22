"""The ``omb`` command line interface.

This is the operator facing entrypoint to the platform. Subcommands are added as
the layers land. At Phase 0 it exposes ``version`` and ``info``; later phases add
``saasgit``, ``trace``, ``sync``, ``memory``, ``replay``, and ``eval`` groups, plus
the top level ``demo`` that runs the full synthetic backtest.
"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from ombench import __version__
from ombench.cli import tracecmds
from ombench.config import load_config

app = typer.Typer(
    help="ombench: memory and backtesting for operational agents.",
    no_args_is_help=True,
    add_completion=False,
)
app.add_typer(tracecmds.app, name="trace")

console = Console()


@app.command()
def version() -> None:
    """Print the ombench version."""
    console.print(f"ombench {__version__}")


@app.command()
def info() -> None:
    """Show the active configuration and which live paths are enabled.

    With an empty environment every live path is disabled and the platform runs on
    synthetic fixtures with a deterministic agent and judge.
    """
    cfg = load_config()
    table = Table(title="ombench configuration")
    table.add_column("setting")
    table.add_column("value")
    table.add_row("version", __version__)
    table.add_row("home", str(cfg.home))
    table.add_row("llm provider requested", cfg.llm.provider)
    table.add_row("llm provider effective", cfg.llm.effective_provider)
    table.add_row("anthropic key present", "yes" if cfg.llm.has_anthropic else "no")
    table.add_row("slack live", "yes" if cfg.slack.is_live else "no (fixtures)")
    table.add_row("google live", "yes" if cfg.google.is_live else "no (fixtures)")
    console.print(table)


def main() -> None:  # pragma: no cover - thin wrapper
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
