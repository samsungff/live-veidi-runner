# Telegram Bot — Render Web Service

This repository contains a Python Telegram bot with an HTTP health endpoint and PostgreSQL persistence.

## What persists

- When someone sends `/start`, their Telegram user ID, username, first name, registration time, and last-seen time are saved in PostgreSQL.
- The database is external to the Render web service, so service restarts, sleep, and redeploys do not erase those rows.
- This starter does **not** implement the previous Classplus/SciAstra account/token-management features, and it does not store passwords, OTPs, cookies, or session tokens.

## Deploy as a Render Web Service

1. Create a persistent PostgreSQL database with a provider of your choice. Copy its PostgreSQL connection URL. Keep it private.
2. In Render, create **New → Web Service** and connect `samsungff/live-veidi-runner`, branch `main`.
3. Runtime: Python.
4. Build command: `pip install -r requirements.txt`
5. Start command: `python bot.py`
6. Add environment variables:
   - `BOT_TOKEN`: Telegram bot token from BotFather
   - `DATABASE_URL`: PostgreSQL connection URL (use the provider's pooled URL if it recommends one)
   - `ADMIN_IDS`: optional comma-separated Telegram numeric user IDs
7. Set Render's health check path to `/health` if the health-check-path field is available.
8. After deployment, open `https://YOUR-SERVICE.onrender.com/health`. It should return JSON with `"status": "ok"`.

## UptimeRobot

Create an HTTP(s) monitor for `https://YOUR-SERVICE.onrender.com/health`. Replace the hostname with the actual Render service URL. A ping can wake a sleeping free web service, but free Render services can still sleep/restart and the monitor cannot guarantee uninterrupted bot availability.

## Important database warning

Do **not** use a local SQLite file for durable production data on a Render free web service: its filesystem is ephemeral. Render's own free PostgreSQL databases currently expire after 30 days, so for data you need to keep long-term, choose a database plan/provider that does not automatically expire or make regular backups and verify restore procedures. No free hosted service can honestly guarantee permanent storage without limits.

## Run locally

1. Install Python 3.11 or newer.
2. Install dependencies: `pip install -r requirements.txt`
3. Set `BOT_TOKEN` and `DATABASE_URL` in your environment.
4. Run: `python bot.py`

## Security

- Never commit real tokens or connection URLs to GitHub.
- Do not send account passwords, OTPs, cookies, or session tokens through bot replies or logs.
- Configure `ADMIN_IDS` for the admin-only `/status` command.
