# sheets_client.py
import os
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
    """
    Append a new swim session row.
    date should be in DD/MM format — sheet handles weeknum and totals.
    """
    ws = _get_swim_sheet()
    ws.append_row([date, "", distance, ""])  # weeknum and total auto-calculated by sheet
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

def weeks_remaining_in_year() -> int:
    today = datetime.now()
    end_of_year = datetime(today.year, 12, 31)
    days_left = (end_of_year - today).days
    return days_left // 7