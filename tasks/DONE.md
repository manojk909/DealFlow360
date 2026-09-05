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
