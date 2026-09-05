# DECISIONS — DealFlow360

ADR log. Only decisions already clear from the repository, the problem statement, or the
event rules are recorded as Accepted. Everything the PDF leaves open is listed as
**Decision Needed** rather than quietly resolved.

---

## ADR-001 — Application stack

**Status:** Accepted
**Date:** 2026-09-05

**Context.** `DealFlow360/` was empty, so nothing constrained the choice. PDF §7 allows any
language, framework and database. Available on the dev machine: Python **3.13.5** (this ADR
originally recorded 3.10.12, which was wrong — corrected at T-02), pip, Node
22, Java 11, git. Not available: Docker, `psql`, Go. Roughly 22 hours remain, with 4
developers. Next.js + Prisma and FastAPI + React were both considered and rejected — see
Consequences.

**Decision.** **Django 5.2 on Python 3.13** (the code targets 3.10+, which Django 5.2
supports through 3.13), Django ORM, Django templates with HTMX for
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

**Status:** Accepted
**Date:** 2026-09-05

**Context.** PDF A1 offers two options without choosing: "Customers access their quotations
through a portal login (magic link, or email and password)." PDF §7 additionally requires
the portal to be a real, separate, restricted view. PDF §5 says "Customer receives the
quotation link", which leans toward a link. Customer accounts with email and password were
the alternative considered — see Consequences.

**Decision.** A **signed, quotation-scoped token in the URL** — `/portal/<token>/` —
produced with Django's `signing.TimestampSigner` over the quotation's id, stored on
`Quotation.portal_token`, and **copied from the internal quotation screen** by the rep.
No customer accounts, no passwords, and **no email is sent**. Tokens carry no expiry:
`max_age` is deliberately not enforced.

**Reason.** The PDF's own workflow step 8 is "customer receives the quotation link", and a
signed link is the smallest thing that satisfies it. It also gives the restriction property
for free: the token resolves to exactly one quotation and to nothing else, so FR-02 — a
customer sees only their own quotation — is enforced by the URL itself rather than by a
permission check somebody could forget to write. Customer accounts would add a registration
flow, a second identity table and a login screen for no scored benefit, and would blur the
line PDF §7 draws between the portal and the internal app.

**Consequences.**
- Portal views take the token from the URL, resolve it to exactly one Quotation, and must
  **never** read `request.user` or sit behind `login_required` (ADR-003, invariant 12).
- A tampered, unsigned or unknown token returns **403** — never the quotation, and never a
  redirect to the internal login page. BACKLOG T-14 asserts exactly this.
- Portal actions have no `User` row, so `AuditLog.actor_id` is null for them and
  attribution runs through the quotation's Customer, as DATA_MODEL.md "Ownership" already
  states.
- **The email sub-question is closed: no email at all.** No acceptance criterion AC-1…AC-8
  requires it, SMTP is a live network dependency in the middle of a demo, and a copyable
  link has no failure mode. If sending ever has to be shown, Django's
  `console.EmailBackend` prints the link to stdout — a five-minute change, not a P0 task,
  and not built unless time is free.
- **No token expiry, stated openly.** `TimestampSigner` stamps the token but the portal
  does not pass `max_age`, so links do not go stale. An expired link mid-demo is pure
  downside with no upside here. The property being relied on is that a signed token is
  unguessable and non-forgeable, not that it is short-lived. That is a hackathon posture and
  is recorded as one rather than claimed to be production-grade.
- One quotation, one token, for the life of the quotation. Rotation is not built.

**Blocks:** T-14 (portal access and restricted view), T-15 (portal negotiation and the re-approval loop). **Unblocked.**

---

## ADR-005 — Blended discount risk score formula and routing thresholds

**Status:** Accepted
**Date:** 2026-09-05

**Context.** PDF §10 explains the *behaviour* of the blended score in detail and gives two
worked examples, but never states the arithmetic or the routing thresholds. This is the
single most important unspecified item in the problem statement — SPEC.md BR-1 and BR-2
both depend on it, and it drives AC-2, AC-3 and AC-7. Two constraints come straight from
PDF §10 and any formula had to satisfy both: a Gold customer's Service line at 18% against
a 10% ceiling — 8 points over — must flag the whole quotation even though 15% is allowed at
tier level; and several lines each only slightly over (2, 3, 2 points) must accumulate into
a flag, because "small violations spread across many lines cannot slip through unnoticed".

