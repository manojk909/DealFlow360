# Completed Tasks

Newest first. A task lands here only when it genuinely works end to end, per CLAUDE.md's
completion protocol.

---

## Services integration contract

*Completed 05 Sep 2026. Commit `d54f1e0`. Not a numbered backlog task — done before any
service body is written, so the tasks that depend on each other cannot disagree about
shapes.*

Eight modules under `core/services/`, **39 functions and 11 dataclasses/exceptions**, each
a signature and a docstring with a `NotImplementedError` body naming the task that fills it
in. Verified by introspection: every module has a docstring, every public function has a
docstring, and every one raises `NotImplementedError`.

| Module | Functions | Owner task |
|---|---|---|
| `pricing.py` | 5 | T-08 |
| `risk.py` | 3 | T-09 |
| `approval.py` | 6 | T-10 |
| `fulfilment.py` | 6 | T-16 (T-24 for consolidation) |
| `billing.py` | 6 | T-17, T-20 |
| `negotiation.py` | 6 | T-14, T-15 |
| `upsell.py` | 3 | T-19 |
| `health.py` | 4 | T-21 |

**Decisions the contract pins down**, beyond argument lists:

- `risk.score_quotation()` stays **pure** — plain dicts and Decimals, no ORM — which is what
  lets the specification tests assert both PDF examples with no fixtures.
  `score_for_quotation()` is the thin adapter beside it.
- `approval.required_levels()` raises rather than falling through to "no approval needed"
  when no chain rule matches. Skipping governance silently is the failure this product
  exists to prevent.
- `fulfilment.accept_split()` recomputes at commit time instead of trusting the suggestion
  the screen rendered — stock moves between page load and click.
- `billing.record_payment()` is the **only** function permitted to write a Payment or move
  an Invoice status, because invariant 11 cannot be a SQLite constraint.
- `negotiation.submit_counter_offer()` **replaces** the targeted line's discount rather than
  stacking an order-level one. This is what keeps DEMO Flow B in the Manager-only band.

**Three functions are blocked, in writing, rather than guessed:**
`billing.prorate_quantity_change()` on ADR-008, and `health.discount_anomalies()` and
`health.delivery_slippage()` on ADR-007. Their docstrings say which ADR blocks them and
why, so nobody quietly invents a threshold the problem statement never gave.

**One change to `core/tests/test_risk.py`.** Its skip guard used to ask "does the module
import?", which stopped meaning anything the moment `risk.py` existed as a stub. It now
probes for a *working* implementation and skips on `NotImplementedError`. The skip
condition changed; no expectation did.

---

## T-02 + T-03 — Full P0 schema and seed script, one migration wave

*Completed 05 Sep 2026. Commit `3c49fea`.*

**Twenty-one models across five domain modules**, one `makemigrations`, one `migrate`.

Beyond T-02's stated entity list this wave also creates `SubscriptionPlan` (P0 as of the A5
split), plus the SHOULD entities from DATA_MODEL.md — `ProductVariant`, `ProductPair` and
`BillingScheduleEntry`. That was a judgment call: "full schema from DATA_MODEL.md" in one
wave means T-19, T-20 and T-25 do not each need their own migration later. Three small
tables now against three migration waves later.

**Acceptance criteria — verified by exercise.**

| Criterion | How it was verified |
|---|---|
| Migration applies cleanly to an empty database | `db.sqlite3` deleted and rebuilt from scratch three times during the task |
| Unique constraint on Stock (product, warehouse) at DB level | Deliberately inserted a duplicate; refused by `unique_stock_per_product_warehouse` |
| Invariant 8 (reserved never exceeds on hand) | Deliberately violated; refused by `stock_reserved_not_over_on_hand` |
| Invariant 9 (RECURRING has a plan, ONE_TIME does not) | Both directions violated; both refused by `recurring_line_has_plan_one_time_does_not` |
| Invariant 11 (payments never exceed invoice amount) | **Not a database constraint** — SQLite cannot express it without a subquery. Enforced in `billing.record_payment()`, documented on the Invoice model and in the verification output, so its absence is a decision rather than an oversight |
| `Quotation.stage` uses ADR-010's enum exactly | Ten `TextChoices` members matching the ADR |
| Everything importable from `core.models`, `check` clean | 21 models re-exported; `manage.py check` silent |
| `manage.py test` still passes | Green, with the two risk spec tests skipping |

