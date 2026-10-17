import asyncio
import logging
import os
from contextlib import suppress
from datetime import datetime, timezone

import asyncpg
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("telegram-bot")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
PORT = int(os.getenv("PORT", "10000"))
ADMIN_IDS = {
    int(value.strip())
    for value in os.getenv("ADMIN_IDS", "").split(",")
    if value.strip().isdigit()
}

if not BOT_TOKEN:
    raise RuntimeError("Missing BOT_TOKEN environment variable.")
if not DATABASE_URL:
    raise RuntimeError(
        "Missing DATABASE_URL. Configure a persistent external PostgreSQL database "
        "so data is not lost when Render restarts or redeploys the service."
    )

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
db_pool: asyncpg.Pool | None = None


def is_admin(message: Message) -> bool:
    return bool(message.from_user and message.from_user.id in ADMIN_IDS)


async def save_user(message: Message) -> None:
    """Persist a Telegram user without storing passwords, OTPs, or session tokens."""
    if not message.from_user or db_pool is None:
        return
    user = message.from_user
    await db_pool.execute(
        """
        INSERT INTO telegram_users (user_id, username, first_name, created_at, last_seen)
        VALUES ($1, $2, $3, NOW(), NOW())
        ON CONFLICT (user_id) DO UPDATE SET
            username = EXCLUDED.username,
            first_name = EXCLUDED.first_name,
            last_seen = NOW()
        """,
        user.id,
        user.username,
        user.first_name,
    )


@dp.message(Command("start"))
async def start(message: Message):
    try:
        await save_user(message)
    except Exception:
        log.exception("Failed to save Telegram user")
        await message.answer("⚠️ Database save failed. Please try again shortly.")
        return
    await message.answer(
        "👋 Bot is online! Your Telegram user record is saved in the database.\n\n"
        "/help — commands\n"
        "/id — your Telegram user ID\n"
        "/status — admin-only service/database status"
    )


@dp.message(Command("help"))
async def help_command(message: Message):
    await message.answer(
        "Commands:\n"
        "/start — register/update your user record\n"
        "/id — show your Telegram ID\n"
        "/status — admin-only service/database status"
    )


@dp.message(Command("id"))
async def show_id(message: Message):
    if message.from_user:
        await message.answer(f"Your Telegram ID: {message.from_user.id}")


@dp.message(Command("status"))
async def status(message: Message):
    if not is_admin(message):
        await message.answer("⛔ Admin-only command.")
        return
    try:
        count = await db_pool.fetchval("SELECT COUNT(*) FROM telegram_users")
        await message.answer(f"✅ Bot running\nDatabase connected\nSaved users: {count}")
    except Exception:
        log.exception("Database status check failed")
        await message.answer("⚠️ Bot is running, but the database check failed.")


async def health(request: web.Request) -> web.Response:
    return web.json_response(
        {"status": "ok", "service": "telegram-bot", "time": datetime.now(timezone.utc).isoformat()}
    )


async def start_http_server() -> web.AppRunner:
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    log.info("Health server listening on 0.0.0.0:%s", PORT)
    return runner


async def main():
    global db_pool
    db_pool = await asyncpg.create_pool(
        dsn=DATABASE_URL,
        ssl="require",
        min_size=1,
        max_size=5,
        command_timeout=15,
    )
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS telegram_users (
                    user_id BIGINT PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        runner = await start_http_server()
        try:
            await dp.start_polling(bot)
        finally:
            await runner.cleanup()
    finally:
        if db_pool is not None:
            await db_pool.close()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
