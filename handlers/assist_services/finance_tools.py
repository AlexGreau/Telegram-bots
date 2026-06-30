import json
import os
from datetime import date as date_today

LOG_TRANSACTION = "log_transaction"
SEARCH_TRANSACTIONS = "search_transactions"
AGGREGATE_TRANSACTIONS = "aggregate_transactions"

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
]


def execute_finance_tool(
    name: str,
    inputs: dict,
    known_categories: list[str],
    known_payment_methods: list[str],
    known_tags: list[str],
) -> tuple[str, dict | None]:
    if name != LOG_TRANSACTION:
        return f"Unknown finance tool: {name}", None

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


# --- Read-only queries -------------------------------------------------------

def execute_finance_query(name: str, inputs: dict) -> str:
    """Read-only query. Returns JSON string for Claude."""
    from handlers.assist_services.sheets_client import get_all_transactions  # lazy to avoid cycles

    rows = get_all_transactions()
    rows = _apply_filters(rows, inputs)

    if name == SEARCH_TRANSACTIONS:
        rows = _order_rows(rows, inputs.get("order_by", "date_desc"))
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
        groups = _aggregate(rows, group_by, metric)
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


def _apply_filters(rows: list[dict], inputs: dict) -> list[dict]:
    query = (inputs.get("query") or "").strip().lower()
    type_ = inputs.get("type")
    cats = {c.lower() for c in inputs.get("categories") or []}
    merchants = {m.lower() for m in inputs.get("merchants") or []}
    tags_any = {t.lower() for t in inputs.get("tags_any") or []}
    tags_all = {t.lower() for t in inputs.get("tags_all") or []}
    pms = {p.lower() for p in inputs.get("payment_methods") or []}
    currencies = {c.upper() for c in inputs.get("currencies") or []}
    recurring = inputs.get("recurring")
    linked_to_id = (inputs.get("linked_to_id") or "").strip()
    date_from = inputs.get("date_from")
    date_to = inputs.get("date_to")
    amount_sgd_min = inputs.get("amount_sgd_min")
    amount_sgd_max = inputs.get("amount_sgd_max")

    def keep(r: dict) -> bool:
        if query:
            blob = f"{r.get('description', '')} {r.get('merchant', '')} {r.get('notes', '')}".lower()
            if query not in blob:
                return False
        if type_ and r.get("type") != type_:
            return False
        if cats and (r.get("category") or "").lower() not in cats:
            return False
        if merchants and (r.get("merchant") or "").lower() not in merchants:
            return False
        if pms and (r.get("payment_method") or "").lower() not in pms:
            return False
        if currencies and (r.get("currency") or "").upper() not in currencies:
            return False
        if tags_any or tags_all:
            row_tags = {t.strip().lower() for t in (r.get("tags") or "").split(",") if t.strip()}
            if tags_any and not (tags_any & row_tags):
                return False
            if tags_all and not tags_all.issubset(row_tags):
                return False
        if recurring is not None and bool(r.get("recurring")) != bool(recurring):
            return False
        if linked_to_id and r.get("linked_id") != linked_to_id:
            return False
        if date_from and (r.get("date") or "") < date_from:
            return False
        if date_to and (r.get("date") or "") > date_to:
            return False
        amt = r.get("amount_sgd") or 0
        if amount_sgd_min is not None and amt < amount_sgd_min:
            return False
        if amount_sgd_max is not None and amt > amount_sgd_max:
            return False
        return True

    return [r for r in rows if keep(r)]


def _order_rows(rows: list[dict], order_by: str) -> list[dict]:
    if order_by == "date_asc":
        return sorted(rows, key=lambda r: r.get("date", ""))
    if order_by == "amount_sgd_desc":
        return sorted(rows, key=lambda r: r.get("amount_sgd") or 0, reverse=True)
    if order_by == "amount_sgd_asc":
        return sorted(rows, key=lambda r: r.get("amount_sgd") or 0)
    # default: date_desc
    return sorted(rows, key=lambda r: r.get("date", ""), reverse=True)


def _row_to_group_keys(row: dict, group_by: str) -> list[str]:
    if group_by == "month":
        return [(row.get("date") or "")[:7] or "(blank)"]
    if group_by == "year":
        return [(row.get("date") or "")[:4] or "(blank)"]
    if group_by == "weekday":
        try:
            return [date_today.fromisoformat(row.get("date", "")).strftime("%A")]
        except (ValueError, TypeError):
            return ["(unknown)"]
    if group_by == "tag":
        tags = [t.strip() for t in (row.get("tags") or "").split(",") if t.strip()]
        return tags  # fan-out — row with no tags contributes to no group
    if group_by == "recurring":
        return ["True" if row.get("recurring") else "False"]
    val = row.get(group_by) or ""
    return [val or "(blank)"]


def _aggregate(rows: list[dict], group_by: str | None, metric: str) -> list[dict]:
    if not group_by:
        return [_compute_metric("total", rows, metric)]

    groups: dict[str, list[dict]] = {}
    for r in rows:
        for k in _row_to_group_keys(r, group_by):
            groups.setdefault(k, []).append(r)
    return [_compute_metric(k, v, metric) for k, v in groups.items()]


def _compute_metric(key: str, rows_in_group: list[dict], metric: str) -> dict:
    amts = [r.get("amount_sgd") or 0 for r in rows_in_group]
    n = len(rows_in_group)
    if metric == "count":
        v = n
    elif not amts:
        v = 0
    elif metric == "sum_sgd":
        v = round(sum(amts), 2)
    elif metric == "avg_sgd":
        v = round(sum(amts) / n, 2)
    elif metric == "max_sgd":
        v = round(max(amts), 2)
    elif metric == "min_sgd":
        v = round(min(amts), 2)
    else:
        v = 0
    return {"group": key, "value": v, "count": n}
