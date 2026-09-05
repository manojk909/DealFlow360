# Evaluator Update Log — DealFlow360

**Odoo Hackathon 2026 · Final Round · Team 317**
Problem statement: **DealFlow360 — An Intelligent, Self-Governing Sales Operations Platform**
Evaluator: Karan Israni (kais@odoo.com · GitHub `kais-odoo`, `hackathon-odoo`)

> Read the current round's section aloud at each check-in. Add a new round section as the
> hackathon progresses; do not rewrite earlier rounds — the history is the point.

---

## Round 1 — Tech stack and approach

*Logged 05 Sep 2026, ~11:45 IST*

### What we are building

A B2B sales platform that governs itself. Rather than a quote-to-invoice form, the system
enforces pricing discipline: it reads every quotation line against its own category
discount ceiling, computes a blended risk score, and routes the deal for approval on its
own. It splits fulfilment across warehouses based on live stock, keeps one-time and
recurring subscription lines reconciled on a single order, and gives the customer a
separate, restricted portal where they can negotiate — with any counter-offer that breaks
a threshold automatically re-entering the approval chain.

### Tech stack

| Layer | Choice | Why we chose it |
|---|---|---|
| **Framework** | **Django 5** (Python 3.10) | Django ships the parts of this problem we would otherwise hand-write. `django.contrib.admin` gives us the entire backend configuration area — products, price lists, discount tiers, category ceilings, approval chains, warehouses, stock — as working CRUD driven straight from our models. That is roughly seven screens we do not build by hand, and those hours go into the business logic the problem statement says it is actually testing. `django.contrib.auth` supplies sessions and password hashing already correct. |
| **Database** | **SQLite** (`db.sqlite3`) | A single local file in the repository — local in the strictest sense, as instructed. It is Django's default backend, so there is nothing to install or configure and no database service to keep running on four laptops. Same ORM, same models, same migrations as any other backend, so nothing about our data model is compromised. |
| **ORM** | **Django ORM + migrations** | One model definition drives the schema, the migrations, the admin screens and the forms. With four people working in parallel, a single source of truth for the data model prevents the hour-18 bug where two developers disagree about a field name. |
| **Interactivity** | **Django templates + HTMX** | The live margin indicator and the upsell panel need to update without a page reload. HTMX does that by swapping a rendered partial — one script tag, no build step, no second codebase. A React SPA would have meant a separate frontend and a REST layer we would have to write and keep in sync. |
| **Styling** | **Tailwind (CDN)** | The provided mockup is a dark-theme design. Tailwind reproduces it quickly and keeps the colour scheme consistent across all 17 screens, which the rules list as a must-have — without adding a Node build step to a Python project. |
| **Auth** | `django.contrib.auth`, custom user with a `role` field | Four roles — Rep, Manager, Finance, Admin — enforced server-side on every view, not by hiding buttons. Runs entirely offline, which the rules explicitly advise planning for. |
| **Portal access** | Separate Django app, signed quotation-scoped token | The customer portal is its own app with its own URL prefix, its own base template and its own access check. A token resolves to exactly one quotation and nothing else. The problem statement requires this be a genuinely separate, restricted view rather than an internal screen relabelled. |
| **Tests** | Django's built-in test runner | No extra dependencies. We test the logic that matters — the risk score, the split algorithm, the pricing engine — rather than building test infrastructure we have no time to maintain. |

**One deliberate engineering note.** SQLite has no native decimal type, so all money
arithmetic happens in Python with `Decimal` inside our services layer rather than through
database aggregates, which can return floats and drift. Line totals, margins and the risk
score are all money maths, so this mattered enough to decide up front rather than debug later.

**Why not the alternatives.** We evaluated FastAPI and Next.js. FastAPI would have meant
writing roughly sixty endpoints plus a separate React frontend, with entity definitions
duplicated in Pydantic and TypeScript and nothing keeping them in sync — a real risk with
four people editing in parallel. Next.js was rejected on team fluency rather than merit. We
chose the stack that lets four developers write business logic instead of plumbing.

### Why this problem statement

We chose DealFlow360 over the accounting and HR options for three reasons. Its features are
independently demonstrable, so partial progress is still a coherent product. Its logic is
genuinely interesting — discount governance and warehouse splitting are real operational
problems, not CRUD. And it has the smallest UI surface of the three, which leaves us more
hours for business logic, which is what the problem statement says it is actually testing.

### How we are working

Documentation-first. Before writing application code we produced a structured
specification, an architecture, a data model with explicit invariants, a demo plan, an ADR
log, and a prioritised backlog. All of it is in this repository under `docs/` and `tasks/`.

Where the problem statement leaves something genuinely unspecified — the exact risk score
arithmetic, the split algorithm, the proration basis — we recorded it as an open decision
in `docs/DECISIONS.md` rather than inventing an answer and hoping nobody asked.

Four members, four parallel tracks: configuration and catalogue; quotation and governance;
portal and workspace; inventory and billing. All four commit to the repository.

### Status at this round

Documentation system complete. Application implementation has not started.
Next task: **T-01 — project scaffold and database connection.**

---

## Round 2 — *(to be filled in)*

**What landed since last round:**

**Currently building:**

**Blocked on / open decisions:**

**Risks:**

---

## Round 3 — *(to be filled in)*

**What landed since last round:**

**Currently building:**

**Blocked on / open decisions:**

**Risks:**

---

## Round 4 — *(to be filled in)*

**What landed since last round:**

**Currently building:**

**Blocked on / open decisions:**

**Risks:**

---

## Final submission summary — *(to be filled in)*

**Working end to end:**

**Built but not demonstrated:**

**Not built, and why:**

**What we would build next:**
