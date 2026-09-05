# DECISIONS — DealFlow360

ADR log. Only decisions already clear from the repository, the problem statement, or the
event rules are recorded as Accepted. Everything the PDF leaves open is listed as
**Decision Needed** rather than quietly resolved.

---

## ADR-001 — Application stack

**Status:** Accepted
**Date:** 2026-09-05

**Context.** `DealFlow360/` was empty, so nothing constrained the choice. PDF §7 allows any
language, framework and database. Available on the dev machine: Python 3.10.12, pip, Node
22, Java 11, git. Not available: Docker, `psql`, Go. Roughly 22 hours remain, with 4
developers. Next.js + Prisma and FastAPI + React were both considered and rejected — see
Consequences.

**Decision.** **Django 5 on Python 3.10**, Django ORM, Django templates with HTMX for
interactivity, Tailwind via CDN for styling, `django.contrib.auth` for authentication, and
Django's built-in test runner.

**Reason.** Django is the only option of the three that ships the parts of this problem we
would otherwise hand-write. `django.contrib.admin` covers the entire backend configuration
area (SPEC §4 A2–A7) — products, price lists, discount tiers, category ceilings, approval
chains, warehouses, stock — as model-driven CRUD with search, filtering and validation. That
is roughly seven screens we do not build. `django.contrib.auth` supplies sessions, password
hashing and login views, already correct. One codebase, one process, one language, so there
is no REST layer to write and no type boundary to keep in sync across a 4-person team.

**Consequences.**
- The rep workspace, approval screen, fulfilment screen and portal are hand-built templates.
  Django admin is for the *configuration* area only; leaning on it for screens judges expect
  to be custom would read as unfinished.
- The live margin indicator (AC-4) is a server round trip. HTMX swapping only the line-items
  partial keeps it fast enough; a full page reload on every quantity change would not be.
- FastAPI was rejected: no ORM, no auth, no admin, and a separate React frontend, meaning
  ~60 hand-written endpoints plus duplicate Pydantic and TypeScript models that drift.
- Next.js + Prisma was rejected on team fluency, not on merit.
- DATA_MODEL.md is stack-neutral and was unaffected by this decision.

---

## ADR-002 — Database engine

**Status:** Accepted
**Date:** 2026-09-05

**Context.** The invigilator instructed teams to use a local database. `psql` is not
installed and Docker is unavailable, so local PostgreSQL would mean installing and
configuring a database service on four laptops during a 22-hour build. Odoo's own guidance
says to "plan for offline or local solutions and don't rely entirely on internet
connectivity".

**Decision.** **SQLite** — Django's default backend, one file at `db.sqlite3`.

**Reason.** Zero configuration and zero installation: it is already what Django uses out of
the box, and it is unambiguously local — a single file inside the repository folder. Same
Django ORM, same models, same migrations as any other backend, so nothing about the data
model or the services layer is compromised. Concurrency limits are irrelevant at demo scale.

**Consequences.**
- **SQLite has no native decimal type.** Use `DecimalField` on models and perform all money
  arithmetic in Python with `Decimal` inside `core/services/`. Do **not** sum money through
  SQLite aggregates — `Sum()` over a `DecimalField` can return a float and drift. This
  applies to line totals, order totals, margins and the risk score, which is most of the
  arithmetic in this application.
- `db.sqlite3` is gitignored. The database is rebuilt from migrations plus the seed script,
  which also makes the demo reset trivial.
- Avoid Postgres-only field types and raw SQL, so the backend stays swappable if it ever
  needs to be.

---

## ADR-003 — Authentication approach

**Status:** Accepted
**Date:** 2026-09-05

**Context.** SPEC.md FR-01 requires internal signup/login with four roles. PDF A1 specifies
"standard credentials". No identity provider is required by the problem statement.

**Decision.** `django.contrib.auth` with a **custom user model** carrying a `role` field
(`REP | MANAGER | FINANCE | ADMIN`). Django sessions and password hashers as shipped.
Authorisation checked in the view layer on every action.

**Reason.** Django's auth is already written and already correct — password hashing, session
handling and login views are exactly the code you do not want a tired team writing at 3am.
Role-based access is itself a scored item; PDF §6 lists it under industry-ready system
thinking.

**Consequences.**
- **`AUTH_USER_MODEL` must be set in `settings.py` before the first migration runs.**
  Changing Django's user model after migrations exist is genuinely painful. This is the most
  expensive mistake available in T-01 and the reason it is called out there explicitly.
