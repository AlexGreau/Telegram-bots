from telegram import Update
from telegram.ext import CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler

valid_words = set()
SCRABBLE_MODE = 1


async def scrabble_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎯 Scrabble mode activated!\n"
        "Send me words to check, or /done to exit."
    )
    return SCRABBLE_MODE


async def checkWord(update: Update, context: ContextTypes.DEFAULT_TYPE):
    word = update.message.text.strip().lower()
    if word in valid_words:
        await update.message.reply_text(f"✓ '{word}' is a valid Scrabble word!")
    else:
        await update.message.reply_text(f"✗ '{word}' is not a valid Scrabble word.")
    return SCRABBLE_MODE


async def done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Exited Scrabble mode. Use /scrabble to start again!")
    return ConversationHandler.END


def loadWords():
    global valid_words
    try:
        with open("data/words.txt", "r") as f:
            valid_words = set(line.strip().lower() for line in f)
        print(f"Loaded {len(valid_words)} words from data/words.txt")
    except FileNotFoundError:
        print("Error: data/words.txt file not found.")


def register(app):
    loadWords()
    
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("scrabble", scrabble_start)],
        states={
            SCRABBLE_MODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, checkWord)],
        },
        fallbacks=[CommandHandler("done", done)],
    )
    
    app.add_handler(conv_handler)