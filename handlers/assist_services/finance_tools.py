import os
from datetime import date as date_today

LOG_TRANSACTION = "log_transaction"

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
            },
            "required": ["type", "amount", "category", "description"],
        },
    },
]


def execute_finance_tool(
    name: str,
    inputs: dict,
    known_categories: list[str],
    known_payment_methods: list[str],
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
        "tags": (inputs.get("tags") or "").strip(),
        "payment_method": final_payment_method,
        "notes": (inputs.get("notes") or "").strip(),
        "new_category": final_category if is_new_category else None,
        "new_payment_method": final_payment_method if is_new_payment_method else None,
    }
    return "pending_confirmation", pending
