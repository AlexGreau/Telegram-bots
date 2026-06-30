# sheets_client.py
import os
import secrets
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

def _get_client():
    creds = Credentials.from_service_account_file(
        os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON"), scopes=SCOPES
    )
    return gspread.authorize(creds)

def _get_swim_sheet():
    gc = _get_client()
    sh = gc.open_by_key(os.getenv("GOOGLE_SHEET_ID_SWIM"))
    year = str(datetime.now().year)
    return sh.worksheet(year)

def format_date_for_swim(iso_date: str) -> str:
    return datetime.strptime(iso_date, "%Y-%m-%d").strftime("%d/%m")

def format_swim_confirmation(date: str, distance: int, stats: dict) -> str:
    return (
        f"✅ Logged *{distance:,}m* on {date}\n"
        f"📊 Total: *{stats['total']:,}m* | Goal: *{stats['objective']:,}m*\n"
        f"📉 Remaining: *{stats['distance_to_goal']:,}m*\n"
        f"📅 Weeks left: *{stats['weeks_left']}*\n"
        f"🏃 Pace needed: *~{stats['weekly_pace']:,}m/week*"
    )

def log_swim(date: str, distance: int) -> dict:
    ws = _get_swim_sheet()
    next_row = len(ws.col_values(1)) + 1
    ws.update(f"A{next_row}:D{next_row}", [[date, "", distance, ""]])
    return get_swim_stats()

def get_swim_stats() -> dict:
    """Return total distance, objective, and distance to goal from sheet."""
    ws = _get_swim_sheet()

    objective = int(ws.acell("F3").value.replace(",", "").replace(" ", ""))
    distance_to_goal = int(ws.acell("G3").value.replace(",", "").replace(" ", ""))
    total = objective - distance_to_goal

    weeks_left = weeks_remaining_in_year()

    weekly_pace = round(distance_to_goal / weeks_left) if weeks_left > 0 else 0

    return {
        "total": total,
        "objective": objective,
        "distance_to_goal": distance_to_goal,
        "weeks_left": weeks_left,
        "weekly_pace": weekly_pace
    }

def _get_run_sheet():
    gc = _get_client()
    sh = gc.open_by_key(os.getenv("GOOGLE_SHEET_ID_RUN"))
    return sh.worksheet("history")

def format_date_for_run(iso_date: str) -> str:
    return datetime.strptime(iso_date, "%Y-%m-%d").strftime("%d%m%Y")

def log_run(date: str, distance_km: float, time: str) -> None:
    ws = _get_run_sheet()
    next_row = len(ws.col_values(1)) + 1
    ws.update(f"A{next_row}:C{next_row}", [[date, distance_km, time]])

def format_run_confirmation(date: str, distance_km: float, time: str) -> str:
    display_date = f"{date[:2]}/{date[2:4]}/{date[4:]}"
    return (
        f"✅ Logged *{distance_km}km* in *{time}* on {display_date}"
    )

def weeks_remaining_in_year() -> int:
    today = datetime.now()
    end_of_year = datetime(today.year, 12, 31)
    days_left = (end_of_year - today).days
    return days_left // 7


# --- Finance -----------------------------------------------------------------

def _get_finance_sheet():
    gc = _get_client()
    return gc.open_by_key(os.getenv("GOOGLE_SHEET_ID_FINANCE_SG"))


def _get_transactions_tab():
    return _get_finance_sheet().worksheet("transactions")


def _get_categories_tab():
    return _get_finance_sheet().worksheet("categories")


def _get_payment_methods_tab():
    return _get_finance_sheet().worksheet("payment_methods")


def get_categories() -> list[str]:
    ws = _get_categories_tab()
    return [v.strip() for v in ws.col_values(1) if v and v.strip()]


def add_category(name: str) -> None:
    ws = _get_categories_tab()
    next_row = len(ws.col_values(1)) + 1
    ws.update(f"A{next_row}", [[name]])


