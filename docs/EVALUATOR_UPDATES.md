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

## Round 2 — Scaffold up, blocking decisions closed

*Logged 05 Sep 2026*

**What landed since last round.**

The application now runs. Django 5.2 on SQLite, with a custom `User` model carrying the
four roles — Rep, Manager, Finance, Admin — and a `/health/` page whose every value is read
from the database on each request, so the round trip from URL to ORM to SQLite to template
is proved rather than asserted. The Django admin is up and registers the user model with
its role. We verified it the way it will actually be used: cloned the repository into a
clean directory, followed only the README, and had the app serving from a fresh database.

Alongside that we closed the four architectural decisions that were blocking the critical
path. These were the places where the problem statement genuinely does not specify an
answer, and we had deliberately left them open rather than guessing early.

- **The blended discount risk score.** The score is the total number of discount percentage
  points given away above ceiling across the quotation, where each line is measured against
  the stricter of its customer tier's ceiling and its category's. One badly-over line flags
  on its own; several slightly-over lines add up until they flag too. Both of the problem
  statement's worked examples reproduce exactly — the 18% service line against a 10% ceiling
  scores 8, and the 2 + 3 + 2 case scores 7.
- **The warehouse split.** Fill each line from the cheapest warehouse first and spill into
  the next, except that a warehouse able to cover the line alone ships it alone; the
  remainder becomes a backorder. We call it a heuristic in the architecture decision record
  and on the screen, because that is what it is.
- **Customer portal access.** A signed, quotation-scoped token in the URL. One token, one
  quotation, enforced server-side; anything else is a 403. No customer accounts and no
  email, so there is no live dependency during the demo.
- **The quotation stage machine.** One stage field, ten stages. What the customer sees in
  the portal is a display mapping over that field rather than a second field that can drift
  out of step with it.

**How we wrote the most important one.** The two worked examples from the problem statement
were written as unit tests **before** the formula was chosen, and the tests say so in their
own docstring: they are the specification, and the implementation is what has to change if
they disagree. They sit in the repository now, skipping with an explicit reason that names
the task that will make them pass.

**Two contradictions we found in our own documents and fixed rather than papered over.**
Our demo script had the customer countering at a discount that, under the routing rules we
had just written, would have required two approvers while the script showed only one — the
walkthrough would have stalled on stage. And our data model diagram allowed a rep to send a
quotation to a customer straight out of Draft, which would have let them route around the
approval chain entirely. Both are corrected, and both corrections are written down with the
reasoning, because a silently patched document teaches nobody anything.

**Currently building.** T-02, the full P0 schema, in one migration wave. Then T-03, the
seed script — which is the highest-leverage task in the build, because every one of our four
tracks needs data to work against.

**Blocked on / open decisions.** Nothing on the critical path. Three decisions remain open
by choice — the deal-health thresholds, the subscription proration basis, and the treatment
of tax — and all three block only SHOULD-priority features. We will close them when their
tasks come up rather than guessing now.

**Risks.**

- Only one machine has run the scaffold so far. All four of us need to clone and run it
  before we build on it in parallel.
- Tailwind and HTMX load from CDNs today. The venue network is a dependency we do not want
  during a five-minute demo, so vendoring them locally is on the backlog ahead of the
  rehearsal.
- The risk score deliberately ignores line value — a percentage-point rule, because the
  problem statement's examples are stated in percentage points with no prices at all. It is
  the most likely question we will be asked about our core rule, and we would rather answer
  it plainly than dress the formula up.

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
