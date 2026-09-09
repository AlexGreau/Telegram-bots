import anthropic
from datetime import date as date_today
from pathlib import Path
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler, CallbackQueryHandler

from config import Config
from handlers.assist_services.sheets_client import (
    get_categories,
    get_payment_methods,
    get_known_tags,
)
from handlers.assist_services.skills import (
    ALL_TOOLS,
    build_skill_instructions,
    commit_pending,
    dispatch_tool,
    preview_pending,
)

AWAIT_PROMPT = 1
_PENDING_PLACEHOLDER = "Confirmation preview shown to the user. Outcome will follow."

_FINANCE_GUIDE = (Path(__file__).parent.parent / "docs" / "finance.md").read_text(encoding="utf-8")


def _patch_pending_outcomes(history: list, outcomes: dict[str, str]) -> None:
    """Update tool_result blocks in saved history with actual Confirm/Cancel outcomes."""
    if not outcomes:
        return
    for msg in history:
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") != "tool_result":
                continue
            tid = block.get("tool_use_id")
            if tid in outcomes:
                block["content"] = outcomes[tid]


def _build_system_prompt(
    known_categories: list[str],
    known_tags: list[str],
    known_payment_methods: list[str],
    base_currency: str,
) -> str:
    today = date_today.today().isoformat()
    ctx = {
        "today": today,
        "base_currency": base_currency,
        "known_categories": known_categories,
        "known_tags": known_tags,
        "known_payment_methods": known_payment_methods,
    }
    preamble = (
        f"Today's date is {today}. "
        "You are a helpful AI assistant integrated into a Telegram bot. "
        "Answer questions clearly and concisely. "
        "When the user gives a relative date (e.g. 'yesterday', '2 days ago', 'last Monday'), "
        f"resolve it to an absolute ISO date using today ({today}) as the reference. "
        "If the user mentions multiple activities in one message, call all the relevant tools together in a single response. "
    )
    closing = "Always respond in plain text without any markdown formatting."
    return preamble + build_skill_instructions(ctx) + closing


async def assist_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in Config.ASSIST_ALLOWED_IDS:
        await update.message.reply_text("Sorry, you are not authorized to use this command.")
        return ConversationHandler.END

    try:
        context.user_data["known_categories"] = get_categories()
    except Exception:
        context.user_data["known_categories"] = []
    try:
        context.user_data["known_payment_methods"] = get_payment_methods()
    except Exception:
        context.user_data["known_payment_methods"] = []
    try:
        context.user_data["known_tags"] = get_known_tags()
    except Exception:
        context.user_data["known_tags"] = []
    context.user_data["base_currency"] = Config.DEFAULT_CURRENCY

    await update.message.reply_text("What would you like help with?")
    return AWAIT_PROMPT