def get_payment_methods() -> list[str]:
    ws = _get_payment_methods_tab()
    return [v.strip() for v in ws.col_values(1) if v and v.strip()]


def add_payment_method(name: str) -> None:
    ws = _get_payment_methods_tab()
    next_row = len(ws.col_values(1)) + 1
    ws.update(f"A{next_row}", [[name]])


def get_known_tags() -> list[str]:
    ws = _get_transactions_tab()
    raw = ws.col_values(9)  # column I = tags (story order)
    if raw:
        raw = raw[1:]  # skip header
    seen: dict[str, str] = {}
    for cell in raw:
        for t in cell.split(","):
            t = t.strip()
            if t and t.lower() not in seen:
                seen[t.lower()] = t
    return sorted(seen.values())


def _generate_id() -> str:
    now = datetime.now()
    return f"{now.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(2)}"


def log_transaction(
    *,
    txn_type: str,
    amount: float,
    currency: str,
    amount_sgd: float,
    category: str,
    description: str,
    merchant: str = "",
    date: str,
    tags: str = "",
    payment_method: str = "",
    notes: str = "",
    recurring: bool = False,
    linked_id: str = "",
) -> dict:
    """Append a transaction row. Column order A..O:
    date | type | description | merchant | category | amount | currency | amount_sgd |
    tags | payment_method | notes | recurring | id | linked_id | logged_at
    """
    ws = _get_transactions_tab()
    txn_id = _generate_id()
    logged_at = datetime.now().isoformat(timespec="seconds")
    row = [
        date, txn_type, description, merchant, category,
        amount, currency, amount_sgd,
        tags, payment_method,
        notes,
        bool(recurring),
        txn_id,
        linked_id,
        logged_at,
    ]
    next_row = len(ws.col_values(1)) + 1
    ws.update(f"A{next_row}:O{next_row}", [row])
    return {"id": txn_id, "logged_at": logged_at}


def get_all_transactions() -> list[dict]:
    """Read all rows from the transactions tab as dicts keyed by header.

    Coerces numeric (amount, amount_sgd) to float, recurring to bool, linked_id to str.
    """
    ws = _get_transactions_tab()
    records = ws.get_all_records()
    for r in records:
        for k in ("amount", "amount_sgd"):
            try:
                r[k] = float(r.get(k, 0) or 0)
            except (TypeError, ValueError):
                r[k] = 0.0
        v = r.get("recurring")
        r["recurring"] = v is True or (isinstance(v, str) and v.strip().lower() in {"true", "yes", "y", "1"})
        r["linked_id"] = str(r.get("linked_id") or "").strip()
    return records


def format_transaction_confirmation(pending: dict) -> str:
    emoji = "💸" if pending["txn_type"] == "expense" else "💰"
    base = pending.get("base_currency", "SGD")
    amt = f"{pending['amount']:,.2f} {pending['currency']}"
    if pending["currency"] != base:
        amt += f" (~{pending['amount_sgd']:,.2f} {base})"
    line = f"{emoji} *{amt}* — {pending['description']}"
    if pending.get("merchant"):
        line += f" @ {pending['merchant']}"
    line += f"\n   {pending['category']} · {pending['date']}"
    if pending.get("tags"):
        line += f" · tags: {pending['tags']}"
    if pending.get("payment_method"):
        line += f" · {pending['payment_method']}"
    if pending.get("notes"):
        line += f"\n   📝 {pending['notes']}"
    badges = []
    if pending.get("recurring"):
        badges.append("🔁 recurring")
    if pending.get("linked_id"):
        badges.append(f"🔗 linked: {pending['linked_id']}")
    if badges:
        line += "\n   " + " · ".join(badges)
    if pending.get("new_category"):
        line += f"\n   ⚠️ New category will be created: '{pending['new_category']}'"
    if pending.get("new_payment_method"):
        line += f"\n   ⚠️ New payment method will be created: '{pending['new_payment_method']}'"
    return line