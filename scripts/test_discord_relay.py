"""
CLI verification script to test Discord Webhook Relay.
Usage:
    python -m scripts.test_discord_relay "Custom reflection text here [tag]"
"""

from __future__ import annotations

import argparse
from datetime import datetime
import sys

from src.bot.config import load_config
from src.bot.discord_relay import format_discord_payload, send_discord_relay
from src.parser import _extract_bracket_tags


def main() -> None:
    parser = argparse.ArgumentParser(description="Test sending a reflection card to Discord via Webhook.")
    parser.add_argument(
        "text",
        nargs="?",
        default="Testing the Kaya Discord Live Journal Relay! 🚀 Live reflections will now sync directly into this channel. [setup] [kaya]",
        help="Custom test message content",
    )
    args = parser.parse_args()

    config = load_config()

    if not config.has_discord_relay:
        print("❌ Error: DISCORD_WEBHOOK_URL is not configured in .env or environment.")
        print("Add DISCORD_WEBHOOK_URL=\"https://discord.com/api/webhooks/...\" to .env first.")
        sys.exit(1)

    print(f"📡 Testing Discord Webhook Relay...")
    # Hide sensitive token part from terminal output
    parts = config.discord_webhook_url.split("/")
    masked_url = "/".join(parts[:-1]) + "/******"
    print(f"Target Webhook: {masked_url}")

    tags = _extract_bracket_tags(args.text)
    sample_row = {
        "id": 9999,
        "timestamp": datetime.now(),
        "text": args.text,
        "word_count": len(args.text.split()),
        "char_count": len(args.text),
        "tags": tags,
        "first_tag": tags[0] if tags else None,
        "total_reactions": 1,
    }

    success = send_discord_relay(config.discord_webhook_url, sample_row)
    if success:
        print("✅ Success! Discord webhook received the message and returned 200/204.")
        print("Check your Discord channel to verify the embed rendering.")
    else:
        print("❌ Failed to send message to Discord webhook.")
        print("Please check that the webhook URL is valid and active in Discord.")
        sys.exit(1)


if __name__ == "__main__":
    main()
