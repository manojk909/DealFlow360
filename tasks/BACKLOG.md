# BACKLOG — DealFlow360

> **State: P0 and P1 complete.** Everything below marked ✅ has shipped; 218 tests pass.
> The only open item is **T-35**, the recorded demo. ADR-007, ADR-008 and ADR-009 — the
> three decisions this file deferred at T-00 — are now closed in `docs/DECISIONS.md`.

Ordered by priority, then by dependency. Tasks are vertical slices: each one ends with
something demonstrable, not a layer.

**Team: 1 member.** This is a solo build. An earlier version of this file assigned four
ownership tracks to four developers; that table has been removed rather than left to
describe a team that does not exist.

**Task order and dependencies below are unchanged.** They were derived from what each task
needs, not from who was going to do it, so they hold exactly as written for one person.
The critical path is still **T-06 → T-08 → T-09 → T-10 → T-13** — quotation and governance.
If that slips, everything else is decoration.

**Parallelism comes from subagents, not from people.** The same rule applies to them as
applied to four developers, and for the same reason: if two pieces of work would touch the
same file, they are one task. See CLAUDE.md's "Working with subagents" for what is safe to
fan out — pure logic in `core/services/`, tests for a service someone else is implementing,
templates for non-overlapping screens — and what never is: `makemigrations`, edits to
`core/models/`, `settings.py`, `config/urls.py`, `requirements.txt`.

Two consequences of being solo, worth stating so they are not rediscovered late:

- **Migration waves are cheap now.** The four-developer version of this plan feared two
  people generating migrations for `core` in parallel. One person cannot collide with
  themselves, so a schema change costs a `makemigrations` and nothing else.
- **Serialisation is the default, so scope discipline matters more.** Four tracks could
  absorb an over-ambitious backlog; one cannot. P0 ships before P1 starts, and T-18 (the
  eight acceptance criteria) is the gate.

---

# P0 — MUST HAVE

## Foundation

### T-00 — Close the blocking open decisions
**Goal.** Resolve the DECISION NEEDED ADRs that block P0 work, and record each one.
**Depends on.** Nothing. Runs in parallel with T-01.
**Priority.** ADR-005 first — it blocks T-09, which is on the critical path.
**Scope, in order of urgency:**
- **ADR-005** blended risk score formula and routing thresholds → blocks T-09, T-10.
- **ADR-006** warehouse split algorithm → blocks T-16.
- **ADR-004** portal access mechanism → blocks T-14, T-15.
- **ADR-010** quotation stage machine shape → blocks T-02's Quotation model work.
- ADR-008 (proration), ADR-007 (deal health), ADR-009 (tax / sales team / replenishment)
  are P1 and may be deferred until their tasks come up.

**Acceptance.**
- Each ADR above rewritten in place with Status `Accepted`, a Decision, a Reason and
  Consequences. No dangling open questions left above the decision.
- ADR-005's chosen formula has **two unit tests** written before any implementation,
  asserting both worked examples from PDF §10: the single 8-points-over service line must
  flag the quotation, and several lines 2–3 points over must accumulate into a flag.
- Each decision is explainable to a judge in one sentence. If it is not, it is too clever.
- SPEC.md BR-1 and BR-4 updated to state the chosen rule rather than "DECISION NEEDED".

### T-01 — Project scaffold and database connection
**Goal.** A running app with a working database connection and a health page proving both.
**Depends on.** Nothing. Resolve ADR-001 and ADR-002 as part of this.
**Acceptance.**
- `python manage.py runserver` serves a page.
- `AUTH_USER_MODEL` set in `settings.py` **before the first migration** — see ADR-003.
- `python manage.py migrate` applies cleanly against `db.sqlite3`.
- README records the setup commands another team member can follow from a clean clone.
- `.gitignore` excludes `db.sqlite3`, `__pycache__/`, `.venv/`, `.env`.
- ~~All four members have cloned and run it successfully.~~ **N/A — solo build.** Odoo's
  rules permit a team of one, and the "one member managing the repo is not enough"
  requirement targets multi-member teams: it exists so a four-person team cannot have
  one person do all the committing. With a single member there is no such thing to check.

### T-02 — Schema and migrations for the P0 entities
**Goal.** DATA_MODEL.md's MUST entities exist as tables.
**Depends on.** T-01.
**Scope.** User, CustomerTier, Customer, Category, Product, PriceListEntry,
CategoryDiscountCeiling, ApprovalChainRule, Quotation, QuotationLine, ApprovalStep,
AuditLog, Warehouse, Stock, FulfilmentAllocation, Invoice, Payment, PortalMessage,
SubscriptionPlan (MUST as of the A5 split — AC-1 requires a plan to persist;
BillingScheduleEntry stays out of P0 and lands with T-20).
**Acceptance.**
- Migration applies cleanly to an empty database.
- Unique constraint on Stock (product, warehouse) enforced at DB level.
- Invariants 8 and 11 from DATA_MODEL.md expressed as DB constraints where the engine allows.
- Schema announced to the team before pushing — schema churn is the main merge risk with 4 devs.

