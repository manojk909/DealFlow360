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

**Status:** Accepted
**Date:** 2026-09-05

**Context.** PDF B9 defines stalled deals as "quotations inactive for more than a
configured number of days" — configurable, but no default given. Discount anomalies are
"a discount well above a rep's historical average" — "well above" is not quantified. Also
listed: delivery promise slippage indicators, with no definition of the promise date.

**Decision.** **All three thresholds live on a `SalesSetting` singleton row, not in code.**

| Threshold | Default | Meaning |
|---|---|---|
| `stall_days` | 7 | An open quotation untouched for longer is stalled. |
| `anomaly_window_days` | 90 | How far back a rep's own average discount is computed. |
| `anomaly_threshold_pct` | 10 | Points above that average which count as an anomaly. |
| `delivery_promise_days` | 5 | Days after confirmation an order is promised for. |

1. **Stalled** — `last_activity_at` older than `stall_days`, and the stage is still open.
   PAID and REJECTED are finished, so they are never stalled however long they sit.
2. **Anomaly** — a line whose discount is at least `anomaly_threshold_pct` points above
   **that rep's own mean discount** over the window. The PDF says "a rep's historical
   average", so the comparison is per rep, not company-wide. A rep with no history has no
   average, so their lines cannot be anomalies — the alternative flags every line a new
   joiner writes, which is noise, not signal.
3. **Slippage** — `Quotation.promised_delivery_date`, set at confirmation to
   today + `delivery_promise_days`, is now the promise the PDF refers to. An order past it
   with stock still on backorder has slipped. Orders confirmed before the field existed
   have no promise and are skipped rather than back-dated into a guess.

**Reason.** The PDF's own word is *configured*. A constant in `health.py` would not be
that, and the difference is demonstrable: a judge can open the back-end, set the stall
window to 1, and watch the dashboard change. Putting the anomaly comparison on the rep's
own record follows the wording exactly and avoids the trap of flagging a whole team
because one product line runs at a structurally higher discount.

**Consequences.** One extra table and one migration. `health.py` reads the row on every
call rather than caching it, which is correct for a dashboard and irrelevant at this size.
The three detectors are covered by `core/tests/test_subscriptions_and_health.py`, including
a test that moving the setting moves the result — the property that makes it configuration.

**Unblocks:** T-21 (deal health and anomaly dashboard), T-29 (nudge action).

---

## ADR-008 — Subscription proration method

**Status:** Accepted
**Date:** 2026-09-05

**Context.** PDF A5 requires "proration rules for mid cycle quantity or plan changes" and
B7 requires handling "mid cycle proration when quantity changes". The basis — daily
pro-rata, whole-period, or something else — is not specified. Cancellation triggers "an
automatic partial refund or credit note" with no rule for computing the amount.

**Decision.** **Daily pro-rata on the current period, for both quantity changes and
cancellation.**

```
adjustment = (new_qty - old_qty) x unit period price x days_remaining / days_in_period
```

* Every period after the current one bills at the new quantity in full.
* A decrease produces a negative adjustment — a credit, carried on the schedule.
* **Cancellation** credits the unused days of the current period as a credit-note
  `Invoice` (`is_credit_note=True`), and cancels every future scheduled entry. A partial
  refund and a credit note are therefore the same thing here, expressed once: the money
  goes back as a document against the order, not as an outbound payment, because nothing
  in this system moves money outwards.

**Reason.** It is the rule a customer can check on a calendar, which is the property that
matters for a billing rule anyone has to trust. Whole-period billing overcharges a customer
who upgrades on the last day of a month; not prorating at all gives away most of a period
on every upgrade. Month lengths are handled by `calendar.monthrange`, so 31 January plus
one month is 28 February rather than a crash.

**Consequences.** `SubscriptionPlan.proration_method` now carries `DAILY` and
`cancellation_policy` carries `CREDIT_UNUSED_DAYS` instead of `UNDECIDED`. Plan *changes*
(as opposed to quantity changes) remain out of scope — SPEC.md scopes proration to
quantity, and a plan change is a different question about what happens to the remaining
schedule. Recorded in NEXT.md rather than half-built.

**Unblocks:** T-20 (subscription lines and hybrid billing), T-30 (cancel with credit note).

---

## ADR-009 — Fields named by the PDF but left undefined

**Status:** Accepted
**Date:** 2026-09-05

**Context.** Three items appear in the problem statement without enough definition to
implement: Tax (A2), Sales Team (A7), and replenishment rules (A4).

**Decision.** The smallest thing that satisfies the words in the PDF, for each.

1. **Tax — carried, displayed, excluded from margin.** `Product.tax_pct` is seeded and
   shown on the product record. Totals are **tax-exclusive** and margin is computed
   pre-tax, because margin is a cost-versus-price question and tax is neither. No tax
   rules engine, no jurisdictions: the PDF names a field, not a behaviour, and inventing
   the behaviour would put a number on screen that nobody specified.