**Decision.**

> **The blended risk score is the total number of discount percentage points given away
> above ceiling across the whole quotation, where every line is measured against the
> stricter of its customer tier's ceiling and its category's.**

Precisely, in `core/services/risk.py`:

1. **Given discount for a line** — its own discount combined with any order-level discount:
   `given = 100 × (1 − (1 − line_discount_pct/100) × (1 − order_discount_pct/100))`.
   An order-level discount is a real discount on every line, so it is scored as one.
2. **Allowed discount for a line** — `min(tier.max_discount_pct, categoryCeiling.max_pct)`.
   This is DATA_MODEL.md invariant 14, and it is the mechanism behind the PDF's Gold example.
3. **Over-by for a line** — `max(0, given − allowed)`. A line inside its ceiling contributes
   nothing; there is no credit for being under.
4. **Score** — `Σ over_by` across every line, as `Decimal`, quantised to `0.01`.
5. **Flagged** — `score > 0`. Any overage at all requires approval, which is what makes
   DATA_MODEL.md invariant 2 meaningful.
6. The service returns the score **and** a per-line breakdown of given / allowed / over-by,
   because the approval screen (FR-14) cannot explain the number without it.

**Service API** — fixed here so T-09 and T-10 build against the same shape, and asserted by
`core/tests/test_risk.py`:

```python
score_quotation(
    lines,                    # iterable of dicts: line_id, label, category, discount_pct
    tier_max_discount_pct,    # Decimal — CustomerTier.max_discount_pct
    category_ceilings,        # dict: category name -> Decimal, resolved for that tier
    order_discount_pct=Decimal("0"),
) -> RiskResult               # .score: Decimal   .flagged: bool   .breakdown: list[RiskLine]
                              # RiskLine: .line_id .label .category
                              #           .given_pct .allowed_pct .over_by_pct
```

Plain data in, plain data out — no ORM objects and no request, per ARCHITECTURE.md.

**Routing thresholds — ApprovalChainRule rows, not code.** SPEC.md FR-07 and CLAUDE.md's
no-hardcoding rule both require these to be configuration. T-03 seeds exactly three rows:

| `score_min` | `score_max` | `requires_manager` | `requires_finance` | Meaning |
|---|---|---|---|---|
| 0.00 | 0.00 | false | false | Clean quotation — no approval, straight to fulfilment |
| 0.01 | 7.99 | true | false | Sales Manager only |
| 8.00 | 9999.99 | true | true | Sales Manager, then Finance |

Ranges are inclusive at both ends and must tile the whole space with no gap and no overlap.
A score matching no rule is a configuration error and must fail loudly rather than silently
skip governance.

**Reason.** Adding up how many points each line went over its own ceiling is the shortest
rule that does everything PDF §10 asks for. Each line carries its own severity signal —
measured against its own ceiling, never one order-wide limit — and the order-wide aggregate
is simply their total, so one badly-over line flags on its own and many slightly-over lines
add up until they flag too. A judge can be told it in one sentence and can then check it by
hand on the approval screen: the breakdown column adds up to the number at the top.

The Finance threshold of 8.00 is not arbitrary either. It is the PDF's own worked example of
a serious overage: anything as bad as the Setup-Service line the PDF chose to complain about
goes to Finance, while the PDF's other example — three lines at 2, 3 and 2 — totals 7 and
stops at the Manager. Both bands are exercised by the seeded data.

**Rejected: weighting each line's overage by its share of order value.** It sounds more
sophisticated, but PDF §10's examples are stated purely in percentage points, with no
quantities and no prices, so a value-weighted score cannot reproduce them — the 8-point
service line would be diluted almost to nothing beside six laptops. The examples are the
specification; the formula follows them.

**Consequences.**
- `core/tests/test_risk.py` was written **before** any implementation and asserts both PDF
  examples against the API above. Those two tests are the specification for T-09: they are
  to be made to pass, not edited to match whatever T-09 happens to produce.
- All arithmetic is `Decimal` (ADR-002). No floats, and no SQLite `Sum()` over money or
  percentage columns.
