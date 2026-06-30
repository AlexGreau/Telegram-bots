# Finance

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

### The `goods` tag — physical purchases across categories

A `Shopping` category alone isn't enough to answer *"how much did I spend shopping?"*, because real shopping spans multiple categories (a laptop is `Tech`, a jacket is `Clothing`, a random Amazon trinket is `Shopping`). At the same time, not every `Tech` row is a purchase — a Claude API top-up or a software subscription is `Tech` but isn't "shopping".

Convention: any row that's the acquisition of a **physical / tangible thing** gets the `goods` tag. The bot applies it automatically based on context — you only need to push back on borderline calls.

| Row | category | `goods`? |
|---|---|---|
| Laptop | Tech | yes |
| Headphones | Tech | yes |
| Claude API top-up | Tech | no (service) |
| GitHub subscription | Tech | no (service) |
| Jacket | Clothing | yes |
| Concert ticket | Entertainment | no (experience) |
| Board game | Entertainment | yes |
| Random Amazon doodad | Shopping | yes |
| Restaurant meal | Food | no (experience) |
| Mom's birthday gift | Shopping | yes (can also tag `gift`) |

Then *"how much did I spend shopping?"* is a single aggregate over `tags_any=["goods"]` — cross-category, but services and subscriptions correctly excluded.

Add `goods` to your `tags` tab so the bot sees it as canonical from the start.

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

## Reports

`/report` pulls a deterministic monthly or yearly summary — same numbers, same layout every time. Unlike the `/assist` queries above, it doesn't go through Claude; the bot computes everything in Python directly from the sheet.

| Command | Period |
|---|---|
| `/report` | current month |
| `/report last` | previous month |
| `/report may` | a named month, this year |
| `/report 2026-05` | a specific month |
| `/report 2026` | a full calendar year |

Each report shows:

- **Spent / Income / Net** for the period (net = income − spend; `+` means you saved).
- **vs the previous period** — spend change as a percentage and net change as an absolute amount (e.g. `vs Apr: spend −4%, net +120`). The previous period is the prior month for a month report, the prior year for a year report.
- **Top 3 spending categories** with amounts.
- **Recurring vs ad-hoc** spend, split on the `recurring` flag.
- **Budgets** — for month reports, each budgeted category (from the `budgets` tab) compared to its monthly limit, with `⚠️` when you're over and `✅` when under. Omitted for year reports and when no `budgets` tab exists.

All amounts are in the base currency (SGD), summed from `amount_sgd`. The sheet is read fresh on every `/report`, same as queries.

`/report` works on its own — no `/assist` session needed — and can also be sent mid-session.

## Sheet structure

One Google Sheet (`GOOGLE_SHEET_ID_FINANCE_SG`), four core tabs (plus an optional `budgets` tab).

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

### `budgets` (optional)

Two columns, no header: `category` (col A) | `monthly_limit` (col B, in base currency). One row per budgeted category. Used by `/report` (see below) to flag categories you've gone over for the month. The tab is optional — if it doesn't exist, `/report` still works and just omits the budget section. Maintained by hand in Sheets, like the other reference tabs (no bot command to edit budgets yet).

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
| `/report [period]` | Deterministic monthly / yearly finance summary. See [Reports](#reports). No session needed. |

Sessions time out after 30 minutes of inactivity.

---

## When something breaks

- **"Sorry, you are not authorized"** — your Telegram user id isn't in `ASSIST_ALLOWED_IDS` (see `.env`).
- **Sheet read errors** — confirm the service account email (from `GOOGLE_SERVICE_ACCOUNT_JSON`) has Editor access to the finance sheet, and that all four tab names match exactly (`transactions`, `categories`, `payment_methods`, `tags`).
- **Bot proposes weird categories/tags** — Claude only knows what's currently in the corresponding tab. If `known_tags` is empty, the first few transactions effectively bootstrap the vocabulary. Pre-seed the `tags` tab with anything you know you'll use.
