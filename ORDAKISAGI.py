"""
ORDAKISAGI – Telegram Video‑Link Bot (Webhook Edition)
=====================================================
  * ویژهٔ میزبانی **Web Service** رایگان روی Render
  * بدون نیاز به Background Worker؛ فقط یک وبهوک روی مسیری مثل `/webhook`
  * حداقل تغییر نسبت به نسخهٔ polling؛ تمام منطق لینک/عضویت همان است.

—— راه‌اندازی در Render ——
1. مخزن GitHub شامل این فایل + requirements.txt
2. Render → **New → Web Service** (Free)
3. ENV:
   - BOT_TOKEN
   - ADMIN_IDS (مثال `1381422763`)
   - CHANNEL_USERNAME (مثال `@UselessShitPosts`)
4. Start Command:
   ```bash
   python ORDAKISAGI.py
   ```
Render متغیّرهای `PORT` و `RENDER_EXTERNAL_URL` را تزریق می‌کند؛ ربات موقع اجرا وبهوک را روی `https://<app>.onrender.com/webhook` ثبت می‌کند.
"""

from __future__ import annotations
import asyncio
import logging
import os
import secrets
import sqlite3
from contextlib import closing

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatMemberStatus
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ===================== تنظیمات پایه =====================
BOT_TOKEN = os.getenv("BOT_TOKEN")  # حتماً در Render ست کنید
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN env var required!")

ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x}
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "@UselessShitPosts")
DATABASE_PATH = "links.db"

# مسیری که وبهوک گوش دهد
WEBHOOK_PATH = "/webhook"
SAVE_REMINDER = "ℹ️ لطفاً ویدیو را ذخیره کنید؛ این پیام ۲۰ ثانیه دیگر حذف می‌شود."
DELETE_AFTER = 20

# ====================== دیتابیس =========================


def init_db():
    with closing(sqlite3.connect(DATABASE_PATH)) as conn, conn, closing(conn.cursor()) as cur:
        cur.execute(
            """CREATE TABLE IF NOT EXISTS links (token TEXT PRIMARY KEY, file_id TEXT)"""
        )


def save_link(token: str, file_id: str):
    with closing(sqlite3.connect(DATABASE_PATH)) as conn, conn, closing(conn.cursor()) as cur:
        cur.execute("INSERT OR REPLACE INTO links VALUES (?, ?)",
                    (token, file_id))


def fetch_file_id(token: str) -> str | None:
    with closing(sqlite3.connect(DATABASE_PATH)) as conn, closing(conn.cursor()) as cur:
        row = cur.execute(
            "SELECT file_id FROM links WHERE token = ?", (token,)).fetchone()
        return row[0] if row else None

# ===================== هندلرها ==========================


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text("سلام! لینک اختصاصی خود را وارد کنید.")
        return
    token = args[0]
    file_id = fetch_file_id(token)
    if not file_id:
        await update.message.reply_text("پیوند نامعتبر یا منقضی است!")
        return
    uid = update.effective_user.id
    if await is_member(uid, context):
        await send_video(update.message, context, file_id)
    else:
        buttons = [
            [InlineKeyboardButton(
                "🚀 عضویت", url=f"https://t.me/{CHANNEL_USERNAME.lstrip('@')}")],
            [InlineKeyboardButton(
                "✅ عضو شدم", callback_data=f"check|{token}")],
        ]
        await update.message.reply_text(
            "برای دریافت ویدیو ابتدا عضو کانال شوید و سپس روی «عضو شدم» بزنید.",
            reply_markup=InlineKeyboardMarkup(buttons),
        )


async def check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    _, token = q.data.split("|", 1)
    file_id = fetch_file_id(token)
    if not file_id:
        await q.message.edit_text("پیوند نامعتبر یا منقضی است!")
        return
    if await is_member(q.from_user.id, context):
        try:
            await q.message.delete()
        except Exception:
            pass
        await send_video(q, context, file_id)
    else:
        await q.message.reply_text("هنوز عضو کانال نیستی!")


async def video_from_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    video = update.message.video or update.message.document
    if not video:
        return
    token = secrets.token_urlsafe(8)
    save_link(token, video.file_id)
    bot_username = context.bot.username
    link = f"https://t.me/{bot_username}?start={token}"
    await update.message.reply_text(f"✅ لینک اختصاصی شما:\n{link}")

# ---------------------- کمکى‌ها ------------------------


async def is_member(user_id: int, ctx: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        member = await ctx.bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return member.status in {
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
        }
    except Exception:
        return False


async def send_video(target, ctx: ContextTypes.DEFAULT_TYPE, file_id: str):
    sent = (await target.reply_video(file_id, caption=SAVE_REMINDER)) if hasattr(target, "reply_video") else (await target.message.reply_video(file_id, caption=SAVE_REMINDER))
    asyncio.create_task(delete_after(ctx.bot, sent.chat_id, sent.message_id))


async def delete_after(bot, chat_id: int, message_id: int):
    await asyncio.sleep(DELETE_AFTER)
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception as e:
        logging.warning("Cannot delete message %s/%s: %s",
                        chat_id, message_id, e)

# ===================== اجرای وبهوک =====================


def main():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    init_db()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.VIDEO |
                    filters.VIDEO, video_from_admin))
    app.add_handler(CallbackQueryHandler(check, pattern=r"^check|"))

    # -------- وبهوک --------
    port = int(os.getenv("PORT", "8000"))
    external = os.getenv("RENDER_EXTERNAL_URL")
    if not external:
        raise RuntimeError("RENDER_EXTERNAL_URL not set by Render!")
    webhook_url = external.rstrip("/") + WEBHOOK_PATH

    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        webhook_url=webhook_url,
        webhook_path=WEBHOOK_PATH,
    )


if __name__ == "__main__":
    main()
