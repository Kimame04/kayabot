#!/usr/bin/env python3
"""
Interactive Telegram Companion Bot Daemon for telegram-journal-analytics.
Listens for user commands (/otd, /random, /stats, /tag) and callback queries.

Usage:
    python -m scripts.run_bot
    python -m scripts.run_bot --export-dir ChatExport_sample
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import threading
import time

# Add project root to sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from src.bot.client import TelegramClient, TelegramAPIError
from src.bot.config import load_config
from src.bot.live_sync import load_unified_journal
from src.bot.handlers import BotDispatcher, resolve_export_dir


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run interactive Telegram companion bot for journal analytics."
    )
    parser.add_argument(
        "--export-dir",
        "-i",
        type=str,
        default=None,
        help="Path to Telegram ChatExport directory (auto-detected if omitted).",
    )
    args = parser.parse_args()

    config = load_config()
    if not config.bot_token:
        print("❌ Error: TELEGRAM_BOT_TOKEN not configured in .env!", file=sys.stderr)
        sys.exit(1)

    client = TelegramClient(config.bot_token)
    try:
        me = client.get_me()
        bot_username = me.get("username", "Unknown")
        bot_name = me.get("first_name", "Bot")
    except TelegramAPIError as e:
        print(f"❌ Failed to connect to Telegram Bot API: {e}", file=sys.stderr)
        sys.exit(1)

    print("=" * 60)
    print(f"🤖 Starting {bot_name} (@{bot_username})...")
    print("=" * 60)

    # Resolve export directory and load unified journal archive (Base + Live Delta)
    export_dir = resolve_export_dir(args.export_dir or config.export_dir)
    print(f"[Bot] Loading journal archive from: {export_dir.name}")
    df = load_unified_journal(export_dir, verbose=True)
    print(f"[Bot] Loaded {len(df):,} total journal entries.")

    dispatcher = BotDispatcher(client, config, df)

    print("\n🟢 Bot is live and listening for messages & channel posts!")
    print(f"👉 Open Telegram and chat with: https://t.me/{bot_username}")
    if config.channel_id:
        print(f"📢 Live ingestion active for channel ID: {config.channel_id}")
    else:
        print("💡 Live ingestion: Add this bot as an Admin in your channel to auto-sync posts!")
    if config.has_discord_relay:
        print("🔗 Discord live relay: Active")
    print("Commands supported: /otd, /random, /stats, /tag <name>, /help")
    print("Press Ctrl+C to terminate.\n")

    offset = None
    if config.has_discord_relay:
        from src.bot.discord_relay import flush_pending_relays
        flushed = flush_pending_relays(
            config.discord_webhook_url,
            author_name=config.discord_author_name,
            author_icon_url=config.discord_author_icon_url,
            client=client,
            delta_path=dispatcher.delta_path,
        )
        if flushed:
            print(f"📢 [DiscordRelay] Flushed {flushed} backlogged reflection(s) to Discord on startup.")

    # Reconcile channel deletions on startup
    if config.channel_id:
        startup_reconciled = dispatcher.run_channel_reconciliation(notify=False)
        if startup_reconciled:
            print(f"🧹 [LiveSync] Reconciled {len(startup_reconciled)} direct channel deletion(s) on startup.")

    RECONCILE_INTERVAL_SEC = 30  # check for direct channel deletions every 30 seconds
    stop_event = threading.Event()

    if config.channel_id:
        def reconcile_worker() -> None:
            while not stop_event.is_set():
                if stop_event.wait(RECONCILE_INTERVAL_SEC):
                    break
                try:
                    dispatcher.run_channel_reconciliation(notify=True)
                except Exception as e:
                    print(f"⚠️ [LiveSync Worker] Error during background deletion reconciliation: {e}")

        reconcile_thread = threading.Thread(
            target=reconcile_worker,
            name="ChannelReconciliationWorker",
            daemon=True,
        )
        reconcile_thread.start()
        print(f"🔄 [LiveSync] Background deletion reconciliation worker started ({RECONCILE_INTERVAL_SEC}s interval).")

    consecutive_errors = 0
    while True:
        try:
            updates = client.get_updates(offset=offset, timeout=20)
            consecutive_errors = 0

            for update in updates:
                offset = update["update_id"] + 1

                # Handle private user text messages & DM commands
                if "message" in update:
                    msg = update["message"]
                    sender = msg.get("from", {}).get("first_name", "User")
                    text = msg.get("text", "")
                    print(f"📩 [{sender}]: {text}")
                    dispatcher.dispatch_message(msg)

                # Handle inline callback queries
                elif "callback_query" in update:
                    cb = update["callback_query"]
                    sender = cb.get("from", {}).get("first_name", "User")
                    data = cb.get("data", "")
                    print(f"🔘 [{sender} clicked]: {data}")
                    dispatcher.dispatch_callback_query(cb)

                # Handle live channel posts (new reflections)
                elif "channel_post" in update:
                    post = update["channel_post"]
                    dispatcher.dispatch_channel_post(post)

                # Handle edited channel posts
                elif "edited_channel_post" in update:
                    post = update["edited_channel_post"]
                    dispatcher.dispatch_edited_channel_post(post)

        except KeyboardInterrupt:
            print("\n🛑 Shutting down Telegram bot...")
            stop_event.set()
            break
        except TelegramAPIError as e:
            consecutive_errors += 1
            print(f"⚠️ Telegram API Error ({consecutive_errors}): {e}")
            time.sleep(min(30, 2 ** consecutive_errors))
        except Exception as e:
            consecutive_errors += 1
            print(f"⚠️ Unexpected error ({consecutive_errors}): {e}")
            time.sleep(min(30, 2 ** consecutive_errors))


if __name__ == "__main__":
    main()
