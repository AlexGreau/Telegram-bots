"""Finance capability inside the /assist agent loop.

Owns the log/search/aggregate tool schemas, the finance system-prompt
instructions, and the preview + commit steps for a pending transaction.
The read-only queries and the deterministic /report command both build on the
shared primitives in core.py.
"""
import json
import os
from datetime import date as date_today
from pathlib import Path

from handlers.assist_services.skills.base import Skill
from handlers.assist_services.skills.finance.core import aggregate, apply_filters, order_rows
from handlers.assist_services.sheets_client import (
    add_category,
    add_payment_method,
    add_tag,
    format_transaction_confirmation,
    get_all_transactions,
    log_transaction as _log_transaction,
)

LOG_TRANSACTION = "log_transaction"
SEARCH_TRANSACTIONS = "search_transactions"
AGGREGATE_TRANSACTIONS = "aggregate_transactions"
EXPLAIN_FINANCE = "explain_finance_feature"

# The user-facing guide is loaded on demand (via the explain_finance_feature tool)
# rather than prepended to every request, to keep per-message token cost down.
# repo_root/docs/finance.md  <-  handlers/assist_services/skills/finance/tools.py
_FINANCE_GUIDE = (Path(__file__).resolve().parents[4] / "docs" / "finance.md").read_text(encoding="utf-8")

_QUERY_FILTER_PROPERTIES = {
    "query": {
        "type": "string",
        "description": "Case-insensitive substring match against description, merchant, and notes.",
    },
    "type": {
        "type": "string",
        "enum": ["expense", "income"],
        "description": "Filter by transaction type.",
    },
    "categories": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Any-match (case-insensitive) against the category column.",
    },
    "merchants": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Any-match (case-insensitive) against the merchant column.",
    },
    "tags_any": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Row matches if its tags set intersects this list (case-insensitive).",
    },
    "tags_all": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Row matches only if all of these tags are present (case-insensitive).",
    },
    "payment_methods": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Any-match (case-insensitive) against the payment_method column.",
    },
    "currencies": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Any-match (uppercase) against the original currency column.",
    },
    "recurring": {
        "type": "boolean",
        "description": "If true, only recurring rows. If false, only non-recurring rows. Omit to ignore.",
    },
    "linked_to_id": {
        "type": "string",
        "description": "Returns rows whose linked_id equals this value (i.e. find children of this parent row).",
    },
    "date_from": {
        "type": "string",
        "description": "Inclusive lower bound on date (ISO YYYY-MM-DD).",
    },
    "date_to": {
        "type": "string",
        "description": "Inclusive upper bound on date (ISO YYYY-MM-DD).",
    },
    "amount_sgd_min": {
        "type": "number",
        "description": "Inclusive lower bound on amount_sgd.",
    },
    "amount_sgd_max": {
        "type": "number",
        "description": "Inclusive upper bound on amount_sgd.",
    },
}