- Roles live on the User row rather than in Django Groups. Groups are more idiomatic, but a
  single `role` field is simpler to read in a view and matches DATA_MODEL.md directly.
- Portal visitors are not users. Portal views must not use `login_required` and must never
  read `request.user`.
- No SSO and no password reset; neither is required by the spec.

---

## ADR-004 — Customer portal access mechanism

**Status:** Decision Needed
**Date:** 2026-09-05

**Context.** PDF A1 offers two options without choosing: "Customers access their quotations
through a portal login (magic link, or email and password)." PDF §7 additionally requires
the portal to be a real, separate, restricted view. PDF §5 says "Customer receives the
quotation link", which leans toward a link.

**Options.**
1. Signed quotation-scoped token in the URL. No customer accounts, no email infrastructure,
   nothing to fail on stage. Copy the link from the internal UI and open it.
2. Customer accounts with email + password. More conventional, but adds a registration
   flow and a second user table for no scored benefit.

**Recommendation.** Option 1, using Django's `signing.TimestampSigner` to sign a
quotation-scoped token, with the link copyable from the internal quotation screen rather
than emailed. Real SMTP is a live dependency during a demo and buys nothing; Django's
`console.EmailBackend` prints to stdout if sending needs to be demonstrated at all.

**Open sub-question.** Whether to send actual email at all. Not required by any acceptance
criterion.

**Blocks:** T-13 (portal access), T-14 (portal negotiation).

---

## ADR-005 — Blended discount risk score formula and routing thresholds

**Status:** Decision Needed
**Date:** 2026-09-05

**Context.** PDF §10 explains the *behaviour* of the blended score in detail and gives two
worked examples, but never states the arithmetic or the routing thresholds. This is the
single most important unspecified item in the problem statement — SPEC.md BR-1 and BR-2
both depend on it, and it drives AC-2, AC-3 and AC-7.

**Constraints any chosen formula must satisfy** (both come straight from PDF §10):
1. A Gold customer's Service line at 18% against a 10% ceiling — 8 points over — must flag
   the whole quotation for approval, even though 15% is allowed at tier level.
2. Several lines each slightly over (2, 3, 2 points) must accumulate into a flag, because
   "small violations spread across many lines cannot slip through unnoticed".

Both imply the score combines a per-line severity signal with an order-wide aggregate, and
that the effective ceiling for a line is the stricter of tier and category.

**Also needed.** The score ranges that map to "Manager only" versus "Manager then Finance".
PDF A3 states these are configurable per SPEC.md FR-07, so whatever is chosen must live in
ApprovalChainRule rows, not in code.

**Consequence of getting this wrong.** A formula that cannot explain itself will look
arbitrary to a judge. Whatever is chosen, the approval screen must show the per-line
given / allowed / over-by breakdown that produced the number.

**Blocks:** T-08 (risk score), T-09 (approval routing).

---

## ADR-006 — Warehouse split algorithm

**Status:** Decision Needed
**Date:** 2026-09-05

**Context.** PDF A4 says shipping cost weighting is "used by the auto split logic to
minimize number of shipments"; B6 requires showing warehouse, quantity, estimated shipment
count and cost. The method is not specified. SPEC.md BR-4.

**What is fixed by the PDF.** The objective is minimising shipments, weighted by shipping
cost. Manual override must be possible. Shortfalls become backorders. A "Consolidate
Remaining Backorder" prompt appears automatically when stock arrives mid-fulfilment.

**What is open.** Whether to optimise properly or use a heuristic; how shipping weight and
shipment count trade off against each other; tie-breaking between warehouses.

**Note.** Whatever is chosen must be honest about being a heuristic if it is one. PDF §7
requires this to be real application logic — a heuristic that is documented as a heuristic
qualifies; a hardcoded split for the demo does not.

**Blocks:** T-15 (fulfilment split).

---

## ADR-007 — Deal health thresholds

**Status:** Decision Needed
**Date:** 2026-09-05

**Context.** PDF B9 defines stalled deals as "quotations inactive for more than a
configured number of days" — configurable, but no default given. Discount anomalies are
"a discount well above a rep's historical average" — "well above" is not quantified. Also
listed: delivery promise slippage indicators, with no definition of the promise date.

**Open.** The default stall window; the anomaly threshold and how a rep's historical
average is computed (over what window, which quotations count); what a delivery promise is
in the data model, since no promise-date field appears anywhere in the PDF.

**Note.** Deal health is SHOULD, not MUST. If this is still undecided when the P1 work
starts, the dashboard can ship with stalled-deal detection only and the anomaly panel
marked incomplete — honestly labelled, per the integrity rule.

