#!/usr/bin/env python3
"""
Utility script to retry and flush un-relayed reflections from live delta Parquet to Discord.
Finds reflections that were saved locally but missing a discord_message_id (e.g. due to
network/DNS dropouts), queues them, and flushes them to Discord with full media attachment support.

Usage:
    python -m scripts.retry_missed_relays
    python -m scripts.retry_missed_relays --ids 5815 5816 5817
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

# Add project root to sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

import pandas as pd

from src.bot.client import TelegramClient
from src.bot.config import load_config
from src.bot.discord_relay import flush_pending_relays, queue_pending_relay
from src.bot.live_sync import get_live_delta_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Retry un-relayed live reflections to Discord.")
    parser.add_argument(
        "--ids",
        nargs="+",
        type=int,
        default=None,
        help="Specific reflection IDs to re-dispatch (e.g. --ids 5815 5816 5817).",
    )
    args = parser.parse_args()

    config = load_config()
    if not config.has_discord_relay:
        print("❌ Error: DISCORD_WEBHOOK_URL is not configured in .env!", file=sys.stderr)
        sys.exit(1)

    delta_path = get_live_delta_path()
    if not delta_path.exists():
        print(f"❌ Error: Delta parquet not found at {delta_path}", file=sys.stderr)
        sys.exit(1)

    df = pd.read_parquet(delta_path)

    # Filter candidate entries
    if args.ids:
        candidates = df[df["id"].isin(args.ids)].copy()
    else:
        # Find entries without discord_message_id and not suppressed
        mask = (df["discord_message_id"].isna() | (df["discord_message_id"] == "")) & (~df["skip_discord"].fillna(False))
        candidates = df[mask].copy()

    if candidates.empty:
        print("✅ No un-relayed reflections found to dispatch.")
        return

    candidates = candidates.sort_values("id")
    print(f"📦 Found {len(candidates)} reflection(s) to re-dispatch: {list(candidates['id'])}")

    for _, row in candidates.iterrows():
        queue_pending_relay(dict(row), action="CREATE")

    print(f"📥 Queued {len(candidates)} reflection(s) into pending queue.")

    client = TelegramClient(config.bot_token) if config.bot_token else None

    print(f"🚀 Flushing to Discord webhook...")
    flushed = flush_pending_relays(
        config.discord_webhook_url,
        bot_name="Kaya",
        author_name=config.discord_author_name,
        author_icon_url=config.discord_author_icon_url,
        client=client,
        delta_path=delta_path,
    )

    print(f"✅ Successfully flushed {flushed}/{len(candidates)} reflection(s) to Discord!")


if __name__ == "__main__":
    main()
