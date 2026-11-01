# Telegram Journal Analytics 🕰️📊

A privacy-focused personal analytics suite and companion Telegram bot for your personal journal channel. Transforms your raw reflections into interactive intelligence dossiers, multi-year "On This Day" flashbacks, and continuous real-time channel sync without manual exports.

For internal system designs, data models, and module topologies, see [ARCHITECTURE.md](ARCHITECTURE.md).

---

## ⚡ Quick Start

### 1. Environment Setup

```bash
# Using Conda (Recommended)
conda env create -f environment.yml
conda activate tele-journal

# Or using Pip
pip install -r requirements.txt
```

### 2. Set Up Your Telegram Companion Bot (5 Minutes)

1. **Create your bot:** Open Telegram, search for [`@BotFather`](https://t.me/BotFather), send `/newbot`, and copy your HTTP API token.
2. **Configure token:** Create a `.env` file in the project root:
   ```bash
   cp .env.example .env
   ```
   Add your token: `TELEGRAM_BOT_TOKEN="your_token_here"`
3. **Link your Telegram ID:** Run the discovery utility:
   ```bash
   python -m scripts.get_chat_id
   ```
   Open Telegram, search for your bot, and tap **START**. Your Chat ID will be captured and saved to `.env` automatically.
4. **Enable Live Channel Sync:**
   * Open your private journal channel $\rightarrow$ **Settings** $\rightarrow$ **Administrators** $\rightarrow$ **Add Admin**.
   * Add your bot with **"Post Messages"** permission. Every new reflection you write will now stream into your analytics in real time!

### 3. Run Your Bot & Generate Analytics

```bash
# Start the bot as a silent 24/7 background service on macOS (Recommended)
python -m scripts.setup_daemon install

# Dispatch today's flashback memory card to your Telegram chat
python -m scripts.send_daily_otd

# Generate and view the master dark-mode analytics dashboard in your browser
python -m scripts.run_all --open
```

---

## 🤖 Telegram Companion Bot Usage

### In Telegram Direct Messages (with your bot)
All commands feature an automatic security whitelist—only you (`TELEGRAM_CHAT_ID`) can interact with your bot.

| Command | Action |
| :--- | :--- |
| **`/start`** or **`/help`** | Open welcome dossier and interactive navigation buttons. |
| **`/otd`** | Display multi-year memories recorded on today's calendar date. |
| **`/otd MM-DD`** | Flashback for a specific date (e.g. `/otd 09-15` or `/otd Sep 15`). |
| **`/random`** | Discover a random past active journal day. |
| **`/stats`** | Instant scorecard: total entries, words, book pages, streaks, and circadian persona. |
| **`/tag <name>`** | Deep dive into an interest tag (e.g. `/tag f1` or `/tag reading`). |

### Managing the macOS Background Daemon
The daemon runs quietly across reboots, with logs written to `output/bot.log`.

```bash
# Check daemon health & view recent logs
python -m scripts.setup_daemon status

# Restart daemon (e.g. after adding new export archives)
python -m scripts.setup_daemon restart

# Stop and remove background service
python -m scripts.setup_daemon uninstall

# Or run interactively in a foreground terminal
python -m scripts.run_bot
```

### Scheduled Daily Morning Push
Schedule a daily flashback delivery to your Telegram chat every morning (e.g. at 8:00 AM via macOS `crontab` or `launchd`):

```bash
# Dispatch today's memory card
python -m scripts.send_daily_otd

# Preview the HTML card in your terminal without sending
python -m scripts.send_daily_otd --dry-run
```

### Discord Live Journal Relay (Optional)
If you have friends who don't use Telegram, you can stream your live reflections into a private Discord channel via Webhook:
1. In Discord, go to **Channel Settings** $\rightarrow$ **Integrations** $\rightarrow$ **Webhooks** $\rightarrow$ **New Webhook** and copy the URL.
2. Add to `.env`:
   ```bash
   DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..."
   ```
3. Test your connection directly:
   ```bash
   python -m scripts.test_discord_relay "Testing my Discord relay! [test]"
   ```
Whenever you post in your Telegram channel, KayaBot will immediately relay the post as a sleek, formatted embed card with auto-local timestamps, tags, and word counts. Photos are attached and displayed inline, and files over Discord's 10MB limit automatically degrade to a clean metadata notice without failing.

---

## 📊 Analytics & Master Dossier CLI

You can also run all analytics engines directly from your terminal or generate interactive HTML dashboards:

### 1. Master Journal Dossier (All-in-One Dashboard)
Runs all 4 analytical pipelines in a single sub-second pass and compiles `output/dashboard.html`:
```bash
# Generate and immediately open the dashboard in your default browser
python -m scripts.run_all --open

# Also output individual standalone reports (circadian, lifecycle, wrapped, OTD)
python -m scripts.run_all --all-reports

# Run against synthetic demo dataset
python -m scripts.run_all --export-dir "ChatExport_sample"
```

### 2. "On This Day" (OTD) Time Capsule
```bash
# Today's memories
python -m scripts.run_otd

# Custom date query with ±2 days window
python -m scripts.run_otd --date 09-15 --window 2

# Discover a random past memory
python -m scripts.run_otd --random
```

### 3. Tag & Hobby Lifecycles
Track how interests and hobbies evolve over time from bracket tags (`[tag]`):
```bash
python -m scripts.run_tag_lifecycles
```
Outputs an interactive Plotly streamgraph and horizontal Gantt charts classifying topics into **Evergreen Passions**, **Seasonal Bursts**, and **Emerging Eras**.

### 4. Circadian & Habit Heatmaps
```bash
python -m scripts.run_circadian
```
Generates 24-hour message distribution curves, day-of-week heatmaps, and longitudinal night-owl habit shifts.

### 5. Channel-Wrapped Retrospective ("Spotify Wrapped" Style)
```bash
# Retrospective for the latest active year (e.g. 2026)
python -m scripts.run_wrapped

# Retrospective across your entire journaling history
python -m scripts.run_wrapped --all-time

# Retrospective for a specific year
python -m scripts.run_wrapped --year 2024
```

---

## 🧪 Testing

Run the automated test suite across all modules:
```bash
python -m unittest discover tests
```
> **Self-Contained:** Tests automatically run against `ChatExport_sample` with 100% mocked network calls, allowing all 65 unit tests to pass out-of-the-box on fresh clones without needing private personal data.

---

## 🔒 Privacy & Data Isolation

Designed strictly for personal journal reflection:
* **Private Exports (`ChatExport_*`):** Excluded from version control in `.gitignore`.
* **Bot Secrets (`.env`):** Bot tokens and chat IDs are strictly ignored by git.
* **Access Control:** The bot rejects interaction attempts from unauthorized Telegram users.
* **Public Demos:** All documentation assets and demo reports are compiled exclusively from sanitized mock datasets (`ChatExport_sample/`).