### T-03 — Seed script
**Goal.** `python manage.py seed_demo` produces exactly the DEMO.md seed state.
**Depends on.** T-02.
**Acceptance.**
- All four users, three tiers, three categories, category ceilings, approval chain rules,
  three customers, ≥8 products with costs, two warehouses, stock, five quotations,
  and at least one SubscriptionPlan (monthly) attached to Care Plan 2yr — AC-1
  cannot pass without a plan that persists and is visible on reload.
- **Main Warehouse holds 4 Laptop Pro 14, East Depot 10** — single-warehouse fulfilment of
  the 6-unit demo order is impossible. Without this, AC-5 cannot be demonstrated.
- One quotation with a backdated `last_activity_at` for the stalled-deal case.
- Idempotent: running twice yields the same state.
- This is the highest-leverage early task — every other track needs data to build against.

## Authentication

### T-04 — Internal auth and role-based access
**Goal.** FR-01. Signup, login, logout, session, four roles enforced.
**Depends on.** T-02.
**Acceptance.**
- Signup and login with hashed passwords.
- Session cookie is httpOnly and sameSite.
- Role stored on the User row, checked server-side on every action.
- A Rep attempting an approval action is refused **by the server**, not by a hidden button.
- Invalid input rejected with a visible message (Odoo must-have: robust validation).

## Core configuration (backend area)

### T-05 — Product, category and price list configuration
**Goal.** FR-03, FR-04. Admin can manage the catalogue.
**Depends on.** T-04.
**Note.** Build this with `django.contrib.admin` — register the models with `list_display`,
`list_filter` and `search_fields`. Do not hand-write CRUD screens. Same for T-06 and T-07.
**Acceptance.**
- CRUD for products: name, category, price, cost, unit, tax, description.
- CRUD for price list entries per tier.
- CRUD for subscription plans (name + interval), registered in Django admin. MUST as
  of the A5 split; the proration and cancellation *rules* on the plan are T-20's job.
- Validation: no negative prices, no missing category.
- A product created here is immediately selectable in the quotation builder.
- Note ADR-009 item 1 — tax is stored but its role in totals is undecided.

### T-06 — Discount tier, category ceiling and approval chain configuration
**Goal.** FR-05, FR-06, FR-07. The governance rules are **data**, not code.
**Depends on.** T-04.
**Acceptance.**
- CRUD for tiers with ceilings (Bronze 5 / Silver 10 / Gold 15 per the PDF example).
- CRUD for per-category ceilings per tier.
- CRUD for approval chain rules mapping score ranges to required approver levels.
- Changing a ceiling here changes routing behaviour on the next quotation, with no code change.
  **This is the acceptance test for CLAUDE.md's no-hardcoding rule.**

### T-07 — Warehouse and stock configuration
**Goal.** FR-08.
**Depends on.** T-04.
**Acceptance.**
- CRUD for warehouses with shipping cost weighting.
- Per-warehouse, per-product stock levels, editable.
- Available quantity displayed as on-hand minus reserved.

## Core business logic

### T-08 — Pricing and live margin engine
**Goal.** FR-10 (arithmetic), FR-11.
**Depends on.** T-05.
**Acceptance.**
- Line total = qty × unit price × (1 − discount).
- Order total applies the order-level discount after line discounts.
- Margin amount and percentage computed from product cost.
- Unit tests covering zero discount, full line discount, and a mixed line-plus-order discount.
- ~~Delete `_totals()` from `seed_demo.py` and call this service instead.~~ **Done.** The
  seed now calls `pricing.recompute_quotation()`; there is no arithmetic left in it.
- Server is the single source of truth for totals; the UI displays what the server computed.

### T-09 — Blended discount risk score
**Goal.** FR-12, BR-1. **The heart of the product.**
**Depends on.** T-06, T-08. **Blocked by ADR-005 — settle the formula first.**
**Acceptance.**
- Effective ceiling per line = the stricter of tier ceiling and category ceiling.
- Returns the score **and** a per-line breakdown of given / allowed / over-by — the
  approval screen cannot explain itself without the breakdown.
- Reproduces PDF §10 example 1: Gold customer, Hardware 12% (ceiling 15) passes,
  Service 18% (ceiling 10) is 8 points over and flags the quotation.
- Reproduces PDF §10 example 2: several lines 2–3 points over accumulate into a flag.
- Unit tests asserting both examples. These two tests are the specification. They already
  exist at `core/tests/test_risk.py` and currently skip; this task is what un-skips them.
