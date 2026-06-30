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
    get_categories,
    add_category,
    get_payment_methods,
    add_payment_method,
    get_known_tags,
    log_transaction as _log_transaction,
    format_transaction_confirmation,
)
from handlers.assist_services.flashcard_tools import FLASHCARD_TOOLS, execute_flashcard_tool
from handlers.assist_services.finance_tools import FINANCE_TOOLS, execute_finance_tool, LOG_TRANSACTION

AWAIT_PROMPT = 1
_PENDING_PLACEHOLDER = "Confirmation preview shown to the user. Outcome will follow."


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
    cats = ", ".join(known_categories) if known_categories else "(none yet)"
    tags = ", ".join(known_tags) if known_tags else "(none yet)"
    pms = ", ".join(known_payment_methods) if known_payment_methods else "(none yet)"
    return (
        f"Today's date is {today}. "
        "You are a helpful AI assistant integrated into a Telegram bot. "
        "Answer questions clearly and concisely. "
        "You can log swim and run sessions when the user mentions them. "
        "When the user gives a relative date (e.g. 'yesterday', '2 days ago', 'last Monday'), "
        f"resolve it to an absolute ISO date using today ({today}) as the reference. "
        "If the user mentions multiple activities in one message, call all the relevant tools together in a single response. "
        "You can manage a language flashcard deck: add new words, run quiz sessions, and show stats. "
        "When quizzing, work through all due cards one at a time, vary how you ask each question, "
        "grade generously for minor typos, and call update_flashcard after every answer. "
        "You can log personal finance transactions (expenses and income) via log_transaction. "
        f"Base currency is {base_currency}. "
        f"Known categories: {cats}. "
        "Prefer a category from this list when one fits. If none fits, propose a new short "
        "Title-Case category name — the user will confirm before it is added. "
        f"Known payment methods: {pms}. "
        "When a payment method is mentioned, prefer one from this list. If none fits, propose a "
        "new short Title-Case name — the user will confirm before it is added. Omit "
        "payment_method entirely if the user didn't mention how they paid. "
        f"Known tags so far: {tags}. "
        "When tagging, reuse an existing tag if it captures the same concept (e.g. don't introduce "
        "'japan_trip' if 'japan-trip' already exists). Only invent a new tag when nothing fits. "
        "Tags are not confirmed by the user, so apply the principle yourself. "
        "If the user spends in a non-base currency without giving the converted amount, do NOT "
        "guess an FX rate; call log_transaction without amount_sgd and the tool will instruct "
        "you to ask the user. "
        "Set log_transaction's `recurring=true` only when the user explicitly mentions the "
        "transaction recurs (Netflix, rent, phone bill, utilities, salary). Leave it false otherwise. "
        "To link a transaction to another (refund of a purchase, reimbursement of an expense), "
        "pass `linked_id` as the id of the related row. The user can give you the id directly, "
        "or you can ask them to paste it. NEVER invent or guess an id. "
        "Always respond in plain text without any markdown formatting."
    )

_TOOLS = [
    *FLASHCARD_TOOLS,
    *FINANCE_TOOLS,
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


async def _execute_tool(name: str, inputs: dict, context: ContextTypes.DEFAULT_TYPE) -> tuple[str, dict | None]:
    """Returns (tool_result_for_claude, pending_data | None)."""
    if name in {"add_flashcard", "get_due_cards", "update_flashcard", "get_flashcard_stats"}:
        return execute_flashcard_tool(name, inputs), None
    if name == LOG_TRANSACTION:
        known_cats = context.user_data.get("known_categories", [])
        known_pms = context.user_data.get("known_payment_methods", [])
        return execute_finance_tool(name, inputs, known_cats, known_pms)
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
                system=[{
                    "type": "text",
                    "text": system_text,
                    "cache_control": {"type": "ephemeral"},
                }],
                tools=_TOOLS,
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
                tool_result, pending = await _execute_tool(tb.name, tb.input, context)
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
                lines = []
                for item in pending_items:
                    if item.get("kind") == "transaction":
                        lines.append(format_transaction_confirmation(item))
                    elif item["type"] == "swim":
                        lines.append(f"🏊 *{item['distance']:,}m* on {item['date']}")
                    else:
                        d = item["date"]
                        display = f"{d[:2]}/{d[2:4]}/{d[4:]}"
                        lines.append(f"🏃 *{item['distance_km']}km* in {item['time']} on {display}")
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
            if item.get("kind") == "transaction":
                if item.get("new_category"):
                    add_category(item["new_category"])
                    cats = context.user_data.get("known_categories", [])
                    if item["new_category"] not in cats:
                        cats.append(item["new_category"])
                        context.user_data["known_categories"] = cats
                if item.get("new_payment_method"):
                    add_payment_method(item["new_payment_method"])
                    pms = context.user_data.get("known_payment_methods", [])
                    if item["new_payment_method"] not in pms:
                        pms.append(item["new_payment_method"])
                        context.user_data["known_payment_methods"] = pms
                if item.get("tags"):
                    existing = context.user_data.get("known_tags", [])
                    existing_lower = {t.lower() for t in existing}
                    for t in (s.strip() for s in item["tags"].split(",")):
                        if t and t.lower() not in existing_lower:
                            existing.append(t)
                            existing_lower.add(t.lower())
                    context.user_data["known_tags"] = existing
                _log_transaction(
                    txn_type=item["txn_type"],
                    amount=item["amount"],
                    currency=item["currency"],
                    amount_sgd=item["amount_sgd"],
                    category=item["category"],
                    description=item["description"],
                    merchant=item.get("merchant", ""),
                    date=item["date"],
                    tags=item["tags"],
                    payment_method=item["payment_method"],
                    notes=item["notes"],
                    recurring=item.get("recurring", False),
                    linked_id=item.get("linked_id", ""),
                )
                confirmations.append("✅ Logged:\n" + format_transaction_confirmation(item))
                if tid:
                    extras = ""
                    if item.get("recurring"):
                        extras += " [recurring]"
                    if item.get("linked_id"):
                        extras += f" [linked_id={item['linked_id']}]"
                    outcomes[tid] = (
                        f"User confirmed. Transaction logged: {item['txn_type']} "
                        f"{item['amount']} {item['currency']} ({item['category']}) — "
                        f"{item['description']} on {item['date']}.{extras}"
                    )
            elif item["type"] == "swim":
                stats = _log_swim(item["date"], item["distance"])
                confirmations.append(format_swim_confirmation(item["date"], item["distance"], stats))
                if tid:
                    outcomes[tid] = f"User confirmed. Swim of {item['distance']}m logged on {item['date']}."
            else:
                _log_run(item["date"], item["distance_km"], item["time"])
                confirmations.append(format_run_confirmation(item["date"], item["distance_km"], item["time"]))
                if tid:
                    outcomes[tid] = (
                        f"User confirmed. Run of {item['distance_km']}km in {item['time']} "
                        f"logged on {item['date']}."
                    )
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
