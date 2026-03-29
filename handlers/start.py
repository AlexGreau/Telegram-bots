from telegram import Update
from telegram.ext import CommandHandler, ContextTypes


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 Welcome to Alex's Raspberry Pi Bot!\n\n"
        "Available Commands:\n"
        "/hello - Enter echo mode (repeats what you say)\n"
        "/scrabble - Enter Scrabble checker mode\n"
        "/done - Exit current mode\n"
        "/help - Show this message again"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Available Commands:\n"
        "/hello - Enter echo mode (repeats what you say)\n"
        "/scrabble - Enter Scrabble checker mode\n"
        "/done - Exit current mode\n"
        "/help - Show this message"
    )


def register(app):
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))