Twelve constraints in total were verified by deliberately violating each one and confirming
SQLite refused it — not by reading the migration and assuming.

**Seed — `python manage.py seed_demo`.**

Reproduces `docs/DEMO.md` exactly: 8 users, 3 tiers, 3 categories, 3 Gold category ceilings,
3 approval chain rules, 3 customers, 10 products with costs, 4 variants, 30 price list
entries, 6 product pairs, 3 subscription plans, 2 warehouses, 8 stock rows and 5 quotations.
Idempotent — run three times, row counts identical.

**The load-bearing numbers, checked independently.** A verification script that imports
nothing from `seed_demo` — the arithmetic rewritten fresh from ADR-005 and applied to
database rows — confirmed:

- Q-2026-0003 (Acme, the PDF worked example) recomputes to **exactly 8.00**: Laptop 12%
  against a 15% Hardware ceiling contributes 0, Onsite Setup 18% against a 10% Services
  ceiling contributes 8. The stored `risk_score` snapshot matches.
- That score matches the `8.00-9999.99` chain rule, which requires **Manager then Finance** —
  and the two seeded ApprovalStep rows are exactly Manager then Finance, both PENDING.
- The three chain bands tile with no gap and no overlap.
- The PDF's second example (17/15, 13/10, 14/12) totals **7.00** and lands in the
  Manager-only band, so both worked examples are exercised by seeded configuration.
- **Laptop Pro 14: Main Warehouse 4, East Depot 10, demo order 6.** Main is the cheaper
  warehouse (1.00 against 1.40) and holds only 4, so ADR-006's single-shipment shortcut
  cannot fire and the split is forced: 4 + 2, estimated cost 6.80.
- Flow B: Beta is Silver, scores 0.00 today, and a 15% counter is 5 points over its ceiling —
  Manager only, so DEMO B5 holds as written.

**Debt taken on deliberately.** `seed_demo` carries provisional copies of the pricing and
risk arithmetic, marked `PROVISIONAL` in the file, because the seed has to store totals and
a score before T-08 and T-09 exist, and a quotation list showing 0.00 on every card is not a
demo. Deleting both is now an acceptance criterion on T-08 and T-09.

**Three integration findings recorded in BACKLOG rather than left for the demo:**

1. **Non-stocked lines must be skipped by the split, not backordered** (T-16). Services and
   Subscriptions have no Stock rows — correctly — so a naive implementation reports the
   Onsite Setup Service line as a total backorder and the fulfilment screen looks broken.
2. **A portal counter replaces a line's discount rather than stacking as a second
   order-level discount** (T-15). Stacking Beta's 15% onto its existing 8% gives roughly 21
   points over, pulls in Finance, and strands DEMO B5.
3. Both provisional seed helpers must be deleted (T-08, T-09).

**Also in this wave.** The `portal` app now exists with its own reserved `urls.py` mounted
at `/portal/`, and `config/urls.py` only mounts apps — so adding a screen never edits it
again. The portal has no views yet; T-14 fills them in. `/portal/` returns 404 today, which
is correct for an empty urlconf.

**Remaining risks.**

- The seed's provisional arithmetic is a second implementation of two formulas. It agrees
  with ADR-005 today, verified; it will silently rot if ADR-005 changes and only the service
  is updated. That is why deletion is an acceptance criterion and not a comment.
- Only Gold has category ceilings, matching DEMO.md. Adding a stricter Services row for
  Silver would change Flow B's routing and break the demo script — flagged in the seed's
  docstring, where someone tidying the data would see it.
- Nothing is registered in Django admin yet, so the seeded configuration is not editable
  through a screen. T-05, T-06 and T-07 do that, and AC-1 is not demonstrable until they do.

---

