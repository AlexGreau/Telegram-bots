import anthropic
from datetime import date as date_today
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler, CallbackQueryHandler

from config import Config
from handlers.assist_services.sheets_client import (
    format_date_for_swim,
    format_swim_confirmation,
    log_swim as _log_swim,
    format_date_for_run,
    format_run_confirmation,
    log_run as _log_run,
)
from handlers.assist_services.flashcard_tools import FLASHCARD_TOOLS, execute_flashcard_tool

AWAIT_PROMPT = 1

_SYSTEM_PROMPT = (
    "You are a helpful AI assistant integrated into a Telegram bot. "
    "Answer questions clearly and concisely. "
    "You can log swim and run sessions when the user mentions them. "
    "You can manage a language flashcard deck: add new words, run quiz sessions, and show stats. "
    "When quizzing, work through all due cards one at a time, vary how you ask each question, "
    "grade generously for minor typos, and call update_flashcard after every answer. "
    "Always respond in plain text without any markdown formatting."
)

_TOOLS = [
    *FLASHCARD_TOOLS,
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
    },
    {
        "name": "log_run",
        "description": "Log a run session to the tracking sheet. Use when the user mentions running a distance.",
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "ISO date (YYYY-MM-DD). Omit if the user means today.",
                },
                "distance_km": {
                    "type": "number",
                    "description": "Distance run in kilometers.",
                },
                "time": {
                    "type": "string",
                    "description": "Duration in HH:MM:SS,ms format e.g. 45:00,00.",
                },
            },
            "required": ["distance_km", "time"],
        },
    },
]


async def _execute_tool(name: str, inputs: dict) -> tuple[str, dict | None]:
    """Returns (tool_result_for_claude, pending_data | None)."""
    if name in {"add_flashcard", "get_due_cards", "update_flashcard", "get_flashcard_stats"}:
        return execute_flashcard_tool(name, inputs), None
    if name == "log_swim":
        iso_date = inputs.get("date") or date_today.today().isoformat()
        formatted = format_date_for_swim(iso_date)
        distance = inputs["distance"]
        return "pending_confirmation", {"type": "swim", "date": formatted, "distance": distance}
    if name == "log_run":
        iso_date = inputs.get("date") or date_today.today().isoformat()
        formatted = format_date_for_run(iso_date)
        return "pending_confirmation", {"type": "run", "date": formatted, "distance_km": inputs["distance_km"], "time": inputs["time"]}
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
        messages = context.user_data.get("assist_history", [])
        messages.append({"role": "user", "content": update.message.text})

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
                messages.append({"role": "assistant", "content": reply})
                context.user_data["assist_history"] = messages
                await update.message.reply_text(reply)
                break

            tool_result, pending = await _execute_tool(tool_block.name, tool_block.input)

            if pending:
                if pending["type"] == "swim":
                    preview = f"🏊 About to log *{pending['distance']:,}m* on {pending['date']}"
                    confirm_data = f"swim_confirm:{pending['date']}:{pending['distance']}"
                else:
                    display_date = f"{pending['date'][:2]}/{pending['date'][2:4]}/{pending['date'][4:]}"
                    preview = f"🏃 About to log *{pending['distance_km']}km* in *{pending['time']}* on {display_date}"
                    confirm_data = f"run_confirm;{pending['date']};{pending['distance_km']};{pending['time']}"
                keyboard = InlineKeyboardMarkup([[
                    InlineKeyboardButton("✅ Confirm", callback_data=confirm_data),
                    InlineKeyboardButton("❌ Cancel", callback_data="activity_cancel"),
                ]])
                await update.message.reply_text(preview, parse_mode="Markdown", reply_markup=keyboard)
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
    return AWAIT_PROMPT


async def swim_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data.startswith("swim_confirm:"):
        _, date, distance = query.data.split(":")
        try:
            stats = _log_swim(date, int(distance))
            msg = format_swim_confirmation(date, int(distance), stats)
            await query.edit_message_text(msg, parse_mode="Markdown")
        except Exception as e:
            await query.edit_message_text(f"❌ Failed to log: {e}")

    elif query.data.startswith("run_confirm;"):
        _, date, distance_km, time = query.data.split(";")
        try:
            _log_run(date, float(distance_km), time)
            msg = format_run_confirmation(date, float(distance_km), time)
            await query.edit_message_text(msg, parse_mode="Markdown")
        except Exception as e:
            await query.edit_message_text(f"❌ Failed to log: {e}")

    elif query.data == "activity_cancel":
        await query.edit_message_text("❌ Cancelled.")


async def done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("assist_history", None)
    await update.message.reply_text("Conversation ended. Use /assist to start a new one.")
    return ConversationHandler.END


def register(app):
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("assist", assist_start)],
        states={
            AWAIT_PROMPT: [MessageHandler(filters.TEXT & ~filters.COMMAND, assist_respond)],
        },
        fallbacks=[CommandHandler("done", done)],
    ))
    app.add_handler(CallbackQueryHandler(swim_callback, pattern="^(?:swim_confirm:|run_confirm;|activity_cancel$)"))