2. **Sales Team — a label on the user, not an entity.** `User.team` is a plain field, and
   the report filter groups by it. The PDF asks for "Sales Team / Rep" as a *filter* and
   describes no team entity, membership, hierarchy or manager-of relationship anywhere
   else. A `Team` table with one column would be ceremony around a string.
3. **Replenishment — a reorder point, display only.** `Stock.reorder_point` per row; the
   fulfilment stock table flags any row at or below it as needing restock. Nothing
   auto-orders, because auto-ordering needs a supplier, a lead time and a purchase order,
   none of which the PDF mentions.

**Reason.** Each of these is one line in the problem statement and peripheral to all eight
acceptance criteria. The failure mode to avoid is building a plausible-looking subsystem
around a word — a tax engine, an org chart — and having a judge ask which requirement it
came from.

**Consequences.** Reporting can filter by team (see A7) and the stock table answers "what
needs restocking". Multi-currency stays a bonus and stays unbuilt (PDF §7 marks it so).

**Unblocks:** T-05, T-23 (reporting with filters), T-31 (replenishment rules).

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

---

## ADR-011 — Where the upsell minimum-margin threshold lives

**Status:** Accepted
**Date:** 2026-09-05

**Context.** BR-7 and PDF A6 require that only suggestions above a configured minimum
margin threshold surface in the upsell panel. But **no entity in DATA_MODEL.md holds that
number**, because the PDF introduces it only inside section A6 — the upsell *configuration
screen* — which the PDF itself marks Optional, and which is BONUS work in our backlog
(T-27). So the threshold is required by a SHOULD feature and owned by a BONUS one.

This ambiguity had no ADR. Added here per CLAUDE.md's instruction to record rather than
silently invent.

**Decision.** `core/services/upsell.py` takes `min_margin_pct` as an **explicit parameter**.
When a caller passes nothing it falls back to a single named module constant,
`DEFAULT_MIN_MARGIN_PCT`, documented in place as a placeholder for the A6 configuration
row that does not exist yet.

**Reason.** The parameter is the real interface: when T-27 adds an upsell configuration
row, the view reads it and passes it in, and no service code changes. A named constant
with one definition is honest about being a default and is trivial to replace; scattering
the number through the ranking logic would not be.

This is deliberately **not** treated the same as discount ceilings, approval bands,
shipping weights or subscription plans. Those are named by CLAUDE.md's no-hardcoding rule,
are all MUST-priority, and all have entities in the data model. This one has none of those
properties, and inventing a model plus a migration for a BONUS screen's setting would cost
more than it is worth today.

**Consequences.**
- The threshold is visible in exactly one place and is named as a default, not a rule.
- Changing it today means a code change. That is a real limitation and is stated on the
  panel's own backlog entry rather than hidden.
- T-27 replaces the constant with a configuration row. Until then the panel is honest:
  the number is ours, not the customer's.
- Nothing else in the services layer gained a constant. Ceilings, bands, weights and plans
  are all still database rows.

**Blocks:** nothing. **Closed by:** T-27 (upsell rule configuration screen).

---

---

## ADR-012 — Self-signup creates a Sales Rep, and only a Sales Rep

**Status:** Accepted
**Date:** 2026-09-05

**Context.** PDF A1 and SPEC.md FR-01 require internal users to be able to sign up. AC-1
opens with "sign up or log in". But **nothing in the problem statement says a user chooses
their own role**, and the four roles are not equal: Manager and Finance can approve
discounts, and Admin can edit the ceilings and approval bands that decide when approval is
needed at all.

A signup form with a role dropdown would let an anonymous visitor grant themselves the
power to approve their own discounts. That is not a security nicety — it would defeat the
premise of the entire product, whose thesis is that pricing discipline is enforced by
somebody other than the person giving the discount away. A judge who typed `MANAGER` into
that dropdown would have disproved the demo in ten seconds.

**Decision.** **Self-signup creates a `REP` and nothing else.**

- The signup form has no role field, and `SignupForm.Meta.fields` is `("email", "name")`,
  so Django never binds `role` from POST data. A crafted request carrying `role=MANAGER`
  has nothing to bind to.
- `SignupForm.save()` sets `role = REP`, `is_staff = False` and `is_superuser = False`
  **explicitly**, rather than relying on the model's default — so the guarantee does not
  quietly depend on a default that somebody could change later for an unrelated reason.
- Manager, Finance and Admin are assigned by an administrator through Django admin, which
  is already the backend configuration area.
- The signup page says all of this in plain words, so it reads as a deliberate policy
  rather than a missing feature.

**Reason.** It is the smallest rule that satisfies FR-01 without contradicting BR-2. It is
also the conventional answer: almost no real sales system lets a stranger self-select into
an approver role. Granting privilege is an administrative act, and this application already
has an administrative surface to do it in.

**Rejected: a role dropdown with an "approval pending" flag.** More faithful to the idea
that someone might legitimately sign up as a manager, but it needs an approval queue for
account creation, which is a second governance system nobody asked for, on a 24-hour build.

**Consequences.**
- AC-1's "sign up" branch is genuinely satisfied and demonstrable.
- A new signup cannot reach `/workspace/approvals/` — the existing role check returns 403,
  and a test asserts a signup attempting `role=MANAGER` still lands as a REP.
