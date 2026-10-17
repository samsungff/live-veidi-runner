# Telegram Polling Bot

A lightweight Python Telegram bot using aiogram 3. It runs as a polling process, so deploy it on Render as a **Background Worker**, not a Web Service.

## Files

- `bot.py` — bot handlers
- `requirements.txt` — Python dependencies
- `Procfile` — worker start command
- `.env.example` — required environment variables

## Run locally

1. Install Python 3.11 or newer.
2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Set `BOT_TOKEN` in your environment. Optionally set `ADMIN_IDS` to comma-separated Telegram numeric user IDs.
4. Run:

   ```bash
   python bot.py
   ```

## Deploy to Render

1. In Render, choose **New → Background Worker**.
2. Connect this GitHub repository and select the `main` branch.
3. Build command: `pip install -r requirements.txt`
4. Start command: `python bot.py`
5. Add environment variables:
   - `BOT_TOKEN`: token from BotFather
   - `ADMIN_IDS`: your Telegram numeric user ID (optional, comma-separated)

## Security notes

- Never commit a real Telegram bot token, passwords, OTPs, cookies, or account session tokens.
- This starter does not collect or store third-party account credentials or session tokens.
- Keep sensitive projects in a private repository. If a secret was ever committed, rotate it; deleting the file alone does not revoke the secret.
- SQLite files are runtime data and are ignored by Git. Configure persistent storage or an external database if your bot later needs durable data.