- ~~Delete `_risk_score()` from `seed_demo.py` and call this service instead.~~ **Done.**
  The seed now calls `risk.score_for_quotation()`, so the seeded 8.00 comes from the same
  code path that scores a quotation at submit time.

### T-10 — Automatic approval routing and audit trail
**Goal.** FR-13, FR-15, FR-16, BR-2, BR-3.
**Depends on.** T-09.
**Acceptance.**
- On submit, the system reads ApprovalChainRule and generates the required steps itself.
- The rep never requests approval manually (AC-3).
- Finance step exists **only** when the chain requires it (PDF B4).
- Approve / Reject / Return-for-revision, each writing an AuditLog row with actor,
  timestamp and reason.
- Invariant 2 holds: a quotation with score > 0 cannot reach APPROVED with no ApprovalStep row.
- Mixed-category quotes route to the **highest** required level.

## Frontend — rep workspace

### T-11 — Quotation list and workspace shell
**Goal.** FR-09, B1, B2.
**Depends on.** T-04, T-03.
**Acceptance.**
- Quotation cards showing customer, amount, stage.
- Top nav: Quotations, Pipeline. Actions: Reload Data, Go to Back-end, Close Workspace.
- Selecting a card opens the builder.
- Dark theme matching the mockup; responsive (Odoo must-have).

### T-12 — Quotation builder screen
**Goal.** FR-10, B3.
**Depends on.** T-08, T-11.
**Acceptance.**
- Products selectable across Hardware / Services / Subscriptions.
- Quantity +/− controls; line and order discounts.
- Order lines with totals and a **live margin indicator** updating on every change.
- Submit routes to approval, or straight to fulfilment when no approval is needed.
- Discount above 100 or below 0 rejected.

### T-13 — Approval screen
**Goal.** FR-14, B4.
**Depends on.** T-10, T-11.
**Acceptance.**
- Blended risk score displayed with the per-line breakdown from T-09.
- Approval steps listed; Finance shown only when required.
- Approve / Reject / Return-for-revision, each demanding a reason.
- Full audit trail visible on the quotation.

## Customer portal

### T-14 — Portal access and restricted view
**Goal.** FR-02, FR-21. **PDF §7 requires this be genuinely separate and restricted.**
**Depends on.** T-11. **Blocked by ADR-004.**
**Acceptance.**
- Token-scoped access to exactly one quotation, enforced **server-side** (invariant 12).
- Changing the token in the URL to another quotation's id returns 403, not that quotation.
- Visually distinct from the internal workspace; no internal nav reachable.
- Status shown: Sent / Under Negotiation / Confirmed.
- Link copyable from the internal quotation screen.

### T-15 — Portal negotiation and the re-approval loop
**Goal.** FR-22, FR-23, FR-24, BR-6. **The best moment in the demo.**
**Depends on.** T-14, T-10.
**Acceptance.**
- Line-level comments and change requests, append-only.
- Counter-discount field; on submit the quotation re-scores.
- If over threshold, it **automatically** re-enters PENDING_APPROVAL with fresh steps (AC-7).
- If under threshold on confirm, it goes straight to fulfilment.
- Confirm Quotation works and is reflected internally.
- **A counter-discount replaces the targeted line's discount; it does not stack on top as a
  second order-level discount.** This is load-bearing for DEMO Flow B: Beta's 15% counter
  against a 10% Silver ceiling is 5 points over, which is the Manager-only band. Stacking it
  onto the line's existing 8% would give roughly 21 points over and pull in Finance, and
  DEMO B5 would stall. Recorded during T-03 because the seeded data depends on it.

## Fulfilment and billing

### T-16 — Warehouse split and backorders
**Goal.** FR-17, FR-18, FR-19, BR-4.
**Depends on.** T-07, T-10. **Blocked by ADR-006.**
**Acceptance.**
- Split computed from **live** stock, not a fixed rule.
- Shows warehouse, quantity from each, shipment count, estimated cost.
- Accept Suggested Split and Manual Override both work.
- Shortfall becomes a backorder row.
- Invariants 6, 7 and 8 hold — no allocation exceeds available stock, reserved never
  exceeds on-hand.
- With the seeded stock (4 + 10, order of 6) the split genuinely triggers.
- **Lines for non-stocked products must be skipped, not backordered.** Services and
  Subscriptions have no `Stock` rows at all — correctly, since you do not warehouse an
  engagement — so a naive implementation reports the Onsite Setup Service line as a total
  backorder and the fulfilment screen looks broken on stage. Found while seeding; decide it
  here rather than at the demo.

### T-17 — Order confirmation, invoice and payment
**Goal.** FR-20.
**Depends on.** T-16.
**Acceptance.**
- Confirm reserves stock and generates an invoice, inside one transaction.
- Payment recording updates invoice status (invariant 11: status is derived, never set).
- Overpayment rejected.
- AC-8 passes end to end.

