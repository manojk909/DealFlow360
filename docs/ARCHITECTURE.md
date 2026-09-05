# ARCHITECTURE — DealFlow360

## Repository state at time of writing

`DealFlow360/` was **empty**. No source, no package manifest, no README, no tests, no
migrations, no `.claude/` config, no `.env`. Everything below is greenfield and nothing
here is constrained by existing code.

Verified on the dev machine: Python 3.10.12, pip 25.3, Node v22.23.2, Java 11, git 2.34.1.
**Not present:** Docker, `psql`, Go, pnpm.

## Tech stack — FINAL

Confirmed by the team. See ADR-001 and ADR-002.

| Layer | Choice | Why |
|---|---|---|
| Framework | **Django 5** (Python 3.10) | Batteries included. `django.contrib.auth` and `django.contrib.admin` cover authentication, roles and the entire backend configuration area (SPEC §4 A2–A7) with almost no code — that is roughly seven CRUD screens we do not write by hand. |
| ORM & migrations | **Django ORM** | Built in. Models, migrations, admin and forms all derive from one model definition. |
| Database | **SQLite** (`db.sqlite3`) | Django's default backend, zero config, one file in the repo. Explicitly local, per the invigilator's requirement. Postgres is not installed and Docker is unavailable, so local Postgres would mean an install on four laptops mid-build. |
| Templates & interactivity | **Django templates + HTMX**, small vanilla JS where needed | HTMX is one `<script>` tag and no build step. The live margin indicator and upsell panel are partial-template swaps, not a client-side app. Avoids reintroducing the two-codebase problem a React SPA would bring back. |
| Styling | **Tailwind via CDN** | Reproduces the mockup's dark theme fast and keeps the colour scheme consistent across 17 screens (an Odoo must-have) with no Node toolchain in the build. |
| Auth | `django.contrib.auth` + custom `User` with a `role` field | Sessions, password hashing and login views are already written and correct. |
| Portal access | Separate Django app, signed quotation-scoped token | Own URL prefix, own base template, own access check. See ADR-004. |
| Tests | Django's built-in test runner | Zero extra dependencies. Used for the domain logic that matters — risk score, split, pricing. |

**Money handling.** SQLite has no native decimal type. Use `DecimalField` on models and do
all money arithmetic in Python with `Decimal` in the services layer. Do **not** push money
sums through SQLite `Sum()` aggregates — they can return floats and drift. This matters
here: line totals, margins and the risk score are all money maths.

## Project layout

Two Django apps, not six. Django apps carry real boilerplate (`apps.py`, `urls.py`,
`migrations/`, …) and six of them would be ~36 files of scaffolding for no benefit at this
size.

```
config/                  settings.py, urls.py, wsgi.py
core/                    the internal application
  models/                split by domain to reduce 4-way merge conflicts
    __init__.py            re-exports everything
    catalogue.py           Category, Product, ProductVariant, PriceListEntry
    parties.py             User, CustomerTier, Customer
    sales.py               Quotation, QuotationLine, ApprovalChainRule,
                           ApprovalStep, AuditLog, PortalMessage
    inventory.py           Warehouse, Stock, FulfilmentAllocation
    billing.py             SubscriptionPlan, BillingScheduleEntry, Invoice, Payment
  services/              ← ALL BUSINESS LOGIC. Plain modules, no Django imports
    pricing.py             line/order totals, margin, price-list resolution
    risk.py                blended discount risk score            (BR-1)
    approval.py            routing, step advance, audit writes    (BR-2, BR-3)
    fulfilment.py          warehouse split, backorders            (BR-4)
    billing.py             invoices, billing schedule, proration  (BR-5)
    negotiation.py         counter-offer → re-score → re-approve  (BR-6)
    upsell.py              ranked suggestions, margin delta       (BR-7)
    health.py              stalled deals, discount anomalies      (BR-8)
  admin.py               registers the config models — this IS the backend config area
  views.py, urls.py      rep workspace
  templates/core/
  tests/                 one test module per service
portal/                  customer-facing app — separate, restricted
  views.py, urls.py
  templates/portal/      its own base template, visually distinct
manage.py
db.sqlite3               local database, gitignored
```

