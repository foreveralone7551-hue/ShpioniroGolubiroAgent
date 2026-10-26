"""Конфигурация из переменных окружения / файла .env (без внешних зависимостей)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo


def _load_dotenv(path: str = ".env") -> None:
    """Читает .env и дополняет os.environ (уже заданные переменные не трогает)."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    token: str
    bot_username: str
    tz: ZoneInfo
    db_path: str
    retain_days: int
    use_topics: bool
    channel: str
    instruction_url: str


def load_config() -> Config:
    _load_dotenv()
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token or token.endswith("replace_me"):
        raise SystemExit("Укажите BOT_TOKEN в файле .env (токен от @BotFather).")
    channel = os.getenv("CHANNEL", "").strip()
    if channel and not channel.startswith("@"):
        channel = "@" + channel
    return Config(
        token=token,
        bot_username=os.getenv("BOT_USERNAME", "ShpioniroGolubiroAgent").strip().lstrip("@"),
        tz=ZoneInfo(os.getenv("TZ", "Europe/Moscow").strip()),
        db_path=os.getenv("DB_PATH", "data/bot.db").strip(),
        retain_days=max(1, int(os.getenv("RETAIN_DAYS", "30") or 30)),
        use_topics=_flag("USE_TOPICS", True),
        channel=channel,
        instruction_url=os.getenv("INSTRUCTION_URL", "").strip(),
    )
