# Accounting

Personal finance tracking inside the `/assist` Telegram bot. Backed by a Google Sheet referenced by `GOOGLE_SHEET_ID_FINANCE_SG`. Log expenses and income in natural language, query them later, and aggregate however you want.

Base currency: **SGD** (configurable via `DEFAULT_CURRENCY`).

---

## Mental model — four ways to slice a transaction

Every row gets classified along these dimensions. Pick the right one for the right kind of information:

| Dimension | How many per row | What it's for | Where the canonical list lives |
|---|---|---|---|
| `category` | 1, required | The primary bucket — Food, Tech, Rent, Salary, … | `categories` tab |
| `merchant` | 0 or 1 | Where the money went or came from | freeform (no tab) |
| `payment_method` | 0 or 1 | Which account / card paid | `payment_methods` tab |
| `tags` | 0..N | Cross-cutting groupings | `tags` tab |

### When to use what

- **category** — the one bucket every transaction lives in. Mutually exclusive. Use the existing list; new ones get confirmed before being added.
- **merchant** — *where*. Apple Store, FairPrice, your employer. Freeform, no canonical list — Claude extracts it from your message when obvious.
- **payment_method** — *how*. DBS Altitude, PayLah, Cash. Strict list; you maintain it.
- **tags** — *what this is part of* across multiple categories. A Japan trip touches Food, Transport, Hotels — tagging them all `japan-trip` lets you ask "how much did I spend on the Japan trip" across all categories. Good tag uses:
  - Trips (`japan-trip`, `bali-2026`)
  - Events (`wedding-2026`, `mom-birthday`)
  - Projects (`home-reno`)
  - Recipients (`gift-mom`)
  - Conditional flags (`reimbursable`, `tax-deductible`)

**Don't tag what's already a category.** If you reach for a tag called `food` or `transport`, stop — you have a Food or Transport category for that. Tags are for things that cut *across* categories. The bot will warn you if it's about to create a new tag, with a one-line reminder of this.

---

## Logging

Start a session with `/assist`, then describe the transaction. The bot calls Claude, which builds a structured log and shows you a preview with **Confirm / Cancel** buttons. Nothing hits the sheet until you confirm.

### Examples

| You say | What gets logged |
|---|---|
| "12 SGD lunch at Maxwell" | type=expense, amount=12, currency=SGD, category=Food, merchant=Maxwell |
| "Bought a MacBook for 1499 EUR at Apple Store" | bot asks "what's that in SGD?", then logs both amounts |
| "Got 3200 SGD salary" | type=income, category=Salary |
| "Netflix bill 18 SGD, monthly subscription" | `recurring=true` |
| "25 SGD at FairPrice on groceries, paid with DBS Altitude" | category=Groceries, merchant=FairPrice, payment_method=DBS Altitude |
| "Person A reimbursed 40 SGD for the Pasta Place dinner" | bot searches for the original, logs an income row with `linked_id` pointing to it |

### Foreign currency

If the currency isn't SGD and you don't supply the SGD equivalent, the bot asks for it. The bot does **not** look up FX rates — you tell it the rate (or the converted amount) at log time.

### New categories / payment methods / tags

If Claude proposes something not in your canonical list, the preview shows a warning:

```
⚠️ New category will be created: 'Pets'
```

Clicking **Confirm** logs the row *and* appends the new value to the relevant tab for next time. Cancelling does neither.

For tags specifically you'll also see the reminder:

```
ℹ️ Tags are for cross-cutting groupings (trips, events, projects, recipients,
   conditional flags) — not for things that fit a category.
```

If that doesn't apply, cancel and rephrase using a category instead.

### Recurring

Set `recurring` only when the transaction is part of a series: subscriptions, rent, phone bill, utilities, salary. The bot only flips this on when you explicitly mention recurrence ("monthly", "subscription", "rent for May"). It's stored as a checkbox in column L.

Why bother: it unlocks queries like "what are my recurring expenses" and "subscription cost per month" without you having to tag each one.

### Linked transactions

When two rows are about the same underlying thing — typically refunds or reimbursements — the child row carries `linked_id` pointing to the parent's id.

**Workflow:**
1. Log the original purchase normally (e.g. "Pasta Place dinner 80 SGD").
2. Later, when reimbursed: "Person A reimbursed 40 SGD for the Pasta Place dinner".
3. Behind the scenes Claude calls `search_transactions(query="Pasta Place")` to find the parent's id, then logs the income row with `linked_id` set.

You'll see `🔗 linked: <id>` in the preview. The bot never invents an id — if it can't find the parent, it'll tell you.

---

## Querying

Same `/assist` session. Ask in natural language; the bot routes to one of two read-only tools (`search_transactions` for individual rows, `aggregate_transactions` for totals / breakdowns) and answers.