async def assist_respond(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        client = anthropic.AsyncAnthropic(api_key=Config.ANTHROPIC_API_KEY)
        messages = context.user_data.get("assist_history", [])
        messages.append({"role": "user", "content": update.message.text})

        system_text = _build_system_prompt(
            context.user_data.get("known_categories", []),
            context.user_data.get("known_tags", []),
            context.user_data.get("known_payment_methods", []),
            context.user_data.get("base_currency", "SGD"),
        )

        while True:
            response = await client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                system=[
                    {
                        "type": "text",
                        "text": (
                            "The following is the canonical user-facing guide for the finance "
                            "feature of this bot. Use it to answer the user's questions about how "
                            "the feature works, what tags vs categories are for, how to log "
                            "reimbursements, etc. Do not quote the markdown verbatim — paraphrase "
                            "in plain text.\n\n"
                            + _FINANCE_GUIDE
                        ),
                        "cache_control": {"type": "ephemeral"},
                    },
                    {
                        "type": "text",
                        "text": system_text,
                        "cache_control": {"type": "ephemeral"},
                    },
                ],
                tools=ALL_TOOLS,
                messages=messages,
            )

            tool_blocks = [b for b in response.content if b.type == "tool_use"]

            if not tool_blocks:
                reply = next((b.text for b in response.content if b.type == "text"), "No response generated.")
                messages.append({"role": "assistant", "content": reply})
                context.user_data["assist_history"] = messages
                await update.message.reply_text(reply)
                break

            pending_items = []
            tool_results = []
            for tb in tool_blocks:
                tool_result, pending = await dispatch_tool(tb.name, tb.input, context)
                if pending:
                    pending["tool_use_id"] = tb.id
                    pending_items.append(pending)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tb.id,
                    "content": tool_result,
                })

            if pending_items:
                pending_ids = {p["tool_use_id"] for p in pending_items}
                persisted_results = [
                    {**tr, "content": _PENDING_PLACEHOLDER} if tr["tool_use_id"] in pending_ids else tr
                    for tr in tool_results
                ]
                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": persisted_results})
                context.user_data["assist_history"] = messages

                context.user_data["pending_activities"] = pending_items
                lines = [preview_pending(item) for item in pending_items]
                preview = "About to log:\n" + "\n".join(lines)
                keyboard = InlineKeyboardMarkup([[
                    InlineKeyboardButton("✅ Confirm", callback_data="multi_confirm"),
                    InlineKeyboardButton("❌ Cancel", callback_data="activity_cancel"),
                ]])
                await update.message.reply_text(preview, parse_mode="Markdown", reply_markup=keyboard)
                break

            messages.append({"role": "assistant", "content": response.content})
            messages.append({
                "role": "user",
                "content": tool_results,
            })

    except anthropic.AuthenticationError:
        await update.message.reply_text("Error: Invalid Anthropic API key. Check ANTHROPIC_API_KEY in .env")
    except anthropic.APIConnectionError:
        await update.message.reply_text("Error: Could not reach the Claude API. Check your internet connection.")
    except Exception as e:
        await update.message.reply_text(f"Something went wrong: {e}")
    return AWAIT_PROMPT


async def activity_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    items = context.user_data.pop("pending_activities", [])
    history = context.user_data.get("assist_history", [])

    if query.data == "activity_cancel":
        outcomes = {
            item["tool_use_id"]: "User cancelled. Nothing was logged."
            for item in items if item.get("tool_use_id")
        }
        _patch_pending_outcomes(history, outcomes)
        if outcomes:
            history.append({"role": "assistant", "content": "Cancelled."})
        context.user_data["assist_history"] = history
        await query.edit_message_text("❌ Cancelled.")
        return

    outcomes: dict[str, str] = {}
    confirmations = []
    for item in items:
        tid = item.get("tool_use_id")
        try:
            confirmation, outcome = commit_pending(item, context)
            confirmations.append(confirmation)
            if tid:
                outcomes[tid] = outcome
        except Exception as e:
            confirmations.append(f"❌ Failed to log entry: {e}")
            if tid:
                outcomes[tid] = f"User confirmed but logging failed: {e}"
    _patch_pending_outcomes(history, outcomes)
    if outcomes:
        history.append({"role": "assistant", "content": "\n\n".join(confirmations)})
    context.user_data["assist_history"] = history
    await query.edit_message_text("\n\n".join(confirmations), parse_mode="Markdown")


async def done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("assist_history", None)
    await update.message.reply_text("Conversation ended. Use /assist to start a new one.")
    return ConversationHandler.END


async def timed_out(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("assist_history", None)
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Session timed out after 30 minutes of inactivity. Use /assist to start a new one.",
    )
    return ConversationHandler.END


def register(app):
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("assist", assist_start)],
        states={
            AWAIT_PROMPT: [MessageHandler(filters.TEXT & ~filters.COMMAND, assist_respond)],
            ConversationHandler.TIMEOUT: [MessageHandler(filters.ALL, timed_out)],
        },
        fallbacks=[CommandHandler("done", done)],
        conversation_timeout=1800,
    ))
    app.add_handler(CallbackQueryHandler(activity_callback, pattern="^(?:multi_confirm|activity_cancel)$"))