## System architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│  BROWSER                                                             │
│                                                                      │
│   Internal workspace                     Customer portal             │
│   /workspace/... /admin/...              /portal/<token>/...         │
│   session cookie + role                  token scoped to ONE quote   │
└────────────┬─────────────────────────────────────────┬───────────────┘
             │                                         │
             ▼                                         ▼
┌──────────────────────────────────────────────────────────────────────┐
│  ENTRY LAYER — Django views + forms  (core/views.py, portal/views.py)│
│  Authenticate. Authorise by role. Validate via Django forms.         │
│  Call a service. Render a template. NO business rules here.          │
│                                                                      │
│  django.contrib.admin sits alongside as the backend config area      │
│  (SPEC §4 A2–A7) — model-driven CRUD, no hand-written screens.       │
└────────────────────────────┬─────────────────────────────────────────┘
                             ▼
┌──────────────────────────────────────────────────────────────────────┐
│  SERVICES LAYER  —  core/services/*.py   ← ALL BUSINESS LOGIC        │
│  Plain Python. Takes model instances or plain data, returns results. │
│  Testable with `manage.py test`, no browser, no HTTP.                │
└────────────────────────────┬─────────────────────────────────────────┘
                             ▼
┌──────────────────────────────────────────────────────────────────────┐
│  PERSISTENCE — Django ORM                                            │
│  transaction.atomic() wraps any multi-row change (confirm, approve,  │
│  split, pay). Config rows (tiers, ceilings, chains, plans, shipping  │
│  weights) are READ here, never hardcoded above.                      │
└────────────────────────────┬─────────────────────────────────────────┘
                             ▼
┌──────────────────────────────────────────────────────────────────────┐
│  DATABASE — SQLite (db.sqlite3, local file)                          │
└──────────────────────────────────────────────────────────────────────┘
```

## Responsibilities

**Templates.** Render state and collect input. Reproduce the mockup's dark theme. HTMX
swaps partials for the live margin indicator, the upsell panel and the split preview. The
template computes nothing the server also computes — displayed totals come from the server
so the number on screen is the number in the database.

**Views (entry layer).** The trust boundary. Every view authenticates, checks `request.user.role`
against the operation, and validates input through a Django form before anything reaches a
service. Django forms are where the "robust input validation" must-have is satisfied.

**Django admin.** Not an afterthought — it *is* the backend configuration area from SPEC §4
A2–A7. Registering the models gives products, price lists, tiers, category ceilings,
approval chains, warehouses and stock as working CRUD with search, filters and validation.
Customise with `list_display` and `list_filter`; do not rebuild these screens by hand.

**Services.** Own every business rule in SPEC §6. Read configuration from the database
rather than embedding constants. Return *explained* results, not bare numbers — the
approval screen must show why a quote was flagged, so `risk.py` returns the per-line
breakdown alongside the score.

**Persistence.** Models mirror DATA_MODEL.md. Multi-row changes run inside
`transaction.atomic()`.

## Domain boundaries

| Domain | Owns | Must not touch |
|---|---|---|
| **Catalogue** | Products, categories, variants, price lists, tiers | Quotation state |
| **Quotation** | Quotation, lines, discounts, totals, margin, stage | Approval decisions, stock |
| **Governance** | Ceilings, chains, risk score, approval steps, audit log | Pricing arithmetic (asks Catalogue) |
| **Inventory** | Warehouses, stock, shipping weights, split, backorders | Quotation pricing |
| **Billing** | Invoices, payments, subscriptions, schedules, proration | Stock |
| **Portal** | Token access, comments, change requests, counter-offers | Approval logic (calls Governance) |
| **Analytics** | Deal health, anomalies, reporting filters | Anything write-side |

A service module may **call** another service module, but may not reach around it into
another domain's models.

## URL / API responsibility boundaries

Server-rendered views are the default. HTMX endpoints return HTML partials, not JSON —
that is the point of using HTMX rather than a JSON API plus a client renderer.

No JSON API surface beyond what a screen needs. Odoo's "nice to have" mentions designing
backend APIs; that is satisfied by clean service interfaces and a well-modelled schema, not
by shipping unused endpoints.

## Authentication & authorisation

- **Custom user model from day one.** `AUTH_USER_MODEL` must be set in the very first
  migration. Swapping Django's user model after migrations exist is genuinely painful — this
  is the single most expensive mistake available in T-01.
- **Internal:** `django.contrib.auth` sessions, Django's password hashers, login/logout views.
- **Roles:** `role` field on User (`REP | MANAGER | FINANCE | ADMIN`), checked server-side
  in every view. A Rep attempting an approval is refused by the view, not by a hidden button.
- **Portal:** a signed, quotation-scoped token in the URL, verified with Django's
  `signing.TimestampSigner`. The portal view resolves the token to exactly one quotation and
  can act on nothing else. This is what makes it "a real, separate, restricted view" per
  PDF §7 — enforced server-side, not by hiding nav links.
- Portal views must **not** be behind `login_required`, and must never touch
  `request.user` — a customer has no user account.
- **DECISION NEEDED:** magic link vs portal email+password. PDF offers both. See ADR-004.

## External integrations

None required. PDF §7 leaves the stack free and marks multi-currency and multi-company as
bonuses. Odoo's guidance to "plan for offline or local solutions" argues against adding any
hosted dependency — with Django + SQLite the whole app runs with no network at all.

Email for sending the customer their portal link: **DECISION NEEDED** — Django's
`console.EmailBackend` or simply a copyable link in the UI. A copyable link has no failure
mode on stage. See ADR-004.

## Major data flow — quotation to cash

```
Rep builds quote
      │  pricing.py recomputes totals + margin on every HTMX edit
      ▼
Rep submits
      │  risk.py  → blended score + per-line breakdown
      ▼
  score > 0 ? ──no──► stage = APPROVED, skip to fulfilment
      │ yes
      ▼
approval.py creates the steps the chain rule requires
      │  Manager acts → audit row → Finance step if required → audit row
      ▼
stage = APPROVED
      │
      ├─► fulfilment.py  → split suggestion from live stock → accept/override
      │                    → reservations, backorder rows
      │
      └─► billing.py     → one-time lines → Invoice
                         → recurring lines → BillingScheduleEntry rows
      ▼
Portal: customer comments / counters
      │  negotiation.py → apply counter → risk.py re-scores
      ▼
  over threshold ? ──yes──► back into approval.py   (BR-6 loop)
      │ no
      ▼
Confirmed → fulfilment → payment recorded → invoice status updated
```

## Major risks and unknowns

| Risk | Impact | Mitigation |
|---|---|---|
| `AUTH_USER_MODEL` not set before the first migration | Painful mid-build reset | Set it in T-01, before any other model exists |
| Money drift through SQLite decimal aggregates | Wrong totals on stage | `Decimal` maths in services; no `Sum()` over money fields |
| Scope: 17 screens and 8 feature areas in the PDF | Nothing finishes | BACKLOG.md strictly ordered; P0 ships before P1 starts |
| Live margin in server-rendered templates | Feels sluggish, hurts AC-4 | HTMX partial swap on the line-items region only, not a full page reload |
| Django admin used for demo screens judges expect to be custom | Reads as unfinished | Admin is the *backend config* area only; the rep workspace, approval screen and portal are hand-built |
| Subscription proration is genuinely fiddly | Time sink late in the build | Scoped to quantity-change proration; plan changes and credit notes are BONUS |
| Blended score formula unspecified | Arbitrary-looking result | Must reproduce both PDF worked examples; approval screen shows the per-line breakdown |
| 4 people on one codebase | Merge conflicts at hour 20 | Models split by domain file; ownership tracks in BACKLOG.md; migrations announced before pushing |
| Migration conflicts between parallel tracks | Broken `migrate` for everyone | One person owns `makemigrations` per wave; never two migrations for the same app in flight |
| Demo depends on stock being short | Split never triggers, AC-5 unverifiable | Seed data deliberately makes single-warehouse fulfilment impossible for one order |