## T-00 — Close the blocking open decisions

*Completed 05 Sep 2026. Ran in parallel with T-01.*

**Four ADRs closed. No P0 task is blocked by an open decision any more.**

| ADR | Decision, in one sentence |
|---|---|
| **ADR-005** blended risk score | The score is the total number of discount percentage points given away above ceiling across the whole quotation, where every line is measured against the stricter of its customer tier's ceiling and its category's. |
| **ADR-006** warehouse split | Fill each line from the cheapest warehouse first and spill into the next cheapest — except that a warehouse able to cover the whole line by itself ships it alone — and whatever is left becomes a backorder. Documented as a heuristic in the ADR, in SPEC BR-4 and on the screen. |
| **ADR-004** portal access | A signed, quotation-scoped `TimestampSigner` token at `/portal/<token>/`, copied from the internal screen: no customer accounts, no passwords, no email, no expiry; a bad token returns 403. |
| **ADR-010** stage machine | One `stage` enum, `SENT` a real stage reachable only from `APPROVED`, `REJECTED` terminal, return-for-revision a separate `ApprovalStep.status = RETURNED` sending the quote back to `DRAFT`, and portal status a display mapping over `stage` rather than a stored field. |

**ADR-007, ADR-008 and ADR-009 were deliberately left open.** All three block P1 tasks only
(T-21 deal health, T-20 proration, T-05/T-23 tax and reporting), and BACKLOG T-00 defers them
on purpose.

**The two specification tests were written before the formula**, per BACKLOG T-00 and
CLAUDE.md. `core/tests/test_risk.py` asserts both PDF §10 worked examples against the API
that ADR-005 fixes. They currently skip with the reason
`"core.services.risk not implemented yet — see T-09"`, so `manage.py test` stays green at
T-01 and turns red the moment T-09 gets the arithmetic wrong. The file says in its docstring
that it is the specification and must not be edited to match the implementation.

Both examples reproduce, and can be checked by hand:

- Example 1 — Hardware 12% against ceiling 15 → 0 over; Services 18% against `min(15, 10)` =
  10 → **8 over**. Score 8.00, flagged, and 8.00 is exactly the Finance boundary.
- Example 2 — 17/15, 13/10, 14/12 → 2 + 3 + 2 = **7.00**, flagged, Manager only.

**ApprovalChainRule rows for T-03 to seed** — configuration, not code:

| `score_min` | `score_max` | `requires_manager` | `requires_finance` |
|---|---|---|---|
| 0.00 | 0.00 | false | false |
| 0.01 | 7.99 | true | false |
| 8.00 | 9999.99 | true | true |

Inclusive both ends, tiling with no gap or overlap. A score matching no rule must fail
loudly rather than silently skip governance. The bands are exact because the score is
quantised to 0.01, so nothing can land between 7.99 and 8.00.

**Two contradictions surfaced by the decisions, both fixed rather than noted.**

1. **DEMO.md Flow B was one approval step short.** B3 had Beta Industries (Silver, ceiling
   10%) counter at 20% — 10 points over, which under the new bands pulls in Finance as well
   as the Manager — while B5 showed only the Manager approving and B6 then expected Confirm
   to work. Fixed by countering at **15%** instead: 5 points over, still automatic re-entry
   for AC-7, but inside the Manager-only band. Flow A already demonstrates the two-step
   chain. The 20%-plus-Finance variant is recorded in DEMO.md as a rehearsed alternative.
2. **DATA_MODEL.md's lifecycle diagram had a `DRAFT → SENT` edge.** ADR-010 forbids it — a
   rep could otherwise send a customer the portal link straight out of Draft and route
   around governance entirely, breaking invariants 2 and 5. The diagram was redrawn and the
   removal called out in the text rather than quietly patched.

Also cleaned up: `docs/ARCHITECTURE.md` still carried two `DECISION NEEDED` markers for
ADR-004 (portal mechanism, and whether to send email at all). Both now state the decision.

