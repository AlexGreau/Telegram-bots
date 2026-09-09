"""Pure filter / aggregate primitives over transaction rows.

Shared engine used by both faces of the finance capability: the conversational
tools (search / aggregate inside /assist) and the deterministic /report command.
No Telegram, no network — just row dicts in, numbers out.
"""
from datetime import date as date_today


def apply_filters(rows: list[dict], inputs: dict) -> list[dict]:
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


def order_rows(rows: list[dict], order_by: str) -> list[dict]:
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


def aggregate(rows: list[dict], group_by: str | None, metric: str) -> list[dict]:
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