FINANCE_TOOLS = [
    {
        "name": LOG_TRANSACTION,
        "description": (
            "Log a personal finance transaction (expense or income). "
            "Use when the user mentions spending or receiving money. "
            "If the user supplies an amount in a non-base currency without the base-currency "
            "equivalent, this tool will return a message asking you to ask the user for it; "
            "do not guess the FX rate. "
            "Pick `category` from the provided list when one fits; if nothing fits, propose a "
            "new, short, Title-Case category — the user will see and confirm it before it is added. "
            "Same rule applies to `payment_method`: pick from the known list when one fits; if not, "
            "propose a new one and the user will confirm it. "
            "For tags, reuse an existing tag from the known_tags list when it captures the same "
            "concept (e.g. don't introduce 'japan_trip' if 'japan-trip' already exists); only "
            "invent a new tag when nothing fits. Tags are not user-confirmed."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["expense", "income"],
                    "description": "Whether this is money out (expense) or money in (income).",
                },
                "amount": {
                    "type": "number",
                    "description": "Amount in the original currency. Positive number.",
                },
                "currency": {
                    "type": "string",
                    "description": (
                        "ISO 4217 3-letter currency code in uppercase (e.g. SGD, EUR, USD, JPY). "
                        "Omit if the user did not specify; defaults to the base currency."
                    ),
                },
                "amount_sgd": {
                    "type": "number",
                    "description": (
                        "Amount converted to the base currency. "
                        "Required when `currency` is not the base currency. "
                        "If the user did not provide it, omit and this tool will ask you to ask the user."
                    ),
                },
                "category": {
                    "type": "string",
                    "description": (
                        "Category for this transaction. Prefer one from the known categories. "
                        "If none fits, propose a short Title-Case category name."
                    ),
                },
                "description": {
                    "type": "string",
                    "description": "Short description of what the transaction was for (e.g. 'lunch', 'MacBook Pro 14').",
                },
                "merchant": {
                    "type": "string",
                    "description": (
                        "Where the transaction happened (e.g. 'Apple Store', 'Ichiran', 'FairPrice'). "
                        "Fill when obvious from context; leave blank otherwise."
                    ),
                },
                "date": {
                    "type": "string",
                    "description": "ISO date (YYYY-MM-DD). Omit if the user means today.",
                },
                "tags": {
                    "type": "string",
                    "description": (
                        "Optional comma-separated freeform tags (e.g. 'japan-trip,work'). "
                        "No quotes, no spaces around commas. Reuse from known_tags when possible."
                    ),
                },
                "payment_method": {
                    "type": "string",
                    "description": (
                        "How the transaction was paid. Optional. Prefer one from the known list. "
                        "If nothing fits, propose a new short Title-Case name — the user will "
                        "confirm before it is added."
                    ),
                },
                "notes": {
                    "type": "string",
                    "description": "Optional additional context.",
                },
                "recurring": {
                    "type": "boolean",
                    "description": (
                        "True iff this transaction is part of a recurring series "
                        "(subscription, rent, phone bill, utilities, salary). "
                        "Set only when the user explicitly mentions the recurring nature. "
                        "Default false."
                    ),
                },
                "linked_id": {
                    "type": "string",
                    "description": (
                        "Optional id of a related transaction (refund of a purchase, "
                        "reimbursement of an expense). MUST reference an existing row's id — "
                        "call `search_transactions` first to find the parent row, then pass its id here. "
                        "NEVER invent or guess an id."
                    ),
                },
            },
            "required": ["type", "amount", "category", "description"],
        },
    },
    {
        "name": SEARCH_TRANSACTIONS,
        "description": (
            "Search the transactions sheet. Use for 'when did I buy X', to list rows matching "
            "specific filters, to find recurring transactions, or to find rows linked to a "
            "given parent (linked_to_id). All filters are AND'd; array filters are any-match. "
            "Returns a JSON object with `count` and `rows` (rows omit logged_at to save tokens)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                **_QUERY_FILTER_PROPERTIES,
                "order_by": {
                    "type": "string",
                    "enum": ["date_desc", "date_asc", "amount_sgd_desc", "amount_sgd_asc"],
                    "description": "Sort order. Default date_desc.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max rows returned. Default 50, hard cap 500.",
                },
            },
        },
    },
    {
        "name": AGGREGATE_TRANSACTIONS,
        "description": (
            "Group and aggregate transactions. Use for totals, top-N breakdowns, monthly "
            "trends. Same filters as search_transactions. Omit `group_by` for a grand total. "
            "Tag grouping fans out (a row with tags='a,b' counts under both a and b — tag "
            "totals can exceed the grand total). Returns a JSON object with `groups`, each "
            "having {group, value, count}, sorted by value (desc by default)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                **_QUERY_FILTER_PROPERTIES,
                "group_by": {
                    "type": "string",
                    "enum": [
                        "month", "year", "category", "merchant", "tag",
                        "currency", "type", "weekday", "payment_method", "recurring",
                    ],
                    "description": "Optional grouping dimension. Omit for grand total.",
                },
                "metric": {
                    "type": "string",
                    "enum": ["sum_sgd", "count", "avg_sgd", "max_sgd", "min_sgd"],
                    "description": "Aggregation function. Defaults to sum_sgd.",
                },
                "order": {
                    "type": "string",
                    "enum": ["desc", "asc"],
                    "description": "Order groups by value. Default desc.",
                },
                "top_n": {
                    "type": "integer",
                    "description": "Optional cap on groups returned.",
                },
            },
        },
    },
    {
        "name": EXPLAIN_FINANCE,
        "description": (
            "Read the finance feature guide. Call this ONLY when the user asks how the finance "
            "feature itself works — what tags vs categories are for, how reimbursements/linking "
            "work, what 'recurring' means, how goods tagging works, and similar meta questions. "
            "Do NOT call it for logging a transaction or for querying the user's actual data. "
            "Returns the guide text; paraphrase it in plain text when you answer."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
]


def _instructions(ctx: dict) -> str:
    today = ctx["today"]
    base_currency = ctx["base_currency"]
    known_categories = ctx.get("known_categories") or []
    known_tags = ctx.get("known_tags") or []
    known_payment_methods = ctx.get("known_payment_methods") or []
    cats = ", ".join(known_categories) if known_categories else "(none yet)"
    tags = ", ".join(known_tags) if known_tags else "(none yet)"
    pms = ", ".join(known_payment_methods) if known_payment_methods else "(none yet)"
    return (
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
        "When tagging, prefer existing tags from this list (case-insensitive match). "
        "Tags are for cross-cutting groupings that span multiple categories — trips, events, "
        "projects, recipients, conditional flags. They are NOT for things that already fit an "
        "existing category. Only propose a new short, kebab-case tag when the user describes a "
        "cross-cutting context that no existing tag captures. The user will confirm before any "
        "new tag is added to the canonical list. "
        "Auto-apply the `goods` tag whenever the user logs an expense for a physical/tangible "
        "item being acquired — laptops, headphones, clothing, books, household items, gifts, "
        "gadgets, furniture, etc. Do NOT apply `goods` to services, subscriptions, API top-ups "
        "/ credits, software licences, experiences (concerts, meals out, travel transport), "
        "bills, salary, refunds, or anything `recurring=true`. The `goods` tag lets the user "
        "ask 'how much did I spend shopping' across all categories. "
        "If the user spends in a non-base currency without giving the converted amount, do NOT "
        "guess an FX rate; call log_transaction without amount_sgd and the tool will instruct "
        "you to ask the user. "
        "Set log_transaction's `recurring=true` only when the user explicitly mentions the "
        "transaction recurs (Netflix, rent, phone bill, utilities, salary). Leave it false otherwise. "
        "To link a transaction to another (refund of a purchase, reimbursement of an expense), "
        "FIRST call `search_transactions` to find the parent row's id (search by description, "
        "merchant, or date), THEN call `log_transaction` with `linked_id=<that id>`. "
        "NEVER invent or guess an id. "
        "You can answer questions about the user's recorded finances via `search_transactions` "
        "and `aggregate_transactions`. Always call the tool — do not invent numbers. "
        "Use `search_transactions(query=...)` for 'when did I buy X' / 'show me the row about Y' "
        "/ 'what are my recurring expenses' (set `recurring=true`) / 'was X reimbursed' "
        "(search the parent, then search with `linked_to_id=<id>`). "
        "Use `aggregate_transactions` for totals, top-N breakdowns, monthly trends. Omit "
        "`group_by` for a grand total. Group by `recurring` to compare recurring vs ad-hoc spending. "
        "Show amounts in SGD by default; mention original currency only when the user asked "
        "about a specific foreign-currency context (e.g. a trip). "
        "For 'biggest expense per month' default to category interpretation: group by category "
        "within each month, return the top category. Ask the user to clarify if they meant the "
        "single largest transaction instead. "
        "Resolve relative dates to ISO date_from/date_to. 'Last calendar month' = the previous "
        f"full month (e.g. if today is {today}, last calendar month spans the entire previous month). "
        "Tag aggregation fans out: a row with tags='a,b' contributes to both 'a' and 'b' totals, "
        "so the sum of tag groups may exceed the grand total. "
        "When the user asks how the finance feature works (what tags vs categories "
        "are, how reimbursements get linked, what 'recurring' means, etc.), call "
        "explain_finance_feature to read the guide, then answer in plain text. Paraphrase — "
        "do not quote the markdown verbatim. "
    )


def _build_transaction_pending(
    inputs: dict,
    known_categories: list[str],
    known_payment_methods: list[str],
    known_tags: list[str],
) -> tuple[str, dict | None]:
    base_ccy = os.getenv("DEFAULT_CURRENCY", "SGD").upper()

    txn_type = inputs.get("type")
    if txn_type not in {"expense", "income"}:
        return "Invalid 'type'. Must be 'expense' or 'income'.", None

    amount = inputs.get("amount")
    if amount is None or not isinstance(amount, (int, float)) or amount <= 0:
        return "Invalid 'amount'. Must be a positive number in the original currency.", None

    currency = (inputs.get("currency") or base_ccy).upper()
    amount_sgd = inputs.get("amount_sgd")

    if currency != base_ccy and amount_sgd is None:
        return (
            f"Missing amount_sgd. The user paid {amount} {currency} but did not specify the "
            f"equivalent in {base_ccy}. Ask the user: 'How much was that in {base_ccy}?' "
            f"Do NOT guess or estimate the FX rate. When they reply, call log_transaction "
            f"again with the same fields plus amount_sgd set."
        ), None

    if currency == base_ccy:
        amount_sgd = float(amount)
    else:
        amount_sgd = float(amount_sgd)

    iso_date = inputs.get("date") or date_today.today().isoformat()
    try:
        date_today.fromisoformat(iso_date)
    except ValueError:
        return f"Invalid date '{iso_date}'. Must be ISO YYYY-MM-DD.", None

    category = (inputs.get("category") or "").strip()
    if not category:
        return "Missing 'category'.", None

    canonical_cat = next((c for c in known_categories if c.lower() == category.lower()), None)
    is_new_category = canonical_cat is None
    final_category = category if is_new_category else canonical_cat

    payment_method = (inputs.get("payment_method") or "").strip()
    final_payment_method = ""
    is_new_payment_method = False
    if payment_method:
        canonical_pm = next(
            (p for p in known_payment_methods if p.lower() == payment_method.lower()),
            None,
        )
        is_new_payment_method = canonical_pm is None
        final_payment_method = payment_method if is_new_payment_method else canonical_pm

    raw_tags = [t.strip() for t in (inputs.get("tags") or "").split(",") if t.strip()]
    known_tags_lower = {t.lower(): t for t in known_tags}
    canonical_tags: list[str] = []
    new_tags: list[str] = []
    seen: set[str] = set()
    for t in raw_tags:
        canonical = known_tags_lower.get(t.lower())
        if canonical is None:
            final = t
            if final.lower() not in seen:
                new_tags.append(final)
        else:
            final = canonical
        if final.lower() not in seen:
            canonical_tags.append(final)
            seen.add(final.lower())
    final_tags = ",".join(canonical_tags)

    pending = {
        "kind": "transaction",
        "txn_type": txn_type,
        "amount": float(amount),
        "currency": currency,
        "amount_sgd": amount_sgd,
        "base_currency": base_ccy,
        "category": final_category,
        "description": inputs.get("description", "").strip(),
        "merchant": (inputs.get("merchant") or "").strip(),
        "date": iso_date,
        "tags": final_tags,
        "payment_method": final_payment_method,
        "notes": (inputs.get("notes") or "").strip(),
        "recurring": bool(inputs.get("recurring", False)),
        "linked_id": (inputs.get("linked_id") or "").strip(),
        "new_category": final_category if is_new_category else None,
        "new_payment_method": final_payment_method if is_new_payment_method else None,
        "new_tags": new_tags,
    }
    return "pending_confirmation", pending


def _run_query(name: str, inputs: dict) -> str:
    """Read-only query. Returns JSON string for Claude."""
    rows = get_all_transactions()
    rows = apply_filters(rows, inputs)

    if name == SEARCH_TRANSACTIONS:
        rows = order_rows(rows, inputs.get("order_by", "date_desc"))
        limit = inputs.get("limit", 50)
        try:
            limit = min(int(limit), 500)
        except (TypeError, ValueError):
            limit = 50
        rows = rows[:limit]
        out = [{k: v for k, v in r.items() if k != "logged_at"} for r in rows]
        return json.dumps({"count": len(out), "rows": out}, ensure_ascii=False, default=str)

    if name == AGGREGATE_TRANSACTIONS:
        group_by = inputs.get("group_by")
        metric = inputs.get("metric", "sum_sgd")
        groups = aggregate(rows, group_by, metric)
        order = inputs.get("order", "desc")
        groups.sort(key=lambda g: g["value"], reverse=(order != "asc"))
        top_n = inputs.get("top_n")
        if top_n:
            try:
                groups = groups[: int(top_n)]
            except (TypeError, ValueError):
                pass
        return json.dumps(
            {"group_by": group_by or "total", "metric": metric, "groups": groups},
            ensure_ascii=False,
            default=str,
        )

    return json.dumps({"error": f"Unknown query: {name}"})


async def _execute(name: str, inputs: dict, context) -> tuple[str, dict | None]:
    if name == LOG_TRANSACTION:
        known_cats = context.user_data.get("known_categories", [])
        known_pms = context.user_data.get("known_payment_methods", [])
        known_tags = context.user_data.get("known_tags", [])
        return _build_transaction_pending(inputs, known_cats, known_pms, known_tags)
    if name in {SEARCH_TRANSACTIONS, AGGREGATE_TRANSACTIONS}:
        return _run_query(name, inputs), None
    if name == EXPLAIN_FINANCE:
        return _FINANCE_GUIDE, None
    return f"Unknown finance tool: {name}", None


def _preview(item: dict) -> str:
    return format_transaction_confirmation(item)


def _commit(item: dict, context) -> tuple[str, str]:
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
    new_tags = item.get("new_tags") or []
    if new_tags:
        cache = context.user_data.get("known_tags", [])
        cache_lower = {t.lower() for t in cache}
        for t in new_tags:
            add_tag(t)
            if t.lower() not in cache_lower:
                cache.append(t)
                cache_lower.add(t.lower())
        context.user_data["known_tags"] = cache
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
    confirmation = "✅ Logged:\n" + format_transaction_confirmation(item)
    extras = ""
    if item.get("recurring"):
        extras += " [recurring]"
    if item.get("linked_id"):
        extras += f" [linked_id={item['linked_id']}]"
    outcome = (
        f"User confirmed. Transaction logged: {item['txn_type']} "
        f"{item['amount']} {item['currency']} ({item['category']}) — "
        f"{item['description']} on {item['date']}.{extras}"
    )
    return confirmation, outcome


FINANCE_SKILL = Skill(
    name="finance",
    tools=FINANCE_TOOLS,
    execute=_execute,
    instructions=_instructions,
    preview=_preview,
    commit=_commit,
)