**Remaining risk.** The risk formula deliberately ignores line value and quantity — a
judge may ask why a 20% discount on a €5 item scores the same as one on a €5,000 item. The
honest answer, recorded in ADR-005, is that PDF §10's worked examples are stated purely in
percentage points with no prices, so a value-weighted score cannot reproduce them, and the
live margin indicator is the separate signal that carries value. Worth rehearsing before the
demo, because it is the most likely question about the product's core rule.

---

## T-01 — Project scaffold and database connection

*Completed 05 Sep 2026. Commit `385bfd1`.*

**What landed.** A running Django 5.2 project on SQLite with a custom `User` model and a
health page that proves the URL → view → ORM → SQLite → template round trip.

**Acceptance criteria — verified, not assumed.**

| Criterion | How it was verified |
|---|---|
| `runserver` serves a page | Server started on 127.0.0.1:8137; `GET /` → 302 → `/health/`, `GET /health/` → 200 |
| `core` app with custom `User` carrying `role`, `AUTH_USER_MODEL` set to it | `AUTH_USER_MODEL = "core.User"`; role choices `REP / MANAGER / FINANCE / ADMIN`; the health page prints the model label read from `User._meta` |
| `migrate` applies cleanly to a fresh `db.sqlite3` | `db.sqlite3` deleted, `makemigrations core` then `migrate` — 19 migrations applied, `core.0001_initial` among them, no conflicts |
| `/health/` renders a value read from the database | Live proof: created a second user through the ORM, the page's user count went 1 → 2 and a `FINANCE` role chip appeared; deleting the user returned it to 1. Also prints `sqlite_version()` from a real cursor and the applied-migration count from `django_migrations` |
| `createsuperuser` works and `/admin/` loads | Superuser `admin@dealflow.test` created (email is `USERNAME_FIELD`, there is no username); login succeeds, `/admin/` → 200, user changelist shows the Role column, add and change forms both render `id_role` |
| `.gitignore` excludes `db.sqlite3`, `__pycache__/`, `.venv/`, `.env` | `git status --ignored` confirms all four are ignored; `db.sqlite3` is absent from a fresh clone |
| `requirements.txt` pins Django and very little else | Two lines: `Django==5.2.17`, `python-dotenv==1.2.3`. HTMX and Tailwind are CDN script tags, not Python packages |
| `README.md` runnable from a clean clone | **Actually performed.** Cloned into a scratch directory, created a venv, installed from `requirements.txt`, migrated, created a superuser and ran the server on port 8138 following only the README. `/health/` → 200 showing 1 user and an `ADMIN` role, read from the clone's own fresh database |
| All four members have cloned and run it | **N/A — closed, not skipped.** This is a solo build (Team 317, one member). Odoo's version-control must-have — "one member managing the repo is not enough" — exists so a multi-member team cannot have one person do all the committing; with a team of one there is nothing to check. The criterion was written when the plan assumed four developers. |

**Decisions taken inside the task.**

- **Email login, no username.** `USERNAME_FIELD = "email"` with `AbstractBaseUser` +
  `PermissionsMixin` and a custom manager, because DATA_MODEL.md gives `User` an email and
  a `name` and no username. `createsuperuser` therefore prompts for email and full name.
- **Python 3.13, not 3.10.** ARCHITECTURE.md recorded Python 3.10.12 on the dev machine;
  this machine has 3.13.5. Django 5.2 supports 3.10 through 3.13, so the code targets 3.10+
  and runs on either. Nothing in the project uses a 3.11+ language feature.
- **`python-dotenv` added as the second and only other dependency**, so `.env.example` is
  meaningful rather than decorative. Settings fall back to working defaults without a
  `.env`, so the app runs immediately after `migrate` with no configuration step.

**Bug found and fixed during verification.** The admin's `add_fieldsets` referenced
`usable_password`, which exists on Django 5.1+'s `AdminUserCreationForm` but not on
`UserCreationForm`. `/admin/core/user/add/` returned a 500 `FieldError` until the form was
switched. Worth noting because it is invisible to `manage.py check` — only loading the page
catches it.

**Remaining risks.**

