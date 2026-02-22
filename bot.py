"""
Telegram Bot + Google Gemini AI Integration
Hosted on Render.com
"""

import os
import logging
import asyncio
import tempfile
from pathlib import Path

from telegram import Update, Message
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from gemini_client import GeminiClient

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Environment variables (set these in Render dashboard)
# ---------------------------------------------------------------------------
TELEGRAM_BOT_TOKEN: str = os.environ["TELEGRAM_BOT_TOKEN"]
GEMINI_API_KEY: str = os.environ["GEMINI_API_KEY"]
GEMINI_MODEL: str = os.environ.get("GEMINI_MODEL", "gemini-1.5-flash")

# Optional: comma-separated list of allowed Telegram user IDs (leave blank to allow all)
ALLOWED_USER_IDS: set[int] = set()
_raw_ids = os.environ.get("ALLOWED_TELEGRAM_USER_IDS", "")
if _raw_ids.strip():
    ALLOWED_USER_IDS = {int(uid.strip()) for uid in _raw_ids.split(",") if uid.strip()}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def is_authorized(update: Update) -> bool:
    """Return True if the user is allowed to use the bot."""
    if not ALLOWED_USER_IDS:
        return True
    return update.effective_user.id in ALLOWED_USER_IDS


def split_long_message(text: str, max_length: int = 4096) -> list[str]:
    """Split a long message into chunks that fit Telegram's limit."""
    if len(text) <= max_length:
        return [text]
    chunks = []
    while text:
        chunks.append(text[:max_length])
        text = text[max_length:]
    return chunks


async def send_long_message(message: Message, text: str) -> None:
    """Send a potentially long message, splitting if necessary."""
    for chunk in split_long_message(text):
        await message.reply_text(chunk)


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    if not is_authorized(update):
        await update.message.reply_text("⛔ You are not authorized to use this bot.")
        return

    user = update.effective_user
    await update.message.reply_html(
        f"👋 Hello, <b>{user.first_name}</b>!\n\n"
        "I'm powered by <b>Google Gemini AI</b>. You can:\n\n"
        "• 💬 <b>Ask any question</b> — just type it\n"
        "• 📎 <b>Upload a file</b> (text, code, PDF, CSV, image…) and I'll analyse it for you\n"
        "• 🔄 /reset — start a fresh conversation\n"
        "• ℹ️ /help — show this message again\n\n"
        "Go ahead and ask me anything!"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command."""
    if not is_authorized(update):
        await update.message.reply_text("⛔ You are not authorized to use this bot.")
        return

    await update.message.reply_html(
        "<b>Gemini AI Telegram Bot — Help</b>\n\n"
        "<b>Commands:</b>\n"
        "/start — Welcome message\n"
        "/reset — Clear conversation history\n"
        "/help  — Show this help\n\n"
        "<b>How to use:</b>\n"
        "• Type any question and I'll answer using Google Gemini AI.\n"
        "• Send any file (document, photo, audio, etc.) optionally with a caption "
        "describing what you want to know about it.\n\n"
        "<b>Supported file types for analysis:</b>\n"
        "Text, code, CSV, JSON, PDF, Markdown, images (JPG, PNG, GIF, WebP), and more."
    )


async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /reset — clear conversation history for this user."""
    if not is_authorized(update):
        await update.message.reply_text("⛔ You are not authorized to use this bot.")
        return

    context.user_data.clear()
    await update.message.reply_text("🔄 Conversation history cleared. Let's start fresh!")


# ---------------------------------------------------------------------------
# Message handlers
# ---------------------------------------------------------------------------

async def handle_text_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle plain text messages — forward to Rovo Dev."""
    if not is_authorized(update):
        await update.message.reply_text("⛔ You are not authorized to use this bot.")
        return

    user_text = update.message.text.strip()
    if not user_text:
        return

    await update.message.chat.send_action("typing")

    # Maintain per-user conversation history
    history: list[dict] = context.user_data.setdefault("history", [])

    client: GeminiClient = context.bot_data["gemini_client"]
    try:
        reply, history = await client.chat(user_text, history)
        context.user_data["history"] = history
        await send_long_message(update.message, reply)
    except Exception as exc:
        logger.exception("Error calling Gemini API: %s", exc)
        await update.message.reply_text(
            f"❌ Error communicating with Gemini:\n<code>{exc}</code>",
            parse_mode="HTML",
        )


async def handle_file_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle file / photo uploads — extract text and forward to Rovo Dev."""
    if not is_authorized(update):
        await update.message.reply_text("⛔ You are not authorized to use this bot.")
        return

    message = update.message
    await message.chat.send_action("typing")

    # ---- Determine the file object ----
    file_obj = None
    file_name = "uploaded_file"
    mime_type = "application/octet-stream"

    if message.document:
        file_obj = message.document
        file_name = message.document.file_name or "document"
        mime_type = message.document.mime_type or mime_type
    elif message.photo:
        # Largest photo size
        file_obj = message.photo[-1]
        file_name = "photo.jpg"
        mime_type = "image/jpeg"
    elif message.audio:
        file_obj = message.audio
        file_name = message.audio.file_name or "audio"
        mime_type = message.audio.mime_type or mime_type
    elif message.video:
        file_obj = message.video
        file_name = message.video.file_name or "video"
        mime_type = message.video.mime_type or mime_type
    else:
        await message.reply_text("⚠️ Unsupported file type.")
        return

    caption = message.caption or ""

    # ---- Download the file ----
    try:
        tg_file = await file_obj.get_file()
        with tempfile.TemporaryDirectory() as tmpdir:
            local_path = Path(tmpdir) / file_name
            await tg_file.download_to_drive(str(local_path))
            file_content = local_path.read_bytes()
    except Exception as exc:
        logger.exception("Failed to download file: %s", exc)
        await message.reply_text(f"❌ Could not download the file: {exc}")
        return

    await message.reply_text(
        f"📂 Received <b>{file_name}</b> ({len(file_content):,} bytes). Analysing…",
        parse_mode="HTML",
    )
    await message.chat.send_action("typing")

    # ---- Build the prompt ----
    history: list[dict] = context.user_data.setdefault("history", [])
    client: GeminiClient = context.bot_data["gemini_client"]

    try:
        reply, history = await client.chat_with_file(
            user_message=caption or f"Please analyse the file: {file_name}",
            file_name=file_name,
            file_bytes=file_content,
            mime_type=mime_type,
            history=history,
        )
        context.user_data["history"] = history
        await send_long_message(message, reply)
    except Exception as exc:
        logger.exception("Error sending file to Gemini: %s", exc)
        await message.reply_text(
            f"❌ Error analysing file:\n<code>{exc}</code>",
            parse_mode="HTML",
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    """Entry point."""
    gemini_client = GeminiClient(
        api_key=GEMINI_API_KEY,
        model=GEMINI_MODEL,
    )

    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .build()
    )
    app.bot_data["gemini_client"] = gemini_client

    # Commands
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("reset", reset_command))

    # Text messages
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))

    # File / media messages
    file_filter = (
        filters.Document.ALL
        | filters.PHOTO
        | filters.AUDIO
        | filters.VIDEO
    )
    app.add_handler(MessageHandler(file_filter, handle_file_message))

    logger.info("Bot is running with polling…")

    # Use async context manager to avoid event loop conflicts on Python 3.14+
    async with app:
        await app.updater.start_polling(drop_pending_updates=True)
        await app.start()
        # Block forever until a stop signal is received
        await asyncio.Event().wait()
        await app.updater.stop()
        await app.stop()


if __name__ == "__main__":
    asyncio.run(main())
