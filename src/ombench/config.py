"""Runtime configuration.

Configuration is read from environment variables, optionally seeded from a ``.env``
file. The guiding rule is that nothing here is required: with an empty environment
the platform runs the full loop keyless using synthetic fixtures and a
deterministic agent and judge. Credentials and provider choices are additive.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:  # python-dotenv is a core dependency but keep import resilient.
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - defensive

    def load_dotenv(*_args, **_kwargs):  # type: ignore
        return False


def _env(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


@dataclass
class LLMConfig:
    """Selection of the LLM provider for the agent under test and the judge."""

    provider: str = "stub"  # stub | anthropic
    model: str = "claude-opus-4-8"
    judge_model: str = "claude-opus-4-8"
    anthropic_api_key: str = ""

    @property
    def has_anthropic(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def effective_provider(self) -> str:
        """Fall back to the stub when anthropic is requested without a key."""
        if self.provider == "anthropic" and not self.has_anthropic:
            return "stub"
        return self.provider


@dataclass
class SlackConfig:
    bot_token: str = ""
    signing_secret: str = ""

    @property
    def is_live(self) -> bool:
        return bool(self.bot_token)


@dataclass
class GoogleConfig:
    credentials_file: str = ""
    token_file: str = ""

    @property
    def is_live(self) -> bool:
        return bool(self.credentials_file and self.token_file)


@dataclass
class Config:
    """Top level configuration object.

    ``home`` is the root of the local store (blob store, SQLite database, compiled
    knowledge base). ``fixtures_dir`` and ``benchmarks_dir`` point at the bundled
    synthetic data used by the keyless path.
    """

    home: Path = field(default_factory=lambda: Path(".ombench"))
    repo_root: Path = field(default_factory=Path.cwd)
    llm: LLMConfig = field(default_factory=LLMConfig)
    slack: SlackConfig = field(default_factory=SlackConfig)
    google: GoogleConfig = field(default_factory=GoogleConfig)

    @property
    def db_path(self) -> Path:
        return self.home / "ombench.db"

    @property
    def blobs_dir(self) -> Path:
        return self.home / "blobs"

    @property
    def kb_dir(self) -> Path:
        return self.home / "memory"

    @property
    def fixtures_dir(self) -> Path:
        return self.repo_root / "fixtures"

    @property
    def benchmarks_dir(self) -> Path:
        return self.repo_root / "benchmarks"

    def ensure_dirs(self) -> None:
        """Create the local store directories if they do not already exist."""
        self.home.mkdir(parents=True, exist_ok=True)
        self.blobs_dir.mkdir(parents=True, exist_ok=True)


def load_config(*, env_file: str | os.PathLike[str] | None = ".env") -> Config:
    """Build a :class:`Config` from the environment.

    Reads ``.env`` if present, then layers in process environment variables. The
    result is a fully populated config where unset credentials simply leave the
    live paths disabled.
    """
    if env_file is not None and Path(env_file).exists():
        load_dotenv(env_file)

    home = Path(_env("OMBENCH_HOME", ".ombench")).expanduser()

    llm = LLMConfig(
        provider=_env("OMBENCH_LLM_PROVIDER", "stub"),
        model=_env("OMBENCH_LLM_MODEL", "claude-opus-4-8"),
        judge_model=_env("OMBENCH_JUDGE_MODEL", "claude-opus-4-8"),
        anthropic_api_key=_env("ANTHROPIC_API_KEY"),
    )
    slack = SlackConfig(
        bot_token=_env("SLACK_BOT_TOKEN"),
        signing_secret=_env("SLACK_SIGNING_SECRET"),
    )
    google = GoogleConfig(
        credentials_file=_env("GOOGLE_CREDENTIALS_FILE"),
        token_file=_env("GOOGLE_TOKEN_FILE"),
    )
    return Config(home=home, llm=llm, slack=slack, google=google)
