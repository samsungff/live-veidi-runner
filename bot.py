import asyncio
import base64
import json
import logging
import os
from datetime import datetime, timezone

import asyncpg
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message
from cryptography.fernet import Fernet, InvalidToken

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("telegram-bot")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
TOKEN_ENCRYPTION_KEY = os.getenv("TOKEN_ENCRYPTION_KEY", "").strip()
PORT = int(os.getenv("PORT", "10000"))
ADMIN_IDS = {
    int(value.strip())
    for value in os.getenv("ADMIN_IDS", "").split(",")
    if value.strip().isdigit()
}

if not BOT_TOKEN:
    raise RuntimeError("Missing BOT_TOKEN environment variable.")
if not DATABASE_URL:
    raise RuntimeError("Missing DATABASE_URL environment variable.")
if not TOKEN_ENCRYPTION_KEY:
    raise RuntimeError(
        "Missing TOKEN_ENCRYPTION_KEY. Generate a Fernet key and set it in Render."
    )
try:
    cipher = Fernet(TOKEN_ENCRYPTION_KEY.encode())
except (ValueError, TypeError) as exc:
    raise RuntimeError("TOKEN_ENCRYPTION_KEY is not a valid Fernet key.") from exc

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
db_pool: asyncpg.Pool | None = None


class AddTokenFlow(StatesGroup):
    waiting_for_token = State()


def is_admin(message: Message) -> bool:
    return bool(message.from_user and message.from_user.id in ADMIN_IDS)


def decode_jwt_payload(token: str) -> dict:
    """Read JWT claims for display only; this does NOT verify the token signature."""
    try:
        parts = token.strip().split(".")
        if len(parts) != 3:
            return {}
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        return json.loads(base64.urlsafe_b64decode(payload.encode()).decode())
    except Exception:
        return {}


def fmt_ts(value) -> str:
    if not value:
        return "Unknown"
    try:
        return datetime.fromtimestamp(int(value), timezone.utc).strftime("%d-%b-%Y %I:%M %p UTC")
    except (ValueError, TypeError, OSError):
        return "Unknown"


def expiry_status(exp) -> str:
    try:
        seconds = int(exp) - int(datetime.now(timezone.utc).timestamp())
    except (ValueError, TypeError):
        return "Unknown expiry"
    if seconds <= 0:
        return "⚠️ EXPIRED"
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    mins = rem // 60
    if days:
        return f"🟢 Valid: {days}d {hours}h left"
    if hours:
        return f"🟡 Urgent: {hours}h {mins}m left"
    return f"🔴 Expiring soon: {mins}m left"


async def save_user(message: Message) -> None:
    if not message.from_user or db_pool is None:
        return
    u = message.from_user
    await db_pool.execute(
        """
        INSERT INTO telegram_users(user_id, username, first_name, created_at, last_seen)
        VALUES($1, $2, $3, NOW(), NOW())
        ON CONFLICT(user_id) DO UPDATE SET
            username=EXCLUDED.username, first_name=EXCLUDED.first_name, last_seen=NOW()
        """,
        u.id, u.username, u.first_name,
    )


async def require_admin(message: Message) -> bool:
    if not is_admin(message):
        await message.answer("⛔ Admin-only command. Set your Telegram numeric ID in ADMIN_IDS on Render.")
        return False
    return True


@dp.message(Command("start"))
async def start(message: Message):
    try:
        await save_user(message)
    except Exception:
        log.exception("Could not save Telegram user")
        await message.answer("⚠️ Database unavailable. Please try again later.")
        return
    await message.answer(
        "👋 Account & Token Manager\n\n"
        "/help — all commands\n"
        "/id — your Telegram ID\n"
        "/addtoken — securely save a JWT you are authorized to manage\n"
        "/accounts — saved account metadata\n"
        "/expiring — expired or soon-to-expire records\n"
        "/search <batch> — search saved batch names\n"
        "/status — admin status\n\n"
        "Tokens are encrypted in the database and never sent back in bot replies."
    )