**Blocks:** T-19 (deal health dashboard).

---

## ADR-008 — Subscription proration method

**Status:** Decision Needed
**Date:** 2026-09-05

**Context.** PDF A5 requires "proration rules for mid cycle quantity or plan changes" and
B7 requires handling "mid cycle proration when quantity changes". The basis — daily
pro-rata, whole-period, or something else — is not specified. Cancellation triggers "an
automatic partial refund or credit note" with no rule for computing the amount.

**Open.** Proration basis; whether a partial refund and a credit note are alternatives or
the same thing expressed differently; whether unused time is refunded or credited forward.

**Note.** SPEC.md scopes proration to quantity changes (SHOULD); plan changes and credit
notes are BONUS. A defensible, documented simple rule beats an elaborate one that is not
finished.

**Blocks:** T-17 (subscription billing).

---

## ADR-009 — Fields named by the PDF but left undefined

**Status:** Decision Needed
**Date:** 2026-09-05

**Context.** Three items appear in the problem statement without enough definition to
implement:

1. **Tax.** PDF A2 lists Tax as a product field. No tax rules, rates or treatment are
   given. Open: whether totals are tax-inclusive or exclusive, and whether tax enters the
   margin calculation. Currently `tax_pct` exists on Product but participates in nothing.
2. **Sales Team.** PDF A7 lists "Sales Team / Rep" as a reporting filter, but no team
   entity, membership or hierarchy is described anywhere else. Open: whether to model a
   Team entity or filter by rep only.
3. **Replenishment rules.** PDF A4 says "Configure stock levels and replenishment rules per
   warehouse" without defining what a replenishment rule does. Open: whether this is a
   reorder point, an auto-restock action, or display-only.

**Note.** All three are peripheral to the eight acceptance criteria. The lazy correct
answer for each is probably the smallest thing that satisfies the words in the PDF.

**Blocks:** T-04 (product config), T-20 (reporting).

---

## ADR-010 — Quotation stage machine shape

**Status:** Decision Needed
**Date:** 2026-09-05

**Context.** DATA_MODEL.md proposes a stage enum. The PDF names stages across several
sections without listing them in one place: Draft and Pending Approval (B2), Sent /
Under Negotiation / Confirmed (B8, portal-visible), plus approved, fulfilment, invoiced
and paid states implied by §5 and §9.

**Open.** Whether the portal statuses are distinct stages or a separate field on the
quotation; whether `SENT` is a stage or a flag on `APPROVED`; whether `REJECTED` is
terminal or returns to `DRAFT` (B4 offers "return for revision" as a distinct action from
reject, which suggests they differ).

**Note.** Invariants 1, 2, 5 and 13 in DATA_MODEL.md constrain this regardless of shape —
whatever stage machine is chosen must make those invariants expressible.

**Blocks:** T-06 (quotation model).

---

## Cross-document consistency check — 2026-09-05

Run after all documents were created (Step 12).

**Verified consistent.**
- SPEC.md §4 covers every module in PDF §4 (A1–A7, B1–B9). Priorities follow the PDF's own
  language: A6 marked BONUS because the PDF marks it Optional; multi-currency marked BONUS
  because PDF §7 says so explicitly.
- SPEC.md §9 acceptance criteria are the PDF's §9 Quick Test Flow, unaltered.
- ARCHITECTURE.md's domain modules map 1:1 onto SPEC.md's business rules BR-1…BR-8.
- DATA_MODEL.md carries an entity for every SPEC.md functional requirement.
- DEMO.md's Flow A covers AC-1…AC-6 and AC-8; Flow B covers AC-7. All eight are demonstrated.
- BACKLOG.md P0 covers every MUST in SPEC.md §7; no P0 task depends on an unresolved
  Decision Needed except T-08/T-09 (ADR-005), which is flagged as the first thing to settle.
- CURRENT.md points at T-01, which has no dependencies.

**Contradictions found:** none between documents.

**Ambiguities carried forward:** ADR-004 through ADR-010 above. All originate in the
problem statement, not in these documents. None has been silently resolved.

**One tension worth naming.** SPEC.md marks the upsell panel (B5) SHOULD, because PDF A6 —
its configuration screen — is explicitly Optional. But the panel appears in the PDF's own
acceptance test as AC-4. It is therefore built as P1 rather than P2: the *panel* is
effectively required by the test flow even though its *config screen* is optional. This is
a reading of the PDF, not an invention, and is recorded here so it can be challenged.
