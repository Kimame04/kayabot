# KayaBot 🥪

> A personal reflection familiar for Telegram channels. Streams live thoughts into Discord with circadian aesthetics, backed by multi-year flashbacks and deep behavioral analytics.

[![Tests](https://img.shields.io/badge/tests-81%20passed-brightgreen.svg)](#-testing)
[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](environment.yml)
[![Zero Dependency Bot API](https://img.shields.io/badge/bot--api-zero--dependency-orange.svg)](src/bot/client.py)
[![Privacy First](https://img.shields.io/badge/privacy-100%25%20offline-success.svg)](#-privacy--data-isolation)

---

## ✨ Features at a Glance

* **⚡ Live Discord Relay:** Streams reflections from your Telegram channel into Discord in real time.
  * **Circadian Theming:** Embed borders dynamically color-code based on your reflection's time of day.
  * **Rich Media:** Automatically mirrors attached photos and videos.
  * **Selective Privacy:** Configurable privacy tags keep sensitive reflections archived locally while skipping Discord.
  * **Offline Resilience:** Failsafe queue auto-delivers reflections if your machine sleeps or disconnects.
* **💬 In-Chat Familiar:** Chat directly with KayaBot in Telegram for instant multi-year flashbacks (`/otd`), statistics, and topic search.
* **📊 Retrospective Analytics:** Compiles sub-second interactive HTML dashboards: circadian habit curves, tag lifecycles, and Spotify Wrapped-style annual reviews.

---

## ⚡ Quick Start

### 1. Install
```bash
conda env create -f environment.yml && conda activate tele-journal
# or: pip install -r requirements.txt
```

### 2. Configure (`.env`)
```bash
cp .env.example .env
```
Fill in your credentials:
```env
TELEGRAM_BOT_TOKEN="your_bot_token"
DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..."
DISCORD_AUTHOR_NAME="My Journal"
```

Link your chat & channel:
1. Run `python -m scripts.get_chat_id`, open Telegram, and tap **START** on your bot.
2. Add your bot as an **Admin** to your private journal channel with "Post Messages" permission.

### 3. Run as 24/7 Background Service (macOS)
```bash
python -m scripts.setup_daemon install    # Install & start launchd daemon
python -m scripts.setup_daemon status     # Check health & recent logs
python -m scripts.setup_daemon restart    # Reload code or .env changes
```
*(Or run interactively in foreground: `python -m scripts.run_bot`)*

---

## 🤖 Bot Commands (Telegram DM)

Only your whitelisted `TELEGRAM_CHAT_ID` can interact with the bot:

| Command | Description |
| :--- | :--- |
| **`/otd`** | Multi-year flashback for today's calendar date |
| **`/otd MM-DD`** | Flashback for a specific date (e.g. `/otd 09-15`) |
| **`/random`** | Pull a random memory from your archive |
| **`/stats`** | Instant scorecard: total entries, words, book pages, streaks, circadian persona |
| **`/tag <name>`** | Deep dive into an interest tag (e.g. `/tag reading` or `/tag f1`) |
| **`/delete <id>`** | Purge a reflection across channel, Discord mirror, and local archive |
| **`/reconcile`** | Probe recent channel posts to reconcile direct channel deletions |
| **`/help`** | Command directory and navigation buttons |

> **Daily Morning Flashback:** Run `python -m scripts.send_daily_otd` (supports `--dry-run`) via cron or launchd to receive today's memory card every morning.

---

## 📊 Analytics & Master Dossier

Run analytics directly from your terminal or open standalone dark-mode HTML reports:

```bash
# Master Dossier: runs all 4 engines in ~0.2s and opens unified dashboard
python -m scripts.run_all --open

# Individual Reports
python -m scripts.run_circadian       # 24h hourly curves, weekly heatmaps, night-owl index
python -m scripts.run_tag_lifecycles  # [tag] streamgraph & lifespan categorization
python -m scripts.run_wrapped         # Spotify Wrapped-style story deck (--all-time or --year 2024)
python -m scripts.run_otd             # Terminal flashback feed (--date 09-15 --window 2)
```

---

## 🧪 Testing

```bash
python -m unittest discover tests
```
* **81/81 unit tests passing** with 100% mocked network calls.
* Fully self-contained; tests run against synthetic benchmarks (`ChatExport_sample/`) without needing private data.

---

## 🔒 Privacy & Data Isolation

* **Strictly Local:** Personal exports (`ChatExport_*`), `.cache/`, and `.env` are gitignored.
* **Access Control:** KayaBot rejects commands from any unverified user ID.
* **Public Demos:** Online [documentation showcase](https://kimame04.github.io/telegram-journal-analytics/) is generated exclusively from synthetic data.