Examples that work:

- *"When did I buy my MacBook?"*
- *"How much did I spend on my Japan trip?"*
- *"Top 3 spending categories last calendar month"*
- *"Give me a report — top 3 spending and how much I saved last month"*
- *"What are my recurring expenses?"*
- *"How much do my subscriptions cost per month?"*
- *"Recurring vs ad-hoc spending this year"*
- *"Biggest expense category each month this year"*
- *"Where do I spend most on food?"*
- *"Average grocery spend per week"*
- *"Net cashflow this calendar year"*
- *"Was the MacBook reimbursed?"*

The bot reads the sheet **fresh on every query** — no caching, no stale data. If you manually edit a row in Sheets, the next query reflects it.

### Things to know about how queries work

- **Currency**: aggregations sum `amount_sgd` (the base-currency-normalised value). Amounts shown to you default to SGD; original currency is mentioned only when you asked about a foreign-currency context (e.g. trip totals).
- **"Last calendar month"** = the previous full month. If today is 2026-06-30, "last calendar month" = 2026-05-01 to 2026-05-31. Not a rolling 30-day window.
- **Tag aggregation fans out**: a row with `tags=a,b` counts under both `a` and `b`. Tag totals can exceed the grand total — that's intentional.
- **"Biggest expense per month"** defaults to *biggest category sum*. If you mean the single largest transaction instead, say so and the bot will switch interpretation.

---

## Sheet structure

One Google Sheet (`GOOGLE_SHEET_ID_FINANCE_SG`), four tabs.

### `transactions` — 15 columns

Column order matters — the bot writes by index, not by header name.

| Col | Field | Type | Notes |
|---|---|---|---|
| A | `date` | ISO `YYYY-MM-DD` | when the transaction happened |
| B | `type` | `expense` / `income` | |
| C | `description` | text | short "what" |
| D | `merchant` | text | optional |
| E | `category` | text | from `categories` tab |
| F | `amount` | number | original currency |
| G | `currency` | text | ISO uppercase (`SGD`, `EUR`, `JPY`) |
| H | `amount_sgd` | number | SGD equivalent |
| I | `tags` | text | comma-separated, from `tags` tab |
| J | `payment_method` | text | from `payment_methods` tab |
| K | `notes` | text | freeform context |
| L | `recurring` | checkbox | TRUE when part of a series |
| M | `id` | text | auto, format `YYYYMMDD-HHMMSS-xxxx` |
| N | `linked_id` | text | optional, references another row's `id` |
| O | `logged_at` | datetime | auto, when the bot wrote the row |

### `categories`, `payment_methods`, `tags`

Each is a one-column reference list. Column A, one value per row, no header. The bot reads these on session start to know what's canonical, and appends to them on Confirm when you accept a new value.

---

## Tips & gotchas

- **Don't reach for a tag when a category fits.** That's the most common drift mistake. The preview reminder is there to catch it.
- **Manual edits in Sheets are fine.** The bot reads fresh; corrections show up immediately. Use this to fix typos in old rows.
- **Confirm-after-restart doesn't work.** Pending confirmation state is in memory — if the bot restarts between preview and Confirm, the click does nothing. Just re-describe the transaction.
- **Linked references are one-way and unvalidated.** The child row stores `linked_id`. If you delete a parent in the sheet, the child still points to a non-existent id (harmless, but `search_transactions(linked_to_id=...)` will return empty).
- **Empty `tags` is normal.** Most transactions don't need a tag.
- **Cancelling rejects everything.** A pending log with new category + new payment method + new tags + the transaction itself = one Confirm to add them all, one Cancel to add none.
- **FX precision drifts ~1-2%** per foreign-currency transaction because you supply the SGD value manually. Fine for budgeting, not for tax filing.

---

## Commands

| Command | What it does |
|---|---|
| `/assist` | Start a session. Loads categories, payment methods, and tags from the sheet. |
| `/done` | End the session. Clears conversation history. |

Sessions time out after 30 minutes of inactivity.

---

## When something breaks

- **"Sorry, you are not authorized"** — your Telegram user id isn't in `ASSIST_ALLOWED_IDS` (see `.env`).
- **Sheet read errors** — confirm the service account email (from `GOOGLE_SERVICE_ACCOUNT_JSON`) has Editor access to the finance sheet, and that all four tab names match exactly (`transactions`, `categories`, `payment_methods`, `tags`).
- **Bot proposes weird categories/tags** — Claude only knows what's currently in the corresponding tab. If `known_tags` is empty, the first few transactions effectively bootstrap the vocabulary. Pre-seed the `tags` tab with anything you know you'll use.