- Seeded demo accounts are unaffected; `seed_demo` sets roles directly, which is the
  administrative path, not the signup path.
- There is no password reset and no email verification. Neither is required by any
  acceptance criterion and both need mail infrastructure that ADR-004 already declined.

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

---

## ADR-013 — Assets: what a customer owns

**Status:** Accepted
**Date:** 2026-09-06

**Context.** A competitor review of Salesforce Revenue Cloud and Odoo Subscriptions found
one structural difference that explains most of the feature gap. Both are built around an
**asset** — a record of what a customer owns *right now* — and their entire right-hand side
(renewals, amendments, cancellations, MRR, churn, retention) reads from it. This system
went Quotation → Invoice and stopped, so it could say "Acme signed a quote in March" and
could not say "Acme owns three Care Plans worth ₹1,440 a month, expiring 14 October".

That second sentence is where a renewals conversation starts, and no amount of querying
quotations produces it: a quotation records what was agreed on a day, an asset records what
is true today. Two quotations for the same customer may overlap, supersede each other, or
have been cancelled, and the quotation table cannot tell you which.

**Decision.** **One `Asset` row per confirmed quotation line, written by the system at
confirmation and never by hand.**

* Created by `assets.create_from_confirmation()`, called from `billing.on_order_confirmed()`
  — the same hook that builds the billing schedule, so an asset cannot exist for an order
  nobody confirmed. Idempotent, because both the rep's warehouse-split confirmation and the
  customer's portal confirmation reach that hook.
* A **one-time** line becomes an asset with no end date and no MRR. Owning a laptop does not
  expire, and "what does this customer own" is not a subscription-only question.
* A **recurring** line gets a term of twelve billing periods — matching the schedule — and an
  `mrr` **normalised to one month** whatever the plan interval. A quarterly plan billed 900
  contributes 300. Without normalising, every dashboard has to know the interval, and one of
  them eventually forgets.
* `source_line` is unique and PROTECT: a line is bought once, and an asset without its
  origin cannot be audited.

**Renewals are the reason the entity earns its place.** `create_renewal_quotation()` raises
one draft quotation covering everything a customer has expiring, **priced at today's price
list rather than the price on the original order**. A renewal is a new agreement; carrying
an old price forward silently is how margin leaks, and the rep can see both numbers. Every
renewed asset is marked and linked to the new quotation, so the same asset cannot be renewed
twice and the chain is traceable.

**Reason.** It is the smallest addition that unlocks the largest set of questions. MRR, ARR,
the renewals queue and per-customer revenue all fall out of one table with two indexes. The
alternative — deriving ownership from quotations on every read — is both slower and wrong,
because it cannot express cancellation.

**Consequences.** `seed_demo` must delete assets first: they hold PROTECT keys to lines,
quotations, customers and products, and the second run fails otherwise. That was caught by
the existing re-seed test rather than on stage.

**Deliberately not built:** amendments and co-terming (changing an asset mid-term rather
than replacing it), cancellation refunds against assets, and churn analytics. Each needs the
spine this ADR establishes, and each is a real piece of work. Recorded in NEXT.md.

## ADR-014 — Display currency

**Status:** Accepted
**Date:** 2026-09-05

> **Renumbered.** This was written as ADR-012, which collided with the self-signup
> decision of the same number. Renumbered to 014 on 06 Sep; nothing about the decision
> itself changed. ADR-013 is Assets.

**Context.** Every template hard-coded `&euro;` beside a `floatformat`, so the currency was
a hundred literals rather than a setting, and the default was wrong for the market this
product is built for. PDF section 7 lists multi-currency as an explicit bonus, not a
requirement, so the question is how much to build.

**Decision.** **One display currency on the `SalesSetting` row — code, symbol and rate —
rendered through a single `money` template filter. Default INR, symbol ₹.**

* Amounts are stored in the base currency and multiplied by `currency_rate` on display.
  `currency_rate = 1.000000` changes only the symbol; a different rate converts every
  screen at once.
* Digits are grouped the Indian way — ₹12,34,567.89 — because 1,234,567 reads as foreign
  in the default market. Western grouping is one branch away.
* The setting is cached and the cache is cleared in `SalesSetting.save()`. A page renders
  this filter dozens of times and must not issue dozens of queries.

**Reason.** This is the smallest thing that is honestly a currency *factor* rather than a
relabelling: one number, documented, that actually converts. It stops short of
multi-currency, which needs a per-customer currency, a rate source, and rates as of the
quotation's date rather than today's — a real piece of work, and a bonus by the PDF's own
framing. Building half of it and calling it multi-currency would be worse than not building
it.

**Consequences.** `PriceListEntry.currency` defaults to INR and remains per row, so the
schema is already shaped for the full version. Fourteen templates lost their `&euro;`
literals. The CSV export names the currency in its column headers, since a symbol in a
spreadsheet is ambiguous and a code is not.

**Unblocks:** T-32 (multi-currency, still a bonus and still unbuilt).

---