- The score ignores line value and quantity. A judge may well ask; the honest answer is that
  the PDF's worked examples are price-free, and that the live margin indicator (B3) is the
  separate signal carrying value. A deliberate simplification, recorded as one.
- Changing a ceiling row or a chain rule in Django admin changes routing on the next
  quotation with no code change. That is the acceptance test for CLAUDE.md's no-hardcoding
  rule (BACKLOG T-06).
- `Quotation.risk_score` is snapshotted at submit, so the approval screen shows the score the
  approver actually acted on rather than a recomputed one.
- **A mismatch with DEMO.md Flow B, found here and since resolved.** DEMO.md B3 had Beta
  Industries (Silver, tier ceiling 10%) counter at **20%**, which is 10 points over and
  therefore lands in the Manager **and** Finance band — yet DEMO.md B5 showed only the Manager
  approving, and B6 then expected Confirm to work. The routing was right; the script was one
  step short. **Resolved by editing DEMO.md B3 down to 15%** — 5 points over, still plainly
  "a bigger discount" for AC-7, still re-enters approval automatically, but inside the
  Manager-only band so B5 and B6 hold as written. Flow A already demonstrates the full
  Manager → Finance chain, so nothing is lost. The alternative — keep 20% and add a Finance
  approval to B5 — is recorded in DEMO.md as a rehearsed option, not the default.
- Note that the counter is a live presenter action in the portal, not seeded data. T-03 seeds
  the Beta quotation and its portal token; the 15% is typed on stage.

**Blocks:** T-09 (blended discount risk score), T-10 (automatic approval routing and audit trail). **Unblocked.**

---

## ADR-006 — Warehouse split algorithm

**Status:** Accepted
**Date:** 2026-09-05

**Context.** PDF A4 says shipping cost weighting is "used by the auto split logic to
minimize number of shipments"; B6 requires showing warehouse, quantity, estimated shipment
count and cost. The method is not specified. SPEC.md BR-4. What the PDF does fix: the
objective is minimising shipments, weighted by shipping cost; manual override must be
possible; shortfalls become backorders; and a "Consolidate Remaining Backorder" prompt
appears automatically when stock arrives mid-fulfilment.

**Decision.** A greedy heuristic — **and it is called a heuristic, in this ADR, on the
fulfilment screen and in the demo script.** It is not an optimiser and is not described as
one.

> **Fill each line from the cheapest warehouse first and spill into the next cheapest,
> except that if the cheapest warehouse can cover the whole line by itself it ships alone;
> whatever is left over becomes a backorder.**

Per quotation line, independently, in `core/services/fulfilment.py`:

1. Rank the warehouses holding that product by **ascending `shipping_cost_weight`**,
   tie-broken by **descending available quantity** (`qty_on_hand − qty_reserved`), then by
   ascending warehouse id so the result is deterministic.
2. **Single-shipment shortcut.** If the cheapest warehouse alone has enough available stock
   for the whole line, allocate the entire line there — one shipment, at the lowest weight
   available. This is what stops the rule fragmenting an order it never needed to split.
3. Otherwise walk the ranking, taking `min(remaining, available)` from each warehouse until
   the line is satisfied or the list is exhausted.
4. Any remaining quantity becomes **one allocation row with `is_backorder = true`** against
   the cheapest warehouse — the one it is most likely to be replenished into.
5. **Shipment count** = distinct warehouses across the quotation's non-backorder
   allocations. **Estimated cost** = `Σ (allocated qty × warehouse.shipping_cost_weight)`,
   computed as `Decimal`.

Manual override replaces a line's allocations wholesale, is re-validated against the same
availability rule, and is recorded with `is_manual_override = true`.

**Reason.** The seeded demo case settles it. Laptop Pro 14 × 6, Main Warehouse holding 4 at
weight 1.0, East Depot holding 10 at weight 1.4:

- Main is cheapest but holds 4 < 6, so the single-shipment shortcut does not fire.
- Take 4 from Main, then 2 from East. **Split = 4 + 2**, exactly DEMO.md step A10.
- Shipments 2; estimated cost `4 × 1.0 + 2 × 1.4 = 6.80`.

