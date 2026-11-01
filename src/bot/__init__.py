"""
Telegram Bot integration package for telegram-journal-analytics.
Provides decoupled bot API client, message formatters, and interactive handlers.
"""

from src.bot.client import TelegramClient
from src.bot.config import BotConfig, load_config
from src.bot.discord_relay import (
    flush_pending_relays,
    format_discord_payload,
    queue_pending_relay,
    send_discord_relay,
)
from src.bot.formatter import format_otd_message, format_stats_message
from src.bot.live_sync import (
    get_live_delta_path,
    ingest_channel_post,
    load_unified_journal,
    parse_channel_post,
)

__all__ = [
    "TelegramClient",
    "BotConfig",
    "load_config",
    "format_discord_payload",
    "send_discord_relay",
    "flush_pending_relays",
    "queue_pending_relay",
    "format_otd_message",
    "format_stats_message",
    "get_live_delta_path",
    "ingest_channel_post",
    "load_unified_journal",
    "parse_channel_post",
]