- Only one machine has run this, and being solo there is no second machine to try it on.
  The clean-clone test is the substitute: it proves the README works from nothing.
- Tailwind and HTMX load from CDNs, so the UI degrades to a minimal inline fallback with no
  network. Logged as **T-26a**; vendor them before the demo rehearsal.
- `/health/` is the only page. Nothing else is built yet, and nothing should be read into
  the scaffold beyond "the round trip works".

---

## T-20 to T-31, T-36 — the P1 sweep

*Completed 05 Sep 2026.*

**Three ADRs closed first**, because each blocked the task that needed it. ADR-007 put the
deal-health thresholds on a `SalesSetting` row rather than in code, which is what the PDF's
word "configured" requires. ADR-008 chose daily pro-rata on the current period for both
quantity changes and cancellation — the rule a customer can check on a calendar. ADR-009
answered the three under-specified fields with the smallest thing that satisfies the PDF:
tax carried and displayed but outside margin, sales team as a label on the user rather than
an entity, replenishment as a display-only reorder point.

**What shipped.**

| Task | Screen or behaviour |
|---|---|
| T-20 | Billing schedules per recurring line, mid-cycle proration, cancel with credit note (B7) |
| T-21 | Deal health: stalled deals, discount anomalies against each rep's own average, delivery slippage (B9) |
| T-22 | Pipeline Kanban, split from the new Quotations table (B1/B2) |
| T-23 | Reporting with all four PDF filters, per-product rollup, CSV export, print-to-PDF (A7) |
| T-24 | Consolidate remaining backorder, reusing the ordinary split rule against the outstanding quantity (B6) |
| T-25 | Product variant picker on the quotation line, repriced through `resolve_unit_price` (A2) |
| T-29 | Nudge from a deal health alert — an audit row and a reset activity clock |
| T-30 | Subscription cancellation with a credit note for the unused days |
| T-31 | Reorder point per stock row, flagged on the fulfilment stock table (A4) |
| T-36 | Sidebar navigation, KPI tiles, light mode, and the three bug fixes below |

**Bugs found by driving the running application, not by reading it.**

1. **Sign-out was a GET.** `LogoutView` has refused GET since Django 5.0, so the control
   rendered a 405 error page and left the session signed in. No test referenced logout at
   all — the suite could not have caught it.
2. **Locked quotations were editable over HTTP.** `line_add`, `line_update`, `line_delete`,
   `order_discount` and `upsell_add` never checked the stage; only the template did. A
   quotation already sitting in approval could have its quantities and discounts changed,
   which is exactly the governance the product claims to enforce. Fixed with one guard
   function that all five endpoints and the builder page share.
3. **Rejected input was silent.** The views returned a 400 carrying a re-rendered region
   with an error banner, and HTMX discarded it, because HTMX does not swap non-2xx
   responses by default. The value stayed in the field and nothing said why.

A fourth was caught by the new tests rather than the browser: `from core.services import
health` silently shadowed this module's own `health` view, so the Deal Health page raised
`AttributeError` on every request. Imported as `health_service` now.

**Seed data grew to match.** 10 users across two sales teams, 8 customers, 18 products,
3 warehouses, ~25 quotations. The history is deliberate rather than decorative: one rep
has eight quiet deals at 2–4% and then one at 34%, which is what gives the anomaly
detector a real average to measure against; several quotations are backdated past the
stall window; one confirmed order sits past its delivery promise with stock still short.
An empty dashboard would prove nothing on stage.

**Tests: 170 → 218.** New files: `test_stage_lock.py` (the three bugs, as regressions),
`test_subscriptions_and_health.py` (both ADRs, including that moving a setting moves the
result — the property that makes it configuration), `test_new_screens.py` (every new URL
renders, the report filters narrow, and the CSV export obeys the same filters as the
screen). `test_billing.py`'s `StillStubbedTests` was replaced: asserting the stubs stay
stubs was correct while the decision was open and wrong once it closed.

---

## T-37 — Profile area, role-correct navigation, pipeline board

*Completed 05 Sep 2026.*

