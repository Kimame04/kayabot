"""
Configuration loader for Telegram Bot integration.
Parses local .env file or environment variables with zero third-party dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Optional


@dataclass
class BotConfig:
    bot_token: str
    chat_id: Optional[str] = None
    channel_id: Optional[str] = None
    export_dir: Optional[str] = None
    discord_webhook_url: Optional[str] = None
    discord_author_name: str = "Kyan's Journal"
    discord_author_icon_url: Optional[str] = None

    @property
    def is_configured(self) -> bool:
        """True if bot_token is present and valid."""
        return bool(self.bot_token and self.bot_token.strip())

    @property
    def can_send(self) -> bool:
        """True if bot_token and chat_id are both present."""
        return self.is_configured and bool(self.chat_id and str(self.chat_id).strip())

    @property
    def can_ingest_channel(self) -> bool:
        """True if bot_token is configured and channel_id is designated."""
        return self.is_configured and bool(self.channel_id and str(self.channel_id).strip())

    @property
    def has_discord_relay(self) -> bool:
        """True if discord_webhook_url is configured and non-empty."""
        return bool(self.discord_webhook_url and self.discord_webhook_url.strip())


def get_repo_root() -> Path:
    """Returns the repository root directory."""
    return Path(__file__).resolve().parent.parent.parent


def parse_env_file(env_path: Path) -> dict[str, str]:
    """Parse a simple .env file into a dictionary."""
    env_vars: dict[str, str] = {}
    if not env_path.exists():
        return env_vars

    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip().strip("'\"")
                env_vars[key] = val
    return env_vars


def load_config(env_file: Optional[Path] = None) -> BotConfig:
    """
    Load bot configuration from .env file or system environment.
    Precedence: os.environ > .env file.
    """
    root = get_repo_root()
    path = env_file or (root / ".env")
    file_vars = parse_env_file(path)

    token = os.environ.get("TELEGRAM_BOT_TOKEN") or file_vars.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID") or file_vars.get("TELEGRAM_CHAT_ID", "")
    channel_id = os.environ.get("TELEGRAM_CHANNEL_ID") or file_vars.get("TELEGRAM_CHANNEL_ID", "")
    export_dir = os.environ.get("DEFAULT_EXPORT_DIR") or file_vars.get("DEFAULT_EXPORT_DIR")
    discord_webhook = os.environ.get("DISCORD_WEBHOOK_URL") or file_vars.get("DISCORD_WEBHOOK_URL")
    author_name = os.environ.get("DISCORD_AUTHOR_NAME") or file_vars.get("DISCORD_AUTHOR_NAME") or "Kyan's Journal"
    author_icon = os.environ.get("DISCORD_AUTHOR_ICON_URL") or file_vars.get("DISCORD_AUTHOR_ICON_URL")

    return BotConfig(
        bot_token=token.strip(),
        chat_id=str(chat_id).strip() if chat_id else None,
        channel_id=str(channel_id).strip() if channel_id else None,
        export_dir=export_dir.strip() if export_dir else None,
        discord_webhook_url=str(discord_webhook).strip() if discord_webhook else None,
        discord_author_name=str(author_name).strip(),
        discord_author_icon_url=str(author_icon).strip() if author_icon else None,
    )


def _update_env_var(key: str, value: str | int, env_file: Optional[Path] = None) -> Path:
    """Updates or inserts a key=value pair in the local .env file."""
    root = get_repo_root()
    path = env_file or (root / ".env")
    val_str = str(value).strip()

    lines: list[str] = []
    found = False

    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith(f"{key}="):
                    lines.append(f'{key}="{val_str}"\n')
                    found = True
                else:
                    lines.append(line)

    if not found:
        lines.append(f'{key}="{val_str}"\n')

    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)

    return path


def save_chat_id_to_env(chat_id: str | int, env_file: Optional[Path] = None) -> Path:
    """Updates or inserts TELEGRAM_CHAT_ID into the local .env file."""
    return _update_env_var("TELEGRAM_CHAT_ID", chat_id, env_file)


def save_channel_id_to_env(channel_id: str | int, env_file: Optional[Path] = None) -> Path:
    """Updates or inserts TELEGRAM_CHANNEL_ID into the local .env file."""
    return _update_env_var("TELEGRAM_CHANNEL_ID", channel_id, env_file)
