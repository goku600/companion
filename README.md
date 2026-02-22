# Rovo Dev Telegram Bot

A **Telegram bot** that connects to the **Atlassian Rovo Dev AI agent** using your Atlassian email and API key. Users can ask questions and upload files for AI-powered analysis — all from Telegram.

Designed to be hosted on **[Render.com](https://render.com)** as a background worker (no open port needed).

---

## Features

| Feature | Details |
|---|---|
| 💬 Conversational AI | Full multi-turn chat backed by Atlassian Rovo Dev |
| 📎 File analysis | Upload text, code, CSV, JSON, PDF, images and more |
| 🔄 Session reset | `/reset` clears conversation history |
| 🔒 Access control | Optionally restrict to specific Telegram user IDs |
| ☁️ Render-ready | `render.yaml` included for one-click deploy |

---

## Prerequisites

1. **Python 3.11+**
2. A **Telegram bot token** — create one via [@BotFather](https://t.me/BotFather)
3. An **Atlassian account** with Rovo Dev enabled and an **API key**:
   - Generate your API key at: <https://id.atlassian.com/manage-profile/security/api-tokens>
4. A **Render.com** account (free tier works for a worker service)

---

## Local Development

```bash
# 1. Clone the repo
git clone https://github.com/YOUR_USERNAME/rovo-telegram-bot.git
cd rovo-telegram-bot

# 2. Create a virtual environment
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment variables
cp .env.example .env
# Edit .env and fill in your values

# 5. Load .env and run
export $(grep -v '^#' .env | xargs)   # Linux/macOS
# Windows PowerShell:
#   Get-Content .env | ForEach-Object { if ($_ -notmatch '^#' -and $_) { $env:($_.Split('=')[0]) = $_.Split('=',2)[1] } }

python bot.py
```

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | ✅ | Token from @BotFather |
| `ATLASSIAN_EMAIL` | ✅ | Your Atlassian account email |
| `ATLASSIAN_API_KEY` | ✅ | Atlassian API token |
| `ATLASSIAN_SITE_URL` | ✅ | e.g. `https://yourcompany.atlassian.net` |
| `ALLOWED_TELEGRAM_USER_IDS` | ❌ | Comma-separated numeric Telegram user IDs (leave blank to allow all) |

---

## Deploy to Render

### Option A — One-click via `render.yaml`

1. Push this repo to GitHub.
2. Go to [Render Dashboard](https://dashboard.render.com) → **New** → **Blueprint**.
3. Connect your GitHub repo — Render will detect `render.yaml` automatically.
4. Fill in the required environment variables in the Render dashboard.
5. Click **Apply** — your bot will be live in ~2 minutes.

### Option B — Manual

1. Go to Render → **New** → **Background Worker**.
2. Connect your GitHub repo.
3. Set:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python bot.py`
4. Add all environment variables from the table above.
5. Deploy.

> **Tip:** Use the **Free** tier — a background worker does not need a public URL, so it won't sleep like a web service would.

---

## Bot Commands

| Command | Description |
|---|---|
| `/start` | Welcome message and usage guide |
| `/help` | Show help |
| `/reset` | Clear your conversation history |

---

## Supported File Types

| Category | Extensions / Types |
|---|---|
| Code | `.py .js .ts .java .c .cpp .go .rs .rb .php .sh` … |
| Data | `.csv .json .xml .yaml .toml .sql` |
| Documents | `.txt .md .rst .log .html .css` |
| Images | `.jpg .png .gif .webp` (sent as base64 data-URI) |
| Binary | PDF and other formats (base64 encoded, size-limited) |

---

## Project Structure

```
rovo-telegram-bot/
├── bot.py            # Telegram bot entry point
├── rovo_client.py    # Atlassian Rovo Dev API client
├── requirements.txt  # Python dependencies
├── render.yaml       # Render.com deployment config
├── .env.example      # Environment variable template
├── .gitignore
└── README.md
```

---

## How It Works

```
User (Telegram)
      │
      │  text / file
      ▼
 Telegram Bot (python-telegram-bot)
      │
      │  HTTP POST (Basic Auth: email + API key)
      ▼
 Atlassian Rovo Dev Agent API
      │
      │  AI response
      ▼
 Telegram Bot → User
```

1. The bot receives a message or file from the user via Telegram.
2. It maintains per-user conversation history in memory.
3. Text files and code are embedded as plain text in the prompt.
4. Binary files (images, PDFs) are base64-encoded and sent as data-URIs.
5. The Atlassian Rovo Dev API returns an AI-generated response.
6. The bot sends the response back to the user, splitting long messages as needed.

---

## Security Notes

- **Never** commit your `.env` file — it is listed in `.gitignore`.
- Use `ALLOWED_TELEGRAM_USER_IDS` to restrict access in production.
- Rotate your Atlassian API key at <https://id.atlassian.com/manage-profile/security/api-tokens> if it is ever exposed.

---

## License

MIT — feel free to use and adapt.