**The profile screen (`/workspace/profile/`).** Four tabs over one user row, switched by a
query parameter rather than JavaScript, so every tab is a real linkable URL and the page
works with scripting off.

| Tab | What it answers |
|---|---|
| Overview | Who you are, four figures about your own deals, and what the problem statement says your role is for |
| Activity | Your own rows from the audit trail — the same log the approval screen reads, not a second one |
| Access | Which screens your role reaches, ticked or crossed |
| Preferences | Theme, and a password change through Django's own `PasswordChangeView` and validators |

**The sidebar footer was rebuilt.** It had been a wrapping row of text links separated by
middots, which at the real sidebar width left a dangling separator and pushed "Sign out"
onto its own line. It is now an identity block linking to the profile page, over a fixed
row of icon buttons that cannot wrap.

**Role-correct navigation — the bug class this task existed for.** Approvals, Deal Health
and Reports were shown to every role and refused to Reps by `require_roles`. A link you can
see, click, and then be denied is a bug however correct the refusal is. Access is now one
table, `SCREEN_ROLES`, read by both the guard and the sidebar, so they cannot drift.

Three findings came out of auditing this properly:

1. **A Rep clicking "View approval →" on their own quotation got a 403.** The builder links
   there from any pending quote, and PDF section 3 gives the Rep "tracks approval status"
   as a duty. `approval_detail` is now readable by any internal user and actionable only by
   the approver — the decision form was already gated on `actionable`, and `approval_act`
   is guarded independently, so opening the page grants nothing.
2. **Deal Health, Reports and the CSV export had no role guard at all.** Added, matching
   PDF section 3: monitoring and platform analytics are the Manager's and Admin's.
3. **Proration and cancellation were open to any signed-in user.** PDF section 3 gives
   "reconciles recurring billing and credit notes" to Finance. Now Finance and Admin only.

**403 is a page now**, not `HttpResponseForbidden` with a line of text — it names the role
you hold, the roles required, and links to somewhere you can actually go.

**Two light-mode bugs**, both found by looking rather than by testing:

* The theme toggle wrote its label with `textContent`, which **deleted the button's SVG**
  and replaced it with the words "Dark mode", breaking the footer layout. It writes to
  `title` and the screen-reader span now.
* Every gradient tile stayed dark. Tailwind's `from-*` utility writes
  `--tw-gradient-stops` from the original colour as well as `--tw-gradient-from`, so
  overriding the one variable changed nothing. The generator rewrites both halves.
* The Back-end gear rendered as an eight-spoke star, indistinguishable at 16px from the
  theme sun beside it. It is a sliders icon now.

**The pipeline board.** Columns are colour-coded by stage and carry their own value total;
the loose "Closed" strip that used to sit under the board is a seventh column, quieter than
the rest; cards are narrower so more fit, and scroll-snap makes the horizontal scroll feel
deliberate instead of clipped.

**Tests: 218 → 229.** `test_end_to_end_roles.py` is the new one worth naming: it drives the
whole PDF section 9 flow with **each step performed by the narrowest role that should be
able to perform it**, because a suite that signs in as Admin proves nothing about the
chain. It also asserts, for every role and every screen, that the sidebar offers exactly
the links that role can open — the regression test for the bug above.

---

## T-38 to T-40 — currency, warehouses, and the performance pass

*Completed 05 Sep 2026.*

**Currency (ADR-012).** `&euro;` was a hundred template literals. It is one `money` filter
now, reading symbol, code and rate off `SalesSetting`: **₹ by default, with Indian digit
grouping** — ₹12,34,567.89, because 1,234,567 reads as foreign in the market this is built
for. Amounts are stored in a base currency and multiplied by `currency_rate` on display, so
a rate of 1.000000 changes only the symbol and a different rate converts every screen at
once. That is the smallest thing that is honestly a currency *factor* rather than a
relabelling. The setting is cached and the cache is cleared on save, because a page renders
the filter dozens of times.

**Warehouses (A4).** A list of every site with its product count, units on hand, units
reserved and how many lines sit at or below their reorder point; and a per-warehouse screen
listing every product it stocks, filterable by category. The list aggregates in the database
rather than looping, so it is three queries whatever the catalogue size.

