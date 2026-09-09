"""Fitness-logging capability inside the /assist agent loop.

Log swim and run sessions to the tracking sheet. Both go through a Confirm/Cancel
step, so this skill provides preview + commit.
"""
from datetime import date as date_today

from handlers.assist_services.sheets_client import (
    format_date_for_run,
    format_date_for_swim,
    format_run_confirmation,
    format_swim_confirmation,
    log_run as _log_run,
    log_swim as _log_swim,
)
from handlers.assist_services.skills.base import Skill

FITNESS_TOOLS = [
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


async def _execute(name: str, inputs: dict, context) -> tuple[str, dict | None]:
    if name == "log_swim":
        iso_date = inputs.get("date") or date_today.today().isoformat()
        formatted = format_date_for_swim(iso_date)
        return "pending_confirmation", {"type": "swim", "date": formatted, "distance": inputs["distance"]}
    if name == "log_run":
        iso_date = inputs.get("date") or date_today.today().isoformat()
        formatted = format_date_for_run(iso_date)
        return "pending_confirmation", {
            "type": "run",
            "date": formatted,
            "distance_km": inputs["distance_km"],
            "time": inputs["time"],
        }
    return f"Unknown fitness tool: {name}", None


def _preview(item: dict) -> str:
    if item["type"] == "swim":
        return f"🏊 *{item['distance']:,}m* on {item['date']}"
    distance_m = round(item["distance_km"] * 1000)
    return f"🏃 *{distance_m:,}m* in {item['time']} on {item['date']}"


def _commit(item: dict, context) -> tuple[str, str]:
    if item["type"] == "swim":
        stats = _log_swim(item["date"], item["distance"])
        confirmation = format_swim_confirmation(item["date"], item["distance"], stats)
        outcome = f"User confirmed. Swim of {item['distance']}m logged on {item['date']}."
        return confirmation, outcome
    _log_run(item["date"], item["distance_km"], item["time"])
    confirmation = format_run_confirmation(item["date"], item["distance_km"], item["time"])
    outcome = (
        f"User confirmed. Run of {item['distance_km']}km in {item['time']} "
        f"logged on {item['date']}."
    )
    return confirmation, outcome


def _instructions(ctx: dict) -> str:
    return "You can log swim and run sessions when the user mentions them. "


FITNESS_SKILL = Skill(
    name="fitness",
    tools=FITNESS_TOOLS,
    execute=_execute,
    instructions=_instructions,
    preview=_preview,
    commit=_commit,
)
