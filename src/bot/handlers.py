"""
Telegram Bot Command & Event Handlers.
Routes incoming messages and callback queries to domain analytics logic.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from src.bot.client import TelegramClient
from src.bot.config import BotConfig, get_repo_root
from src.bot.formatter import (
    escape_html,
    format_otd_message,
    format_stats_message,
    format_tag_message,
)
from src.otd.logic import get_random_active_day, parse_query_date, query_on_this_day


def resolve_export_dir(preferred_dir: Optional[str | Path] = None) -> Path:
    """
    Resolve the Telegram export directory path with robust fallbacks:
    1. Preferred directory if passed and exists.
    2. 'ChatExport_kieran's channel' in repo root.
    3. Any ChatExport_* directory in repo root.
    4. 'ChatExport_sample' benchmark fixture.
    """
    root = get_repo_root()
    if preferred_dir:
        p = Path(preferred_dir).expanduser()
        if not p.is_absolute():
            p = root / p
        if p.exists() and p.is_dir():
            return p

    default_personal = root / "ChatExport_kieran's channel"
    if default_personal.exists() and default_personal.is_dir():
        return default_personal

    for candidate in sorted(root.glob("ChatExport_*")):
        if candidate.is_dir() and candidate.name != "ChatExport_sample":
            return candidate

    sample = root / "ChatExport_sample"
    if sample.exists() and sample.is_dir():
        return sample

    raise FileNotFoundError("Could not find any Telegram export directory in repository.")


def compute_quick_stats(df: pd.DataFrame) -> Dict[str, Any]:
    """Compute high-level summary KPIs from the parsed DataFrame."""
    total_messages = len(df)
    total_words = int(df["word_count"].sum()) if "word_count" in df.columns else 0
    pages = int(round(total_words / 250))

    # Night owl index (22:00 -> 04:00)
    hours = df["hour"] if "hour" in df.columns else pd.Series([], dtype=int)
    if not hours.empty:
        night_owl_mask = (hours >= 22) | (hours < 4)
        night_owl_pct = float(night_owl_mask.mean() * 100)
        peak_hour = int(hours.mode().iloc[0]) if not hours.mode().empty else 23
    else:
        night_owl_pct = 0.0
        peak_hour = 23

    # Persona heuristic
    if night_owl_pct > 50:
        persona = "The Midnight Philosopher 🌙"
    elif peak_hour < 12:
        persona = "The Dawn Chronicler 🌅"
    elif 12 <= peak_hour < 18:
        persona = "The Afternoon Synthesizer ☕"
    else:
        persona = "The Evening Storyteller 🌇"

    # Consistency & active days
    dates = pd.to_datetime(df["date"]).drop_duplicates().sort_values()
    if len(dates) >= 2:
        min_date, max_date = dates.min(), dates.max()
        span_days = max(1, (max_date - min_date).days + 1)
        consistency_pct = float(len(dates) / span_days * 100)

        # Longest day streak
        date_diffs = dates.diff().dt.days
        current_streak = 1
        longest_streak = 1
        for diff in date_diffs[1:]:
            if diff == 1:
                current_streak += 1
                longest_streak = max(longest_streak, current_streak)
            else:
                current_streak = 1
    else:
        consistency_pct = 100.0 if len(dates) == 1 else 0.0
        longest_streak = len(dates)

    # Top tags
    all_tags: List[str] = []
    if "tags" in df.columns:
        for tags_list in df["tags"].dropna():
            if hasattr(tags_list, "__iter__") and not isinstance(tags_list, (str, bytes)):
                all_tags.extend(tags_list)
    top_tags = [t for t, _ in pd.Series(all_tags).value_counts().head(5).items()] if all_tags else []

    return {
        "persona": persona,
        "night_owl_pct": night_owl_pct,
        "peak_hour": peak_hour,
        "total_messages": total_messages,
        "total_words": total_words,
        "pages": pages,
        "consistency_pct": consistency_pct,
        "streak": longest_streak,
        "top_tags": top_tags,
    }


class BotDispatcher:
    """Routes updates to corresponding command, callback, and live channel handlers."""

    def __init__(
        self,
        client: TelegramClient,
        config: BotConfig,
        df: pd.DataFrame,
        delta_path: Optional[Path] = None,
    ):
        self.client = client
        self.config = config
        self.df = df
        self.delta_path = delta_path

    def handle_start(self, chat_id: int | str) -> None:
        """Welcome message and command directory."""
        text = (
            "👋 <b>Welcome to your Telegram Journal Companion!</b>\n\n"
            "I connect directly with your journal archive to surface memories, track consistency, and profile your habits.\n\n"
            "<b>Available Commands:</b>\n"
            "• <code>/otd</code> — Flashback for today's calendar date\n"
            "• <code>/otd MM-DD</code> — Flashback for a specific date (e.g. <code>/otd 09-15</code> or <code>/otd Sep 15</code>)\n"
            "• <code>/random</code> — Discover a random past active journal day\n"
            "• <code>/stats</code> — High-level intelligence scorecard & streaks\n"
            "• <code>/tag &lt;name&gt;</code> — Search interest tag mentions (e.g. <code>/tag f1</code>)\n"
            "• <code>/help</code> — Show this manual\n\n"
            "✨ <i>Tip: Tap the buttons below to quickly explore your archive!</i>"
        )
        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "🕰️ Today's Flashback", "callback_data": "cmd:otd"},
                    {"text": "🎲 Random Memory", "callback_data": "cmd:random"},
                ],
                [
                    {"text": "📊 Journal Stats", "callback_data": "cmd:stats"},
                ],
            ]
        }
        self.client.send_message(chat_id, text, reply_markup=keyboard)

    def handle_otd(self, chat_id: int | str, date_arg: Optional[str] = None) -> None:
        """Handle /otd command."""
        try:
            target_month, target_day = parse_query_date(date_arg)
        except ValueError as e:
            self.client.send_message(chat_id, f"⚠️ {escape_html(str(e))}")
            return

        otd_result = query_on_this_day(self.df, month=target_month, day=target_day, window_days=0)
        messages = format_otd_message(otd_result)

        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "🎲 Random Memory", "callback_data": "cmd:random"},
                    {"text": "📊 Stats", "callback_data": "cmd:stats"},
                ]
            ]
        }

        for i, chunk in enumerate(messages):
            # Attach keyboard only to the final message chunk
            markup = keyboard if i == len(messages) - 1 else None
            self.client.send_message(chat_id, chunk, reply_markup=markup)

    def handle_random(self, chat_id: int | str) -> None:
        """Handle /random command."""
        month, day = get_random_active_day(self.df)
        otd_result = query_on_this_day(self.df, month=month, day=day, window_days=0)
        messages = format_otd_message(otd_result)

        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "🎲 Another Random", "callback_data": "cmd:random"},
                    {"text": "🕰️ Today's Flashback", "callback_data": "cmd:otd"},
                ]
            ]
        }

        for i, chunk in enumerate(messages):
            markup = keyboard if i == len(messages) - 1 else None
            self.client.send_message(chat_id, chunk, reply_markup=markup)

    def handle_stats(self, chat_id: int | str) -> None:
        """Handle /stats command."""
        stats = compute_quick_stats(self.df)
        text = format_stats_message(stats)
        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "🕰️ Today's Flashback", "callback_data": "cmd:otd"},
                    {"text": "🎲 Random Memory", "callback_data": "cmd:random"},
                ]
            ]
        }
        self.client.send_message(chat_id, text, reply_markup=keyboard)

    def handle_tag(self, chat_id: int | str, tag_query: str) -> None:
        """Handle /tag <tag> command."""
        clean_tag = tag_query.strip().lower().lstrip("#[").rstrip("]")
        if not clean_tag:
            self.client.send_message(chat_id, "⚠️ Please specify a tag. E.g.: <code>/tag f1</code>")
            return

        if "tags" not in self.df.columns:
            self.client.send_message(chat_id, "⚠️ No tags indexed in journal.")
            return

        # Filter dataframe for matching tag (exact match, or fallback to partial match)
        def tag_matches_exact(tags_val: Any) -> bool:
            if hasattr(tags_val, "__iter__") and not isinstance(tags_val, (str, bytes)):
                return clean_tag in [str(t).lower() for t in tags_val]
            return False

        matches = self.df[self.df["tags"].apply(tag_matches_exact)]
        matched_tag_label = clean_tag

        if matches.empty:
            def tag_matches_partial(tags_val: Any) -> bool:
                if hasattr(tags_val, "__iter__") and not isinstance(tags_val, (str, bytes)):
                    return any(clean_tag in str(t).lower() for t in tags_val)
                return False
            matches = self.df[self.df["tags"].apply(tag_matches_partial)]
            if not matches.empty:
                # Find the full matching tag name from the first match
                for t in matches.iloc[0]["tags"]:
                    if clean_tag in str(t).lower():
                        matched_tag_label = str(t)
                        break

        if matches.empty:
            self.client.send_message(chat_id, f"🔍 No entries found tagged with <code>[{escape_html(clean_tag)}]</code>.")
            return

        count = len(matches)
        dates = pd.to_datetime(matches["timestamp"]).sort_values()
        first_seen = dates.iloc[0].strftime("%b %d, %Y")
        last_seen = dates.iloc[-1].strftime("%b %d, %Y")
        sample_text = matches.iloc[-1].get("text", "")

        msg = format_tag_message(matched_tag_label, count, first_seen, last_seen, sample_text)
        self.client.send_message(chat_id, msg)

    def dispatch_message(self, message: Dict[str, Any]) -> None:
        """Route incoming message text to appropriate handler with strict access control."""
        chat_id = message.get("chat", {}).get("id")
        text = message.get("text", "").strip()
        if not chat_id or not text:
            return

        # Security Access Control: Whitelist check
        sender_id = str(message.get("from", {}).get("id", chat_id))
        if self.config.chat_id and sender_id != str(self.config.chat_id):
            print(f"🛑 [Security] Blocked unauthorized interaction attempt from user ID: {sender_id}")
            self.client.send_message(
                chat_id,
                "🔒 <b>Access Denied</b>\nThis is a private personal journal bot. Only the journal owner can access memories."
            )
            return

        parts = text.split(maxsplit=1)
        cmd = parts[0].lower().split("@")[0]  # strip bot username if present, e.g. /otd@kaya0401_bot
        arg = parts[1].strip() if len(parts) > 1 else None

        if cmd in ("/start", "/help"):
            self.handle_start(chat_id)
        elif cmd in ("/otd", "/today"):
            self.handle_otd(chat_id, date_arg=arg)
        elif cmd in ("/random", "/memory"):
            self.handle_random(chat_id)
        elif cmd in ("/stats", "/wrapped"):
            self.handle_stats(chat_id)
        elif cmd == "/tag":
            if arg:
                self.handle_tag(chat_id, arg)
            else:
                self.client.send_message(chat_id, "Usage: <code>/tag &lt;name&gt;</code> (e.g. <code>/tag f1</code>)")
        else:
            # If user sent plain text date (e.g. "Sep 15" or "09-15"), try to parse as OTD
            try:
                parse_query_date(text)
                self.handle_otd(chat_id, date_arg=text)
            except ValueError:
                self.client.send_message(
                    chat_id,
                    "❓ Unknown command. Send <code>/help</code> to see available actions."
                )

    def dispatch_callback_query(self, callback: Dict[str, Any]) -> None:
        """Handle inline button callback queries."""
        cb_id = callback.get("id")
        data = callback.get("data", "")
        message = callback.get("message", {})
        sender_id = str(callback.get("from", {}).get("id", ""))
        if self.config.chat_id and sender_id != str(self.config.chat_id):
            if cb_id:
                try:
                    self.client.answer_callback_query(cb_id, text="Access Denied: Private Bot", show_alert=True)
                except Exception:
                    pass
            return

        if cb_id:
            try:
                self.client.answer_callback_query(cb_id)
            except Exception:
                pass

        if not chat_id or not data:
            return

        if data == "cmd:otd":
            self.handle_otd(chat_id)
        elif data == "cmd:random":
            self.handle_random(chat_id)
        elif data == "cmd:stats":
            self.handle_stats(chat_id)

    def handle_channel_post(self, post: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Ingest incoming or edited channel post into the live delta layer."""
        from src.bot.config import save_channel_id_to_env
        from src.bot.live_sync import ingest_channel_post

        chat = post.get("chat", {})
        post_chat_id = str(chat.get("id"))

        # Channel verification & auto-discovery
        if self.config.channel_id:
            if post_chat_id != str(self.config.channel_id):
                # Ignore posts from non-configured channels
                return None
        else:
            # Auto-discover and persist channel ID if not yet configured
            save_channel_id_to_env(post_chat_id)
            self.config.channel_id = post_chat_id
            print(f"📢 [LiveSync] Auto-configured TELEGRAM_CHANNEL_ID=\"{post_chat_id}\" from channel: {chat.get('title')}")

        # Ingest and persist into live delta Parquet store
        row, is_new = ingest_channel_post(post, delta_path=self.delta_path)

        # Update in-memory DataFrame so /otd and /stats immediately reflect this entry
        new_row_df = pd.DataFrame([row])
        new_row_df["timestamp"] = pd.to_datetime(new_row_df["timestamp"])
        self.df = (
            pd.concat([self.df, new_row_df], ignore_index=True)
            .drop_duplicates(subset=["id"], keep="last")
            .sort_values("timestamp")
            .reset_index(drop=True)
        )

        status_tag = "New entry" if is_new else "Edited entry"
        print(f"✨ [LiveSync] {status_tag} #{row['id']} synced ({row['word_count']} words, tags: {row['tags']})")

        # Relay to Discord if webhook is configured and post is a new entry
        if is_new and self.config.has_discord_relay:
            from src.bot.discord_relay import flush_pending_relays, queue_pending_relay, send_discord_relay
            # Flush any prior backlog
            flush_pending_relays(
                self.config.discord_webhook_url,
                author_name=self.config.discord_author_name,
                author_icon_url=self.config.discord_author_icon_url,
            )

            file_bytes: Optional[bytes] = None
            filename: Optional[str] = None
            media_warning: Optional[str] = None

            # Handle media downloading with 10MB limit guardrails
            media_file_id = row.get("media_file_id")
            media_size = row.get("media_file_size") or 0
            max_discord_size = 10 * 1024 * 1024  # 10 MB

            if media_file_id:
                if media_size > max_discord_size:
                    media_type_label = (row.get("media_type") or "Media").title()
                    media_warning = f"⚠️ {media_type_label} ({media_size / (1024 * 1024):.1f} MB exceeds Discord limit — view in Telegram channel)"
                else:
                    try:
                        file_info = self.client.get_file(media_file_id)
                        file_path = file_info.get("file_path")
                        if file_path:
                            file_bytes = self.client.download_file(file_path, max_bytes=max_discord_size)
                            filename = row.get("media_file_name") or "reflection.jpg"
                    except Exception as e:
                        print(f"⚠️ [DiscordRelay] Failed to fetch media from Telegram: {e}")
                        media_warning = "⚠️ Media could not be downloaded (view in Telegram channel)"

            success = send_discord_relay(
                self.config.discord_webhook_url,
                row,
                file_bytes=file_bytes,
                filename=filename,
                media_warning=media_warning,
                author_name=self.config.discord_author_name,
                author_icon_url=self.config.discord_author_icon_url,
            )
            if success:
                media_str = f" with {row.get('media_type')}" if file_bytes else ""
                print(f"📢 [DiscordRelay] Reflection #{row['id']}{media_str} relayed to Discord")
            else:
                queue_pending_relay(row, media_warning=media_warning)
                print(f"⚠️ [DiscordRelay] Delivery failed; reflection #{row['id']} queued for retry")

        return row

    def dispatch_channel_post(self, post: Dict[str, Any]) -> None:
        """Route incoming new channel post."""
        self.handle_channel_post(post)

    def dispatch_edited_channel_post(self, post: Dict[str, Any]) -> None:
        """Route incoming edited channel post."""
        self.handle_channel_post(post)