@dp.message(Command("help"))
async def help_command(message: Message):
    await message.answer(
        "Commands:\n"
        "/start — register/update your user record\n"
        "/id — show Telegram numeric ID\n"
        "/addtoken — add an existing JWT you own/are authorized to manage\n"
        "/accounts — list saved account metadata\n"
        "/expiring — list records expiring within 48 hours or already expired\n"
        "/search <batch> — search batch names saved in account metadata\n"
        "/status — admin-only database status\n"
        "/delete <record_id> — delete one of your saved records\n\n"
        "OTP/password collection and automatic third-party OTP login are not enabled."
    )


@dp.message(Command("id"))
async def show_id(message: Message):
    if message.from_user:
        await message.answer(f"Your Telegram ID: {message.from_user.id}")


@dp.message(Command("login"))
async def login_disabled(message: Message):
    await message.answer(
        "For security, OTP/password collection is not enabled in this bot. "
        "Use the service's official login flow, then use /addtoken only for a token you are authorized to manage."
    )


@dp.message(Command("addtoken"))
async def add_token_init(message: Message, state: FSMContext):
    if not await require_admin(message):
        return
    await state.clear()
    await message.answer(
        "Send your JWT in your next message. Only add a token you own or are explicitly authorized to manage. "
        "I will attempt to delete your message after processing and will never echo the token."
    )
    await state.set_state(AddTokenFlow.waiting_for_token)


@dp.message(AddTokenFlow.waiting_for_token)
async def process_token(message: Message, state: FSMContext):
    if not await require_admin(message):
        await state.clear()
        return
    token = (message.text or "").strip()
    try:
        await message.delete()
    except Exception:
        pass

    claims = decode_jwt_payload(token)
    if not claims:
        await message.answer("❌ Invalid JWT format. No token was saved.")
        await state.clear()
        return

    now = int(datetime.now(timezone.utc).timestamp())
    exp = claims.get("exp")
    iat = claims.get("iat", now)
    name = str(claims.get("name") or "Unknown")[:200]
    mobile = str(claims.get("mobile") or "Unknown")[:40]
    org_code = str(claims.get("orgCode") or "Unknown")[:100]
    # JWT claims are untrusted until verified by the issuer; we only parse metadata.
    encrypted = cipher.encrypt(token.encode()).decode()
    try:
        record = await db_pool.fetchrow(
            """
            INSERT INTO managed_accounts(owner_telegram_id, name, mobile, org_code, encrypted_token,
                                          batches, issued_at, expires_at, created_at)
            VALUES($1,$2,$3,$4,$5,'',$6,$7,NOW())
            RETURNING id
            """,
            message.from_user.id, name, mobile, org_code, encrypted,
            int(iat) if str(iat).isdigit() else now,
            int(exp) if str(exp).isdigit() else None,
        )
    except Exception:
        log.exception("Could not save encrypted token")
        await message.answer("⚠️ Database save failed. The token was not saved.")
        await state.clear()
        return
    await state.clear()
    await message.answer(
        f"✅ Saved encrypted record #{record['id']}\n"
        f"Name: {name}\nMobile: {mobile}\nOrg: {org_code}\n"
        f"Issued: {fmt_ts(iat)}\nExpires: {fmt_ts(exp)}\n"
        f"Status: {expiry_status(exp)}\n\n"
        "Note: JWT format/claims were parsed only; token signature and live validity were not verified."
    )


@dp.message(Command("accounts"))
async def accounts(message: Message):
    if not await require_admin(message):
        return
    rows = await db_pool.fetch(
        """SELECT id,name,mobile,org_code,batches,issued_at,expires_at
           FROM managed_accounts ORDER BY expires_at NULLS LAST, id"""
    )
    if not rows:
        await message.answer("Database mein abhi koi saved account record nahi hai.")
        return
    lines = [f"📋 Saved records: {len(rows)}"]
    for row in rows[:40]:
        lines.append(
            f"\n#{row['id']} — {row['name']}\n"
            f"Mobile: {row['mobile']} | Org: {row['org_code']}\n"
            f"Expiry: {fmt_ts(row['expires_at'])} — {expiry_status(row['expires_at'])}\n"
            f"Batches: {row['batches'] or 'Not fetched'}"
        )
    if len(rows) > 40:
        lines.append(f"\nShowing 40 of {len(rows)} records.")
    await message.answer("\n".join(lines))


