"""
Telegram Video Link Bot (v2)
===========================
رفع سه باگ گزارش شده:
1. اگر کاربر روی «عضو شدم» بزند ولی هنوز عضو کانال نباشد، پیام «هنوز عضو نیستی!» در چت نمایش داده می‌شود.
2. پس از ارسال ویدیو، کپشن حاوی یادآوری «ذخیره کنید؛ پیام ۲۰ ثانیه بعد پاک می‌شود» افزوده شد.
3. حذف پیام بهبود یافت؛ خطا‌ها لاگ می‌شوند تا در صورت ناتوانیِ حذف دیده شود.

Python ≥ 3.13 و python‑telegram‑bot ≥ 21.3 توصیه می‌شود.

Before run (once):
    pip install "python-telegram-bot>=22.3" aiosqlite

Set env:
    export BOT_TOKEN="<YOUR_TOKEN>"
"""

import asyncio
import logging
import os
import secrets
import sqlite3
from contextlib import closing

# --- HOTFIX برای ptb ≤ 21.x روی Python 3.13 ---
try:
    from telegram.ext._updater import Updater as _PTB_Updater  # type: ignore
    if hasattr(_PTB_Updater, "__slots__") and "_Updater__polling_cleanup_cb" not in _PTB_Updater.__slots__:
        _PTB_Updater.__slots__ = _PTB_Updater.__slots__ + \
            ("_Updater__polling_cleanup_cb",)
except Exception:
    pass
# ------------------------------------------------

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

# ========================== CONFIG ==========================
BOT_TOKEN = os.getenv(
    "BOT_TOKEN", "8209783094:AAGuH5EQfJGu8h3kwK8LK1XeT-YjzHtQXk0")
ADMIN_IDS = {1381422763}
CHANNEL_USERNAME = "@UselessShitPosts"
BOT_USERNAME_FALLBACK = "YourBotUsername"
DATABASE_PATH = "links.db"

MSG_NEED_JOIN = (
    "برای دریافت ویدیو ابتدا عضو کانال زیر شوید و سپس روی دکمه «عضو شدم» بزنید."
)
MSG_NOT_MEMBER = "هنوز عضو کانال نیستی!"
MSG_INVALID_LINK = "پیوند نامعتبر یا منقضی است!"
MSG_SEND_VIDEO = "✅ لینک اختصاصی شما:\n{}"
MSG_NOT_VIDEO = "لطفاً یک فایل ویدیویی ارسال کنید."
SAVE_REMINDER = "ℹ️ لطفاً ویدیو را ذخیره کنید؛ این پیام ۲۰ ثانیه دیگر حذف می‌شود."
DELETE_AFTER = 20

# ======================== DATABASE =========================


def init_db():
    with closing(sqlite3.connect(DATABASE_PATH)) as conn, conn, closing(conn.cursor()) as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS links (
                token TEXT PRIMARY KEY,
                file_id TEXT NOT NULL
            )
            """
        )


def save_link(token: str, file_id: str):
    with closing(sqlite3.connect(DATABASE_PATH)) as conn, conn, closing(conn.cursor()) as cur:
        cur.execute(
            "INSERT OR REPLACE INTO links (token, file_id) VALUES (?, ?)", (token, file_id))


def fetch_file_id(token: str) -> str | None:
    with closing(sqlite3.connect(DATABASE_PATH)) as conn, closing(conn.cursor()) as cur:
        row = cur.execute(
            "SELECT file_id FROM links WHERE token = ?", (token,)).fetchone()
        return row[0] if row else None

# ========================= HANDLERS =========================


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text("سلام! برای دریافت ویدیو باید از لینک اختصاصی استفاده کنید.")
        return

    token = args[0]
    file_id = fetch_file_id(token)
    if not file_id:
        await update.message.reply_text(MSG_INVALID_LINK)
        return

    user_id = update.effective_user.id
    if await is_member(user_id, context):
        await send_video(update.message, context, file_id)
    else:
        buttons = [
            [InlineKeyboardButton(
                "🚀 عضویت در کانال", url=f"https://t.me/{CHANNEL_USERNAME.lstrip('@')}")],
            [InlineKeyboardButton(
                "✅ عضو شدم", callback_data=f"check|{token}")],
        ]
        await update.message.reply_text(
            MSG_NEED_JOIN, reply_markup=InlineKeyboardMarkup(buttons)
        )


async def check_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    _, token = query.data.split("|", 1)
    file_id = fetch_file_id(token)
    if not file_id:
        await query.edit_message_text(MSG_INVALID_LINK)
        return

    user_id = query.from_user.id
    if await is_member(user_id, context):
        await query.delete_message()
        await send_video(query, context, file_id)
    else:
        await query.message.reply_text(MSG_NOT_MEMBER)


async def video_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return

    video = update.message.video or update.message.document
    if not video or (video.mime_type and not video.mime_type.startswith("video")):
        await update.message.reply_text(MSG_NOT_VIDEO)
        return

    token = secrets.token_urlsafe(8)
    save_link(token, video.file_id)

    bot_username = context.bot.username or BOT_USERNAME_FALLBACK
    link = f"https://t.me/{bot_username}?start={token}"
    await update.message.reply_text(MSG_SEND_VIDEO.format(link))

# ------------------------ HELPERS ---------------------------


async def is_member(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        member = await context.bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return member.status in {
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
        }
    except Exception:
        return False


async def delete_after(bot, chat_id: int, message_id: int):
    """حذف پیام پس از DELAY ثانیه."""
    await asyncio.sleep(DELETE_AFTER)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception as e:
        logging.warning("Cannot delete message %s/%s: %s",
                        chat_id, message_id, e)


async def send_video(target, context: ContextTypes.DEFAULT_TYPE, file_id: str):
    """ارسال ویدیو + زمان‌بندی حذف با asyncio"""
    if hasattr(target, "reply_video"):
        sent = await target.reply_video(file_id, caption=SAVE_REMINDER)
    else:  # CallbackQuery
        sent = await target.message.reply_video(file_id, caption=SAVE_REMINDER)

    # حذف بعد از DELAY ثانیه
    asyncio.create_task(delete_after(
        context.bot, sent.chat_id, sent.message_id))

    # زمان‌بندی حذف با asyncio
    asyncio.create_task(delete_after(context.bot, sent.chat_id, sent)
                        )

# ========================= MAIN =============================


def main():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s - %(levelname)s - %(message)s")

    init_db()

    application = ApplicationBuilder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(
        filters.Document.VIDEO | filters.VIDEO, video_handler))
    application.add_handler(CallbackQueryHandler(
        check_callback, pattern=r"^check\|"))

    application.run_polling()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Bot stopped!")
