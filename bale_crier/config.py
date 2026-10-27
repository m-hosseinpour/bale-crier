"""Settings, read from the environment with the ``CRIER_`` prefix."""

from pathlib import Path

from pydantic import Field, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .news.feed import DEFAULT_FEED_URL

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
    # The model is a reasoning model and takes tens of seconds to answer where a
    # Bale or credit call takes milliseconds, so it gets its own allowance: at the
    # project's HTTP timeout every model call would be cut off and degrade to the
    # fallback text without a word about why.
    open_ai_timeout: int = Field(default=120, ge=1)
    avalai_api_key: str | None = None
    credit_threshold_irt: float = Field(default=50_000, ge=0)
    # The whole machine is one filesystem here (`/`), so that is what the disk
    # watcher reads unless the owner points it somewhere else.
    disk_path: Path = Path("/")
    # Bounded above zero: a threshold of zero could never be crossed. In GiB, the
    # unit the bulletin shows, so the setting and the message cannot disagree.
    disk_threshold_gib: float = Field(default=2, gt=0)
    # Bounded above zero: a window of zero would repeat the reminder every hour.
    disk_reminder_hours: float = Field(default=24, gt=0)
    watchers_state_path: Path = Path("data/watchers.json")
    # Bounded above zero: a window of zero would speak on every failed read.
    credit_unknown_alert_hours: float = Field(default=24, gt=0)
    # How long before a weekly package lapses the owner hears about it, in hours.
    # Bounded above zero: a window of zero is never entered, so it would say nothing.
    credit_expiry_warning_hours: float = Field(default=24, gt=0)
    # The local port, not the public hostname: the watcher talks to changedetection
    # on the loopback, so Caddy and TLS are not on the path and a public outage
    # cannot silence the watch.
    changedetection_url: str = "http://127.0.0.1:5005"
    # The API key changedetection shows in its own settings. No key means the API
    # refuses every read, so the watcher is not registered without one.
    changedetection_api_key: str | None = None
    # Bounded above zero, for the same reason as the credit window.
    changedetection_unknown_alert_hours: float = Field(default=24, gt=0)
    # The default lives in `news/feed.py`, where the feed's URL shape has its one
    # home, so the query is not written out twice.
    news_feed_url: str = DEFAULT_FEED_URL
    # Bounded below: a cap of zero asks the model for nothing while still spending
    # a call, and sends a digest with a header and no story under it.
    news_max_items: int = Field(default=10, ge=1)
    news_blocklist: str = ""

    @model_validator(mode="after")
    def _inherit_the_llm_key(self) -> "Settings":
        # One AvalAI key covers both the credit read and the rewording, so an empty
        # CRIER_OPEN_AI_API_KEY takes the other one rather than making the owner
        # paste the same secret twice. An explicit key always wins.
        if not self.open_ai_api_key:
            self.open_ai_api_key = self.avalai_api_key or None
        return self

    @model_validator(mode="after")
    def _default_the_feed_url(self) -> "Settings":
        # A shipped `CRIER_NEWS_FEED_URL=` would otherwise be read as an empty URL
        # rather than as "unset", so every fetch would fail. Empty means the
        # owner's query, exactly as empty means the built-in blocklist.
        if not self.news_feed_url.strip():
            self.news_feed_url = DEFAULT_FEED_URL
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