**The trade-off, stated openly.** East Depot alone could have shipped all 6 in a single
shipment. That is one fewer shipment, but it costs `6 × 1.4 = 8.40` against 6.80 — 24% more.
The rule prefers the cheaper plan, so it reads PDF A4's "minimize number of shipments" as
*weighted by shipping cost*, which is what the same sentence also says, rather than as a
count to be minimised at any price. If a judge asks why not one shipment from East Depot,
the answer is a number already on the screen: 8.40 versus 6.80.

The strict alternative — fewest shipments first, cost only as a tie-break — was rejected
twice over. It produces the more expensive plan, and with the seeded stock it produces no
split at all, which would leave AC-5's "splitting across two warehouses if needed"
undemonstrable. Recorded here so the choice is visible rather than assumed.

**Consequences.**
- It is a heuristic and is described as one everywhere it appears. Lines are solved
  independently, so across a multi-line order the shipment count is not globally optimal:
  two lines could each pick a different cheapest warehouse where one warehouse could have
  covered both. Honest, cheap, and enough for this build; a global optimiser is explicitly
  out of scope and belongs in the "what we would build next" note (T-34).
- The ordering is fully deterministic, so the suggested split is reproducible on stage and
  testable without fixtures.
- Invariants 6, 7 and 8 hold by construction: no allocation exceeds available stock at
  allocation time, allocations per line never exceed the line quantity, and any shortfall
  exists as a backorder row rather than as a silently missing quantity.
- Manual override goes through the same validation as the suggestion. An override exceeding
  available stock is rejected by the service, not prevented by hiding the control.
- The split is computed from **live** stock every time it is requested — never cached, never
  seeded. T-24's "Consolidate Remaining Backorder" prompt re-runs the same function against
  the backordered quantity.

**Blocks:** T-16 (warehouse split and backorders). **Unblocked.**

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

**Blocks:** T-21 (deal health and anomaly dashboard).

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

**Blocks:** T-20 (subscription lines and hybrid billing).

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

**Blocks:** T-05 (product, category and price list configuration), T-23 (reporting with filters).

---

## ADR-010 — Quotation stage machine shape

**Status:** Accepted
**Date:** 2026-09-05

**Context.** DATA_MODEL.md proposes a stage enum. The PDF names stages across several
sections without listing them in one place: Draft and Pending Approval (B2), Sent /
Under Negotiation / Confirmed (B8, portal-visible), plus approved, fulfilment, invoiced
and paid states implied by §5 and §9. Invariants 1, 2, 5 and 13 in DATA_MODEL.md constrain
the answer regardless of shape — whatever machine is chosen must make those expressible.

**Decision.** **One `stage` field on Quotation, a single enum, and no second
portal-status field.**

```
DRAFT · PENDING_APPROVAL · REJECTED · APPROVED · SENT
UNDER_NEGOTIATION · CONFIRMED · FULFILLED · INVOICED · PAID
```

The three sub-questions, answered:

- **`SENT` is a distinct stage, not a flag on `APPROVED`.** B8 lists it as one of three
  portal-visible statuses alongside the other two, and a flag would be a second field that
  every transition has to remember to clear.
- **`REJECTED` is terminal.** Return-for-revision is a *different* action, exactly as B4
  implies: it is an `ApprovalStep.status = RETURNED` which sends the quotation back to
  `DRAFT` for the rep to fix. Reject kills the deal; return sends it back. Two actions, two
  outcomes.
- **Portal status is a display mapping over `stage`, not a stored field.** `SENT` → "Sent";
  `UNDER_NEGOTIATION`, `PENDING_APPROVAL` and `APPROVED` → "Under Negotiation";
  `CONFIRMED`, `FULFILLED`, `INVOICED`, `PAID` → "Confirmed"; `REJECTED` → "Closed". The
  customer therefore never sees an internal approval stage, and there is no second field to
  drift out of step with the first.

**Transitions.**

