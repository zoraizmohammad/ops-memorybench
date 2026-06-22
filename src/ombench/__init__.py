"""ombench: memory and backtesting platform for operational agents.

ombench turns operational agent work into replayable history, compiles durable
knowledge from that history, and measures whether the compiled memory improves
performance under historical conditions.

The package is organized into layers that mirror the data flow:

- ``ombench.storage``     content addressed blob store and bitemporal backend
- ``ombench.traces``      agent agnostic trajectory capture
- ``ombench.events``      canonical append only bitemporal app event log
- ``ombench.snapshots``   point in time state materialization (git for SaaS)
- ``ombench.memory``      knowledge base compiler and hybrid retrieval
- ``ombench.replay``      deterministic simulated environment
- ``ombench.eval``        tasks rubrics judges and the paired backtest
- ``ombench.llm``         pluggable LLM layer with a deterministic stub
- ``ombench.integrations`` Slack Calendar Docs adapters and fixtures
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
