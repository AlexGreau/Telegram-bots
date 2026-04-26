import anthropic
from datetime import date as date_today
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler, CallbackQueryHandler

from config import Config
from handlers.assist_services.sheets_client import (
    format_date_for_swim,
    format_swim_confirmation,
    log_swim as _log_swim,
)

AWAIT_PROMPT = 1

_SYSTEM_PROMPT = (
    "You are a helpful AI assistant integrated into a Telegram bot. "
    "Answer questions clearly and concisely. "
    "You can log swim sessions when the user mentions swimming a distance. "
    "Always respond in plain text without any markdown formatting."
)

_TOOLS = [
    {
        "name": "log_swim",
        "description": "Log a swim session to the tracking sheet. Use when the user mentions swimming a distance.",
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "ISO date (YYYY-MM-DD). Omit if the user means today.",
                },
                "distance": {
                    "type": "integer",
                    "description": "Distance swum in meters.",
                },
            },
            "required": ["distance"],
        },
    }
]


async def _execute_tool(name: str, inputs: dict) -> tuple[str, dict | None]:
    """Returns (tool_result_for_claude, pending_data | None)."""
    if name == "log_swim":
        iso_date = inputs.get("date") or date_today.today().isoformat()
        formatted = format_date_for_swim(iso_date)
        distance = inputs["distance"]
        return "pending_confirmation", {"date": formatted, "distance": distance}
    return f"Unknown tool: {name}", None


async def assist_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in Config.ASSIST_ALLOWED_IDS:
        await update.message.reply_text("Sorry, you are not authorized to use this command.")
        return ConversationHandler.END

    await update.message.reply_text("What would you like help with?")
    return AWAIT_PROMPT


async def assist_respond(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        client = anthropic.AsyncAnthropic(api_key=Config.ANTHROPIC_API_KEY)
        messages = [{"role": "user", "content": update.message.text}]

        while True:
            response = await client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                system=[{
                    "type": "text",
                    "text": _SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }],
                tools=_TOOLS,
                messages=messages,
            )

            tool_block = next((b for b in response.content if b.type == "tool_use"), None)

            if tool_block is None:
                reply = next((b.text for b in response.content if b.type == "text"), "No response generated.")
                await update.message.reply_text(reply)
                break

            tool_result, pending = await _execute_tool(tool_block.name, tool_block.input)

            if pending:
                context.user_data["pending_swim"] = pending
                keyboard = InlineKeyboardMarkup([[
                    InlineKeyboardButton("✅ Confirm", callback_data="swim_confirm"),
                    InlineKeyboardButton("❌ Cancel", callback_data="swim_cancel"),
                ]])
                await update.message.reply_text(
                    f"🏊 About to log *{pending['distance']:,}m* on {pending['date']}",
                    parse_mode="Markdown",
                    reply_markup=keyboard,
                )
                break

            messages.append({"role": "assistant", "content": response.content})
            messages.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": tool_block.id,
                    "content": tool_result,
                }],
            })

    except anthropic.AuthenticationError:
        await update.message.reply_text("Error: Invalid Anthropic API key. Check ANTHROPIC_API_KEY in .env")
    except anthropic.APIConnectionError:
        await update.message.reply_text("Error: Could not reach the Claude API. Check your internet connection.")
    except Exception as e:
        await update.message.reply_text(f"Something went wrong: {e}")
    return ConversationHandler.END


async def swim_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "swim_confirm":
        pending = context.user_data.pop("pending_swim", None)
        if not pending:
            await query.edit_message_text("Session expired, please try again.")
            return
        stats = _log_swim(pending["date"], pending["distance"])
        msg = format_swim_confirmation(pending["date"], pending["distance"], stats)
        await query.edit_message_text(msg, parse_mode="Markdown")

    elif query.data == "swim_cancel":
        context.user_data.pop("pending_swim", None)
        await query.edit_message_text("❌ Cancelled.")


async def done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelled. Use /help for available commands.")
    return ConversationHandler.END


def register(app):
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("assist", assist_start)],
        states={
            AWAIT_PROMPT: [MessageHandler(filters.TEXT & ~filters.COMMAND, assist_respond)],
        },
        fallbacks=[CommandHandler("done", done)],
    ))
    app.add_handler(CallbackQueryHandler(swim_callback, pattern="^swim_"))