```
DRAFT ──submit, score > 0──► PENDING_APPROVAL ──all steps APPROVED──► APPROVED
DRAFT ──submit, score == 0─────────────────────────────────────────► APPROVED
PENDING_APPROVAL ──any step REJECTED──► REJECTED            (terminal)
PENDING_APPROVAL ──any step RETURNED──► DRAFT               (return for revision)
APPROVED ──rep sends the portal link──► SENT
SENT ──customer comments or counters──► UNDER_NEGOTIATION
UNDER_NEGOTIATION ──counter re-scores over threshold──► PENDING_APPROVAL    (BR-6)
SENT | UNDER_NEGOTIATION | APPROVED ──customer confirms──► CONFIRMED
CONFIRMED ──split accepted, stock reserved──► FULFILLED
FULFILLED ──invoice generated──► INVOICED
INVOICED ──payments cover the invoice──► PAID
```

**Reason.** One field is the smallest shape that expresses all four constraining invariants,
and a single enum is exactly what the quotation list, the Kanban pipeline (T-22) and the
reporting "Approval Status" filter (T-23) all want to group by. A stage plus a parallel
portal-status field would be two sources of truth for one question.

Each constraining invariant, expressed:

1. *No `APPROVED` while a step is `PENDING`* — `PENDING_APPROVAL → APPROVED` fires only when
   no step remains `PENDING`.
2. *`risk_score > 0` needs at least one step* — the direct `DRAFT → APPROVED` edge is guarded
   by `score == 0`; every other route into `APPROVED` passes through `PENDING_APPROVAL`,
   which is what creates the steps.
5. *`CONFIRMED` requires `APPROVED` or a zero score* — the only edges into `CONFIRMED` come
   from `APPROVED`, `SENT` and `UNDER_NEGOTIATION`, and `SENT` is reachable only from
   `APPROVED`. From `UNDER_NEGOTIATION`, confirm is permitted only while the current score
   still requires no approval; otherwise BR-6's edge fires first.
13. *A portal counter past the threshold returns to `PENDING_APPROVAL` with fresh steps* —
    that edge is in the table, and the re-approval loop reuses `PENDING_APPROVAL` rather than
    inventing a second re-approval stage.

**Consequences.**
- **This is stricter than DATA_MODEL.md's lifecycle sketch, deliberately.** That diagram
  branches `DRAFT → SENT`. This machine does not: `SENT` is reachable only from `APPROVED`,
  so an over-ceiling quotation cannot be put in front of a customer before governance has
  seen it. Letting a rep skip approval by sending the link is precisely the failure this
  product exists to prevent. DATA_MODEL.md's diagram should be corrected to match; it is not
  edited here because that file is owned by a task in flight.
- Quotations seeded straight into `SENT` (Beta Industries, DEMO.md Flow B) are fine — the
  seed writes an end state, it does not walk the machine.
- `REJECTED` being terminal means a rejection ends the deal. Sending work back to a rep is
  the `RETURNED` step status, and that is the action worth demonstrating.
- Every transition updates `last_activity_at` — the stalled-deal detector is meaningless
  otherwise — and writes an `AuditLog` row wherever BR-3 requires one.
- The portal label mapping lives in one function in the portal app. Adding an internal stage
  later means adding one line there, and the customer-visible vocabulary stays the three
  words PDF B8 names.

**Blocks:** T-02 (schema and migrations — the Quotation stage enum is defined there). **Unblocked.**

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
  Decision Needed except T-09/T-10 (ADR-005), which is flagged as the first thing to settle.
- CURRENT.md points at T-01, which has no dependencies.

**Contradictions found:** none between documents.

**Ambiguities carried forward:** ADR-004 through ADR-010 above. All originate in the
problem statement, not in these documents. None has been silently resolved.

**One tension worth naming.** SPEC.md marks the upsell panel (B5) SHOULD, because PDF A6 —
its configuration screen — is explicitly Optional. But the panel appears in the PDF's own
acceptance test as AC-4. It is therefore built as P1 rather than P2: the *panel* is
effectively required by the test flow even though its *config screen* is optional. This is
a reading of the PDF, not an invention, and is recorded here so it can be challenged.

---

## Cross-document consistency check — 2026-09-05 (second pass)

Run before T-01 started. Three contradictions were found and fixed; they are recorded here
rather than silently corrected.