@dp.message(Command("expiring"))
async def expiring(message: Message):
    if not await require_admin(message):
        return
    threshold = int(datetime.now(timezone.utc).timestamp()) + 48 * 3600
    rows = await db_pool.fetch(
        """SELECT id,name,mobile,org_code,expires_at FROM managed_accounts
           WHERE expires_at IS NULL OR expires_at <= $1
           ORDER BY expires_at NULLS FIRST""",
        threshold,
    )
    if not rows:
        await message.answer("✅ Agle 48 hours mein koi saved record expire nahi ho raha.")
        return
    lines = [f"⚠️ Expired/expiring records: {len(rows)}"]
    for row in rows[:40]:
        lines.append(
            f"\n#{row['id']} — {row['name']} ({row['mobile']} | {row['org_code']})\n"
            f"{fmt_ts(row['expires_at'])} — {expiry_status(row['expires_at'])}"
        )
    await message.answer("\n".join(lines))


@dp.message(Command("search"))
async def search_batches(message: Message):
    if not await require_admin(message):
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await message.answer("Format: /search <batch_name>\nNote: batches are not auto-fetched in this safe starter.")
        return
    query = parts[1].strip()
    rows = await db_pool.fetch(
        """SELECT id,name,mobile,org_code,batches,expires_at FROM managed_accounts
           WHERE batches ILIKE $1 OR name ILIKE $1 OR org_code ILIKE $1
           ORDER BY expires_at NULLS LAST LIMIT 40""",
        f"%{query}%",
    )
    if not rows:
        await message.answer(f"❌ '{query}' ke liye koi matching saved record nahi mila.")
        return
    lines = [f"🔎 Results for: {query}"]
    for row in rows:
        lines.append(
            f"\n#{row['id']} — {row['name']} ({row['mobile']} | {row['org_code']})\n"
            f"Batches: {row['batches'] or 'Not fetched'}\nExpiry: {expiry_status(row['expires_at'])}"
        )
    await message.answer("\n".join(lines))


@dp.message(Command("delete"))
async def delete_record(message: Message):
    if not await require_admin(message):
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("Format: /delete <record_id>")
        return
    record_id = int(parts[1])
    result = await db_pool.execute("DELETE FROM managed_accounts WHERE id=$1", record_id)
    if result.endswith(" 1"):
        await message.answer(f"🗑️ Record #{record_id} deleted.")
    else:
        await message.answer("Record nahi mila.")


@dp.message(Command("status"))
async def status(message: Message):
    if not await require_admin(message):
        return
    try:
        users = await db_pool.fetchval("SELECT COUNT(*) FROM telegram_users")
        records = await db_pool.fetchval("SELECT COUNT(*) FROM managed_accounts")
        await message.answer(f"✅ Bot running\nPostgreSQL connected\nSaved Telegram users: {users}\nAccount records: {records}")
    except Exception:
        log.exception("Database status check failed")
        await message.answer("⚠️ Database check failed.")


async def health(request: web.Request) -> web.Response:
    try:
        await db_pool.fetchval("SELECT 1")
        return web.json_response({"status": "ok", "database": "connected"})
    except Exception:
        return web.json_response({"status": "degraded", "database": "unavailable"}, status=503)


async def start_http_server() -> web.AppRunner:
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    log.info("Health server listening on port %s", PORT)
    return runner


async def main():
    global db_pool
    db_pool = await asyncpg.create_pool(dsn=DATABASE_URL, ssl="require", min_size=1, max_size=5)
    try:
        async with db_pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS telegram_users (
                    user_id BIGINT PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS managed_accounts (
                    id BIGSERIAL PRIMARY KEY,
                    owner_telegram_id BIGINT NOT NULL,
                    name TEXT NOT NULL DEFAULT 'Unknown',
                    mobile TEXT NOT NULL DEFAULT 'Unknown',
                    org_code TEXT NOT NULL DEFAULT 'Unknown',
                    encrypted_token TEXT NOT NULL,
                    batches TEXT NOT NULL DEFAULT '',
                    issued_at BIGINT,
                    expires_at BIGINT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
        runner = await start_http_server()
        try:
            await dp.start_polling(bot)
        finally:
            await runner.cleanup()
    finally:
        if db_pool:
            await db_pool.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
