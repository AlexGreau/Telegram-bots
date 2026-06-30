from datetime import date

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

from config import Config
from handlers.assist_services.finance_report import (
    build_report,
    format_report,
    resolve_period,
)
from handlers.assist_services.sheets_client import get_all_transactions, get_budgets


async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in Config.ASSIST_ALLOWED_IDS:
        await update.message.reply_text("Sorry, you are not authorized to use this command.")
        return

    arg = " ".join(context.args).strip()
    try:
        period = resolve_period(arg, date.today())
    except ValueError as e:
        await update.message.reply_text(str(e))
        return

    try:
        rows = get_all_transactions()
        budgets = get_budgets()
    except Exception as e:
        await update.message.reply_text(f"Couldn't read the finance sheet: {e}")
        return

    report = build_report(rows, period, budgets)
    await update.message.reply_text(format_report(report), parse_mode="Markdown")


def register(app):
    app.add_handler(CommandHandler("report", report_command))
