import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message

logging.basicConfig(level=logging.INFO)
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = {
    int(value.strip())
    for value in os.getenv("ADMIN_IDS", "").split(",")
    if value.strip().isdigit()
}

if not BOT_TOKEN:
    raise RuntimeError("Set BOT_TOKEN in the hosting environment variables.")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


def is_admin(message: Message) -> bool:
    return bool(message.from_user and message.from_user.id in ADMIN_IDS)


@dp.message(Command("start"))
async def start(message: Message):
    await message.answer(
        "👋 Bot is online!\n\n"
        "/help — commands\n"
        "/id — your Telegram user ID\n"
        "/status — admin-only status"
    )


@dp.message(Command("help"))
async def help_command(message: Message):
    await message.answer(
        "Commands:\n"
        "/start — start the bot\n"
        "/id — show your Telegram ID\n"
        "/status — admin-only status"
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
    await message.answer("✅ Bot is running.")


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
