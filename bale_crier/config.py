"""Settings, read from the environment with the ``CRIER_`` prefix."""

from pathlib import Path

from pydantic import Field, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_PREFIX = "CRIER_"


class ConfigError(Exception):
    """A misconfiguration, worded so the owner reads prose and not a traceback."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX,
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bale_bot_token: str
    bale_chat_id: int
    lists_dir: Path = Path("lists")
    history_path: Path = Path("data/history.jsonl")
    # Bounded below because each of these silently does damage at zero: a cap of
    # zero empties the history, and a zero timeout fails every call.
    history_max_lines: int = Field(default=5000, ge=1)
    http_timeout: int = Field(default=30, ge=1)
    smoke: bool = False
    open_ai_base_url: str = "https://api.avalai.ir/v1"
    open_ai_model: str = "deepseek-v4-flash"
    open_ai_api_key: str | None = None
    avalai_api_key: str | None = None
    credit_threshold_irt: float = Field(default=50_000, ge=0)
    watchers_state_path: Path = Path("data/watchers.json")
    # Bounded above zero: a window of zero would speak on every failed read.
    credit_unknown_alert_hours: float = Field(default=24, gt=0)

    @model_validator(mode="after")
    def _inherit_the_llm_key(self) -> "Settings":
        # One AvalAI key covers both the credit read and the rewording, so an empty
        # CRIER_OPEN_AI_API_KEY takes the other one rather than making the owner
        # paste the same secret twice. An explicit key always wins.
        if not self.open_ai_api_key:
            self.open_ai_api_key = self.avalai_api_key or None
        return self


def _message(error: dict) -> str:
    field = ".".join(str(part) for part in error["loc"])
    name = f"{ENV_PREFIX}{field.upper()}"
    if error["type"] == "missing":
        return f"متغیر محیطی {name} تنظیم نشده است؛ قاصد بدون آن نمی‌تواند چیزی بفرستد."
    return f"مقدار متغیر محیطی {name} نامعتبر است؛ مقدار درست را در محیط یا فایل .env بگذارید."


def load_settings() -> Settings:
    try:
        return Settings()
    except ValidationError as exc:
        raise ConfigError("\n".join(_message(error) for error in exc.errors())) from exc
