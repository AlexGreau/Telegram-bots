from telegram import Update
from telegram.ext import CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler

HELLO_MODE = 1


async def hello_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Hello mode activated!\n"
        "I'll echo everything you say. Send /done to exit."
    )
    return HELLO_MODE


async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"You said: {update.message.text}")
    return HELLO_MODE


async def done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Exited Hello mode. Use /hello to start again!")
    return ConversationHandler.END


def register(app):
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("hello", hello_start)],
        states={
            HELLO_MODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, echo)],
        },
        fallbacks=[CommandHandler("done", done)],
    )
    
    app.add_handler(conv_handler)