import anthropic
from telegram import Update
from telegram.ext import CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler

from config import Config

AWAIT_PROMPT = 1

_SYSTEM_PROMPT = (
    "You are a helpful AI assistant integrated into a Telegram bot. "
    "Answer questions clearly and concisely."
)


async def assist_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in Config.ASSIST_ALLOWED_IDS:
        await update.message.reply_text("Sorry, you are not authorized to use this command.")
        return ConversationHandler.END

    await update.message.reply_text("What would you like help with?")
    return AWAIT_PROMPT


async def assist_respond(update: Update, context: ContextTypes.DEFAULT_TYPE):
    client = anthropic.AsyncAnthropic(api_key=Config.ANTHROPIC_API_KEY)

    response = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=[{
            "type": "text",
            "text": _SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{"role": "user", "content": update.message.text}],
    )

    reply = next((b.text for b in response.content if b.type == "text"), "No response generated.")
    await update.message.reply_text(reply)
    return ConversationHandler.END


async def done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelled. Use /help for available commands.")
    return ConversationHandler.END


def register(app):
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("assist", assist_start)],
        states={
            AWAIT_PROMPT: [MessageHandler(filters.TEXT & ~filters.COMMAND, assist_respond)],
        },
        fallbacks=[CommandHandler("done", done)],
    )
    app.add_handler(conv_handler)
