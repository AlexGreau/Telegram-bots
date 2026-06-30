"""Deterministic monthly / yearly finance reports for the /report command.

Pure functions (no Telegram, no network): resolve a period from a user argument,
build the report numbers by reusing the filter/aggregate primitives from
finance_tools, and format the result as plain text with light Markdown.
"""
import calendar
import os
from dataclasses import dataclass
from datetime import date

from handlers.assist_services.finance_tools import _aggregate, _apply_filters

_MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
_MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})

_USAGE = (
    "Usage: /report [period]\n"
    "  /report            this month\n"
    "  /report last       previous month\n"
    "  /report may        a named month (this year)\n"
    "  /report 2026-05    a specific month\n"
    "  /report 2026       a full year"
)


@dataclass
class Period:
    label: str
    granularity: str  # "month" | "year"
    date_from: str
    date_to: str
    prev_label: str
    prev_from: str
    prev_to: str


def _month_bounds(year: int, month: int) -> tuple[str, str]:
    last = calendar.monthrange(year, month)[1]
    return f"{year:04d}-{month:02d}-01", f"{year:04d}-{month:02d}-{last:02d}"


def _prev_month(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


def _month_period(year: int, month: int) -> Period:
    df, dt = _month_bounds(year, month)
    py, pm = _prev_month(year, month)
    pdf, pdt = _month_bounds(py, pm)
    return Period(
        label=f"{calendar.month_name[month]} {year}",
        granularity="month",
        date_from=df,
        date_to=dt,
        prev_label=calendar.month_abbr[pm],
        prev_from=pdf,
        prev_to=pdt,
    )


def _year_period(year: int) -> Period:
    return Period(
        label=str(year),
        granularity="year",
        date_from=f"{year:04d}-01-01",
        date_to=f"{year:04d}-12-31",
        prev_label=str(year - 1),
        prev_from=f"{year - 1:04d}-01-01",
        prev_to=f"{year - 1:04d}-12-31",
    )


def resolve_period(arg: str | None, today: date) -> Period:
    """Map a /report argument to a Period. Raises ValueError with usage on bad input."""
    arg = (arg or "").strip().lower()

    if not arg or arg == "this month":
        return _month_period(today.year, today.month)

    if arg in ("last", "last month"):
        py, pm = _prev_month(today.year, today.month)
        return _month_period(py, pm)

    if arg.isdigit() and len(arg) == 4:
        return _year_period(int(arg))

    if len(arg) == 7 and arg[4] == "-":  # YYYY-MM
        y, _, m = arg.partition("-")
        if y.isdigit() and m.isdigit() and 1 <= int(m) <= 12:
            return _month_period(int(y), int(m))

    if arg in _MONTHS:
        return _month_period(today.year, _MONTHS[arg])

    raise ValueError(_USAGE)


def _category_spend(expense_rows: list[dict]) -> dict[str, float]:
    return {g["group"]: g["value"] for g in _aggregate(expense_rows, "category", "sum_sgd")}


def _totals(rows: list[dict], period_from: str, period_to: str) -> dict:
    scoped = _apply_filters(rows, {"date_from": period_from, "date_to": period_to})
    expenses = [r for r in scoped if r.get("type") == "expense"]
    incomes = [r for r in scoped if r.get("type") == "income"]
    spent = _aggregate(expenses, None, "sum_sgd")[0]["value"] if expenses else 0.0
    income = _aggregate(incomes, None, "sum_sgd")[0]["value"] if incomes else 0.0
    return {"expenses": expenses, "spent": spent, "income": income, "net": round(income - spent, 2)}


def build_report(rows: list[dict], period: Period, budgets: dict[str, float]) -> dict:
    base_ccy = os.getenv("DEFAULT_CURRENCY", "SGD").upper()

    cur = _totals(rows, period.date_from, period.date_to)
    prev = _totals(rows, period.prev_from, period.prev_to)

    cat_spend = _category_spend(cur["expenses"])
    top = sorted(cat_spend.items(), key=lambda kv: kv[1], reverse=True)[:3]

    recurring_groups = {g["group"]: g["value"] for g in _aggregate(cur["expenses"], "recurring", "sum_sgd")}
    recurring_spend = recurring_groups.get("True", 0.0)
    adhoc_spend = recurring_groups.get("False", 0.0)

    spent_pct = (
        round((cur["spent"] - prev["spent"]) / prev["spent"] * 100)
        if prev["spent"]
        else None
    )

    # Budgets are monthly limits — only meaningful for a month report in v1.
    budget_lines = []
    if period.granularity == "month" and budgets:
        for category, limit in budgets.items():
            spent_cat = cat_spend.get(category, 0.0)
            budget_lines.append({
                "category": category,
                "spent": round(spent_cat, 2),
                "limit": limit,
                "over": spent_cat > limit,
            })
        budget_lines.sort(key=lambda b: b["spent"] - b["limit"], reverse=True)

    return {
        "base_currency": base_ccy,
        "label": period.label,
        "prev_label": period.prev_label,
        "granularity": period.granularity,
        "spent": cur["spent"],
        "income": cur["income"],
        "net": cur["net"],
        "top_categories": top,
        "recurring_spend": recurring_spend,
        "adhoc_spend": adhoc_spend,
        "prev_spent": prev["spent"],
        "prev_net": prev["net"],
        "spent_pct": spent_pct,
        "net_delta": round(cur["net"] - prev["net"], 2),
        "budgets": budget_lines,
    }


def _money(value: float) -> str:
    return f"{value:,.2f}"


def _signed(value: float) -> str:
    return f"{'+' if value >= 0 else '-'}{abs(value):,.2f}"


def format_report(report: dict) -> str:
    ccy = report["base_currency"]
    lines = [f"📊 *Finance Report — {report['label']}*", ""]

    delta_bits = []
    if report["spent_pct"] is not None:
        sign = "+" if report["spent_pct"] >= 0 else "−"
        delta_bits.append(f"spend {sign}{abs(report['spent_pct'])}%")
    delta_bits.append(f"net {_signed(report['net_delta'])}")
    delta = f"   (vs {report['prev_label']}: {', '.join(delta_bits)})"

    lines.append(f"Spent:   {_money(report['spent'])} {ccy}")
    lines.append(f"Income:  {_money(report['income'])} {ccy}")
    lines.append(f"Net:     {_signed(report['net'])} {ccy}{delta}")
    lines.append("")

    if report["top_categories"]:
        lines.append("*Top categories:*")
        for cat, amt in report["top_categories"]:
            lines.append(f"  {cat}  {_money(amt)}")
    else:
        lines.append("No expenses in this period.")
    lines.append("")

    lines.append(
        f"Recurring: {_money(report['recurring_spend'])} · "
        f"Ad-hoc: {_money(report['adhoc_spend'])}"
    )

    if report["budgets"]:
        lines.append("")
        lines.append("*Budgets:*")
        for b in report["budgets"]:
            mark = "⚠️" if b["over"] else "✅"
            line = f"  {mark} {b['category']}  {_money(b['spent'])} / {_money(b['limit'])}"
            if b["over"]:
                line += f"  (over by {_money(b['spent'] - b['limit'])})"
            lines.append(line)

    return "\n".join(lines)