**The footer** — "Team 317 · Odoo Hackathon 2026" — is gone from every page.

### The timezone bug

Found at 00:24 IST, which is the point. `timezone.now().date()` returns the **UTC** date.
With `TIME_ZONE = "Asia/Kolkata"`, every evening between 18:30 and midnight the application
was a day behind: invoices issued with yesterday's date, billing schedules starting
yesterday, delivery slippage counted a day short. Seven call sites moved to
`timezone.localdate()`, and a test now fails if `now().date()` reappears in either service.
An evening demo falls squarely inside that window.

### Performance

Query counts measured per screen, then the loops that grew with row count removed:

| Fix | Before | After |
|---|---|---|
| `fulfilment_list` fetched allocations inside the loop | 18 queries | 5 |
| `subscription_list` called `upcoming_schedule()` and `.count()` per order | 13 queries | 5 |
| `health.discount_anomalies` ran one `AVG` per rep | grew with headcount | 1 grouped query |
| `resolve_unit_price` used `.filter()` on a related manager, silently discarding any prefetch | 1 query per upsell suggestion | 0 |

That last one is worth remembering: `.filter()` on a related manager **always** issues a
query and ignores `prefetch_related`. `.all()` plus a Python filter uses the cache when there
is one and costs the same query when there is not.

Five indexes added, each chosen from the query log of a real screen rather than sprinkled.

**`core/tests/test_query_budget.py`** is the guarantee: it loads every list screen, inserts
250 more quotations, loads them again, and fails if any screen issues even one extra query.
It also adds ten lines to a quotation and requires the builder's query count not to rise.
Full write-up, including what is deliberately not done, in `docs/SCALE.md`.

**Tests: 229 → 234.**

---

## T-41 — Assets: what a customer owns (ADR-013)

*Completed 06 Sep 2026, from a competitor review of Salesforce Revenue Cloud and Odoo
Subscriptions.*

Both are built around an **asset** — what a customer owns right now — and their whole
right-hand side reads from it: renewals, amendments, cancellations, MRR, churn, retention.
This system went Quotation → Invoice and stopped. It could say "Acme signed a quote in
March"; it could not say "Acme owns three Care Plans worth ₹1,440 a month, expiring
14 October", which is where a renewals conversation actually starts.

**What shipped.**

| Piece | Detail |
|---|---|
| `Asset` model | One row per confirmed line, `source_line` unique and PROTECT |
| `assets.create_from_confirmation()` | Runs from the same hook that builds the billing schedule, so an asset cannot exist for an unconfirmed order. Idempotent — both confirmation paths reach it |
| `mrr_summary()` | MRR **normalised to one month** whatever the interval, plus ARR and contract counts |
| `due_for_renewal()` | Contracts ending inside a window, lapsed ones included and sorted first |
| `create_renewal_quotation()` | One draft covering everything a customer has expiring, **priced at today's price list, not the original order's** |
| Customers screen | Every account, what it owns, what it earns; MRR/ARR/contracts/paying-customers tiles |
| Customer detail | Assets with term and status, plus quotation history |
| Renewals queue | Grouped by account, MRR at risk, one button per customer |

**Two decisions worth keeping.** A one-time line becomes an asset with no end date, because
owning a laptop does not expire and "what does this customer own" is not a subscription-only
question. And a renewal is priced at today's list rather than carrying the old price
forward, because a renewal is a new agreement and quiet price carry-forward is how margin
leaks — the rep sees both numbers.

**A bug the existing suite caught immediately:** `Asset` holds PROTECT keys to lines,
quotations, customers and products, so `seed_demo`'s wipe failed on its second run. The
re-seed test found it in the same minute it was introduced, rather than at 09:50 on stage.

**Deliberately not built:** amendments and co-terming, cancellation refunds against assets,
churn and cohort analytics. Each needs this spine and each is real work — recorded in
`docs/NEXT.md` alongside the rest of the competitor gap analysis.

**Tests: 234 → 257.**