### T-18 — P0 verification pass against the eight acceptance criteria
**Goal.** Prove AC-1 … AC-8 from SPEC.md §9 actually pass.
**Depends on.** T-17, T-15.
**Acceptance.**
- Each of the eight steps run manually against seeded data, result recorded.
- Any failure becomes a task, not a note.
- This is the gate: **P1 does not start until this passes.**

---

# P1 — IMPORTANT (SHOULD HAVE)

### T-19 — Upsell and cross-sell panel
**Goal.** FR-28, B5. Required by AC-4 even though its config screen is Optional (see
DECISIONS.md cross-check note).
**Depends on.** T-12.
**Acceptance.** Ranked suggestions from ProductPair co-purchase counts and the promoted
flag; margin delta shown per suggestion; minimum margin threshold respected; Add to Quote
and Dismiss; margin indicator updates **immediately** on add.

### T-20 ✅ — Subscription lines and hybrid billing
**Goal.** FR-29, FR-30, FR-31, BR-5. **Blocked by ADR-008.**
**Depends on.** T-17.
**Acceptance.** One-time and recurring lines shown separately on one order; billing
schedule for recurring lines; proration on mid-cycle quantity change; invariants 9 and 10
hold. AC-6 passes.

### T-21 ✅ — Deal health and anomaly dashboard
**Goal.** FR-33, B9. **Blocked by ADR-007.**
**Depends on.** T-18.
**Acceptance.** Stalled deals from `last_activity_at`; discount anomalies against rep
history; click-through to the quotation. Ship stalled-deal detection alone if ADR-007 is
still open, labelled honestly.

### T-22 ✅ — Pipeline Kanban view
**Goal.** FR-27, B1.
**Depends on.** T-11.
**Acceptance.** Quotations grouped by stage; opening a card opens the builder.

### T-23 ✅ — Reporting with filters
**Goal.** FR-34, A7. **See ADR-009 item 2 — no Sales Team entity is defined.**
**Depends on.** T-18.
**Acceptance.** Filters for Period, Rep, Approval Status, Product/Category; results
reflect real data.

### T-24 ✅ — Consolidate remaining backorder
**Goal.** FR-35, B6.
**Depends on.** T-16.
**Acceptance.** When stock arrives for a backordered line, the prompt appears
**automatically**; accepting consolidates the remaining quantity.

### T-25 ✅ — Product variants
**Goal.** FR-26, A2.
**Depends on.** T-05.
**Acceptance.** Attribute, values and extra prices; variant selectable on a quotation line
and reflected in the price.

### T-26 — Input validation and responsive pass
**Goal.** Odoo's stated must-haves, swept across the whole app.
**Depends on.** T-18.
**Acceptance.** Every form validates and shows errors; no layout breaks between mobile and
desktop; consistent colour scheme; menu spacing checked. **Do not skip this — it is
explicitly scored regardless of features.**

---

# P2 — BONUS

### T-26a — Vendor Tailwind and HTMX locally instead of CDN
**Noticed during T-01, not fixed there.** `core/templates/core/base.html` pulls Tailwind
and HTMX from CDNs. Odoo's guidance is to "plan for offline or local solutions and don't
rely entirely on internet connectivity", and the venue wifi is a live dependency during a
five-minute demo. A minimal inline fallback stylesheet is in `base.html` so the app stays
legible if the CDNs are unreachable, but it is not the real theme.
**Fix.** Download `tailwind.js` and `htmx.min.js` into `core/static/vendor/` and serve
them with `{% static %}`. Ten minutes of work; do it before the demo rehearsal (T-35), not
after.

### T-27 ✅ — Upsell rule configuration screen (A6, PDF marks it Optional)
### T-28 ✅ — Report export to PDF / XLS (FR-38)
### T-29 ✅ — Automated nudge or escalation from a deal health alert (FR-39)
### T-30 ✅ — Subscription cancel/modify with credit note (FR-32)
### T-31 ✅ — Replenishment rules per warehouse (FR-36, see ADR-009 item 3)
### T-32 — Multi-currency or multi-company (FR-40, PDF §7 explicitly a bonus)

---

# Demo preparation — NOT optional, these are PDF §8 deliverables

### T-33 — One-page architecture diagram
**Depends on.** T-18. Data model plus module connections, on one page.

### T-34 — "What we would build next" note
**Depends on.** T-18. Honest list of what is unbuilt and why. Draw it from the open
Decision Needed items and the untouched P2 tasks.

### T-35 — Rehearse and record the 5-minute demo
**Depends on.** T-18.
**Acceptance.** Reset script run, full DEMO.md walkthrough performed twice, both flows
end to end, recording completed. **Do this at hour 20, not at 09:45.**