1. **Stack leftovers in DATA_MODEL.md.** The "Calculated fields" table named `pricing.ts`,
   `risk.ts`, `fulfilment.ts`, `upsell.ts` and `health.ts` — TypeScript filenames surviving
   from a draft written before ADR-001 chose Django. Corrected to `core/services/*.py`,
   matching ARCHITECTURE.md. (The Next.js + Prisma mentions in ADR-001 are deliberate: they
   record rejected alternatives and are not leftovers.)

2. **Stale task IDs in every ADR `Blocks:` line.** ADR-004 said T-13/T-14, ADR-005 T-08/T-09,
   ADR-006 T-15, ADR-007 T-19, ADR-008 T-17, ADR-009 T-04/T-20, ADR-010 T-06 — all written
   against an earlier numbering of BACKLOG.md. Every line now cites the real task and names
   it, so a wrong number is visible rather than merely wrong. BACKLOG.md's own T-00 was the
   correct mapping in every case **except** ADR-010, which it pointed at T-06 (approval chain
   config). The Quotation stage enum is defined in T-02, so both were corrected to T-02.

3. **A5 scope — the same argument as the upsell panel above.** SPEC.md marked A5
   (subscription / recurring plan setup) SHOULD in full. But AC-1, which is PDF §9 verbatim,
   requires the tester to "set up basic backend data: a discount tier, a warehouse, a
   subscription plan" and for all three to persist. A MUST acceptance criterion cannot depend
   on a SHOULD feature.

   **Decision.** A5 is split. The `SubscriptionPlan` entity and its Django admin CRUD are
   **MUST**: they move into T-02's entity list, T-03's seed and T-05's config screens.
   Recurring *billing behaviour* — BillingScheduleEntry rows, proration, cancellation refunds
   (FR-30, FR-31, FR-32) — stays **SHOULD/BONUS** in T-20, and AC-6 rather than AC-1 is what
   exercises it.

   **Reason.** This is the identical reading applied to the upsell panel in the note above: a
   feature named in the PDF's own acceptance test is required by the test flow even where its
   surrounding module is marked optional. Promoting the smallest unit that makes AC-1 pass —
   a plan row and a screen to create it — costs one model and one admin registration, and
   leaves the genuinely expensive part (proration) where the PDF's priorities put it.

   **Consequences.** T-02 gains one model, T-03 gains one seed row, T-05 gains one admin
   registration. `BillingScheduleEntry` deliberately stays out of P0 — a plan that exists and
   persists satisfies AC-1; billing against it does not have to. ADR-008 (proration method)
   therefore still blocks only T-20, not any P0 task.

---

## T-00 record — blocking decisions closed, 2026-09-05

Four ADRs moved from **Decision Needed** to **Accepted**: ADR-005 (blended risk score),
ADR-006 (warehouse split), ADR-004 (portal access) and ADR-010 (quotation stage machine).
ADR-007, ADR-008 and ADR-009 were deliberately left open — BACKLOG.md T-00 defers them and
each blocks only a P1 task (T-21, T-20, T-23 respectively). **No P0 task is now blocked by an
open decision.**

ADR-005 was closed first and its two specification tests were written **before** the formula
was chosen, in `core/tests/test_risk.py`, per CLAUDE.md. They skip cleanly until
`core/services/risk.py` exists, naming T-09 in the skip reason so the gap stays visible.

**Two document contradictions surfaced while closing these. Neither is silently patched.**

1. **DEMO.md B5 versus the ADR-005 routing bands.** Beta Industries is Silver (tier ceiling
   10%) and DEMO.md B3 has the customer counter at 20% — at least 10 points over, which
   lands in the Manager + Finance band, while DEMO.md B5 shows only the Manager approving.
   The routing is correct; the script is one step short. Recommended fix: T-03 seeds the
   Flow B counter at **15%** (5 points over, Manager only, matching B5 exactly and still
   plainly "a bigger discount" for AC-7). Alternative: add a Finance approval to B5.
   DEMO.md is owned by another task and was not edited here.

2. **DATA_MODEL.md's lifecycle diagram versus ADR-010.** That diagram branches
   `DRAFT → SENT`. ADR-010 forbids it: `SENT` is reachable only from `APPROVED`, so an
   over-ceiling quotation cannot reach a customer before governance has seen it. The
   diagram should be corrected. DATA_MODEL.md is owned by a task in flight and was not
   edited here.
