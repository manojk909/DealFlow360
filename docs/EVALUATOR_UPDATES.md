# Evaluator Update Log — DealFlow360

**Odoo Hackathon 2026 · Final Round · Team 317**
Problem statement: **DealFlow360 — An Intelligent, Self-Governing Sales Operations Platform**
Evaluator: Karan Israni (kais@odoo.com · GitHub `kais-odoo`, `hackathon-odoo`)

> Read the current round's section aloud at each check-in. Add a new round section as the
> hackathon progresses; do not rewrite earlier rounds — the history is the point.
>
> **This file is written to be spoken.** The round sections run in order first. The
> three standing sections after them — "Likely questions and our answers", the open
> decisions, and the known risks — are reference for every round, not just one.

---

## Round 1 — Tech stack and approach

*Logged 05 Sep 2026, ~11:45 IST*

### Team

**Team 317 is one person.** This is a solo build, which Odoo's registration rules allow.
The tech stack table below was written when the plan still assumed four developers, so a
few of its sentences say "four people" and "four laptops". Those are left exactly as
written rather than quietly edited — the reasoning behind each choice did not change, only
the number of people carrying it out.

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
duplicated in Pydantic and TypeScript and nothing keeping them in sync. Next.js was
rejected on fluency rather than merit. We chose the stack that spends the available hours
on business logic instead of plumbing — which matters more, not less, with one developer.

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

### Status at this round

Documentation system complete. Application implementation has not started.
Next task: **T-01 — project scaffold and database connection.**

---

## Round 2 — Decisions closed, schema and seed live, services under contract

*Logged 05 Sep 2026*

Five pieces of work landed since Round 1: **T-00** closed the blocking decisions, **T-01**
stood up the application, **T-02 and T-03** built the whole schema and the seed in one
migration wave, and a **contract pass** fixed the interfaces of the services layer before
any of it was written. Every change is committed and pushed; `git log` is the record.

Nothing in this section is a plan. Every claim below is something that runs today and can
be checked in the repository.

---

### T-00 — We closed the four decisions that were blocking everything

The problem statement describes what the system should *do* but, in four places, not how.
We had deliberately left those open in Round 1 rather than guessing early. This round we
closed them, and each one is written up in `docs/DECISIONS.md` with the decision, the
reason, and the consequences — including the alternatives we rejected and why.

**ADR-005, the blended discount risk score.** This is the important one, because it is the
number that decides who reviews a deal. Here it is in one sentence:

> **The risk score is the total number of discount percentage points given away above
> ceiling across the whole quotation, where every line is measured against the stricter of
> the customer's tier ceiling and its own category ceiling.**

That is the whole rule. If a line is inside its limit it contributes nothing. If it is over,
it contributes however many points it is over by. Add those up and that is the score.

We chose it because it is the shortest rule that does both things the problem statement
asks for, and because a judge can check it by hand against the breakdown on our approval
screen — the column adds up to the number at the top.

**Both worked examples from PDF §10, with the arithmetic.**

*Example one — the Gold customer.* Gold is allowed fifteen percent overall. Hardware is
capped at fifteen, Services at ten.

| Line | Category | Discount given | Ceiling that applies | Points over |
|---|---|---|---|---|
| Laptop Pro 14 | Hardware | 12% | `min(15, 15)` = 15 | 0 |
| Onsite Setup Service | Services | 18% | `min(15, 10)` = **10** | **8** |
| | | | **Score** | **8.00** |

The laptop is fine. The service line is eight points over *its own* ceiling, and that one
line flags the entire quotation — even though eighteen percent "sounds fine on paper" for a
Gold customer who is allowed fifteen. That is exactly the point the PDF makes.

*Example two — many small overages.* Three lines, none of them alarming on its own.

| Line | Category | Discount given | Ceiling | Points over |
|---|---|---|---|---|
| Laptop Pro 14 | Hardware | 17% | 15 | 2 |
| Onsite Setup Service | Services | 13% | 10 | 3 |
| Care Plan 2yr | Subscriptions | 14% | 12 | 2 |
| | | | **Score** | **7.00** |

No single line looks bad. Together the rep has quietly given away seven points of margin,
and the quotation is flagged. That is what "blended" means, and it is why the score is
order-wide rather than a check on the worst line.

**Where the routing thresholds live.** Not in code. They are three rows in an
`ApprovalChainRule` table, which an admin can edit:

| Score from | Score to | Manager | Finance |
|---|---|---|---|
| 0.00 | 0.00 | no | no |
| 0.01 | 7.99 | **yes** | no |
| 8.00 | 9999.99 | **yes** | **yes** |

So example one, at 8.00, needs the Sales Manager and then Finance. Example two, at 7.00,
stops at the Manager. The eight-point boundary is not arbitrary — it is the PDF's own
example of a serious overage. Change a row in that table and routing changes on the next
quotation with no code change at all.

**The other three decisions, briefly.**

*ADR-006, the warehouse split.* Fill each line from the cheapest warehouse first and spill
into the next cheapest — except that if the cheapest warehouse can cover the whole line by
itself, it ships alone. Anything left over becomes a backorder. We call it a heuristic in
the decision record, on the screen, and here, because that is what it is.

*ADR-004, portal access.* A signed token in the URL, one token per quotation, copied from
the internal screen. No customer accounts, no passwords, no email. A tampered token gets a
403, never the quotation.

*ADR-010, the quotation stage machine.* One field with ten stages. What the customer sees
in the portal is a display mapping over that field, not a second stored field that could
drift out of step with the first.

---

### T-01 — The application runs, and the health page proves it

Django 5.2 on SQLite, a custom user model carrying the four roles, and a `/health/` page.

**Why a health page at all.** Because "it compiles" is not evidence. Every value on that
page is read from the database on each request — the SQLite version from a real cursor, the
applied migration count from Django's own migrations table, the number of users, the roles
present. We tested it by creating a user through the ORM and watching the count go from one
to two and a Finance badge appear, then deleting that user and watching it go back. If the
database were missing or unmigrated the page would fail loudly rather than render something
reassuring.

**The one thing that had to be right first.** Django's user model must be swapped *before*
the first migration runs. Changing it afterwards means deleting the database and every
migration and starting over. So `AUTH_USER_MODEL` was set, the custom user written, and
only then was `migrate` run for the first time.

**The bug the clean-clone test caught.** We verified the setup instructions by actually
doing them: cloned the repository into an empty directory, created a virtual environment,
installed from `requirements.txt`, migrated, created a superuser, and started the server —
following only what the README said. Doing that surfaced a real defect. The Django admin's
add-user form referenced a field called `usable_password`, which exists on Django 5.1 and
later's `AdminUserCreationForm` but *not* on the older `UserCreationForm` we had
subclassed. The page returned a 500 with a `FieldError`.

The reason this is worth telling you: `manage.py check` reported no issues. The system
check does not build admin forms, so nothing caught it until a browser actually loaded
`/admin/core/user/add/`. It is a small bug, but it is the kind that surfaces on stage
rather than in a terminal, and the clean-clone test is what found it.

---

### T-02 and T-03 — The whole schema and the seed, in one migration wave

**Twenty-two models in total, twenty-one of them added in this wave** — the custom user
came with T-01. They are split across five files by domain — catalogue, parties, sales,
inventory, billing — and one `makemigrations`, one `migrate`.

**Why one wave.** Because a migration is the one thing that is expensive to get wrong. We
built the entire data model at once, including three entities the specification marks as
lower priority — product variants, product co-purchase pairs, and billing schedule entries.
Three small tables now, against three more migration waves later when those features come
up. Being solo makes that cheaper, not riskier: there is nobody else's migration to collide
with.

**Twelve invariants are enforced by the database itself, and we proved it by breaking
each one.** These are not form validations that a direct database write could sidestep.
For each, we deliberately attempted the illegal thing and confirmed SQLite refused it:

| # | What we tried | What refused it |
|---|---|---|
| 1 | Two stock rows for the same product in the same warehouse | `unique_stock_per_product_warehouse` |
| 2 | Reserving more stock than is on hand | `stock_reserved_not_over_on_hand` |
| 3 | A recurring line with no subscription plan | `recurring_line_has_plan_one_time_does_not` |
| 4 | A one-time line carrying a subscription plan | the same constraint, other direction |
| 5 | A line discount above 100% | `quotation_line_discount_in_range` |
| 6 | A line with a quantity of zero | `quotation_line_qty_positive` |
| 7 | An approval band whose maximum is below its minimum | `chain_rule_band_ordered` |
| 8 | A product with a negative cost | `product_cost_non_negative` |
| 9 | A payment of zero | `payment_amount_positive` |
| 10 | A product paired with itself | `product_pair_not_self` |
| 11 | Two approval steps with the same sequence on one quotation | `unique_step_sequence_per_quotation` |
| 12 | A duplicate quotation number | the unique constraint on `Quotation.number` |

**One invariant we could not put in the database, and we say so rather than hide it.** The
rule that payments never exceed an invoice's amount needs a subquery, which SQLite cannot
express in a CHECK constraint. It is enforced in the billing service instead, which is the
only place in the codebase permitted to record a payment or move an invoice's status. That
is written on the model, in the service, and in the verification output — so its absence
from the schema is a documented decision, not something we missed.

**The seed.** `python manage.py seed_demo` rebuilds the exact demo state: eight users,
three tiers, three categories, three category ceilings, three approval chain rules, three
customers, ten products each with a cost, four variants, thirty price-list entries, six
product pairs, three subscription plans, two warehouses, eight stock rows and five
quotations. It is idempotent — we ran it three times and compared row counts.

**How we verified the seed, and why the method matters.** The seed writes a risk score onto
a quotation. Checking that score with the same code that wrote it proves nothing. So we
wrote a separate verification script that **imports nothing from the seed command**. It
reads the configuration rows out of the database — the tier ceiling, the category ceilings,
the line discounts — and applies ADR-005's rule, written fresh, to them.

It confirmed:

- The seeded Acme quotation `Q-2026-0003` recomputes to **exactly 8.00**, and the score
  stored on the row matches that recomputation.
- 8.00 matches the `8.00 to 9999.99` chain rule, which requires Manager and then Finance —
  and the two approval steps sitting on that quotation are exactly Manager then Finance,
  both pending.
- The three approval bands tile with no gap and no overlap.
- The PDF's second example totals **7.00** against the seeded Gold ceilings and lands in the
  Manager-only band. So both worked examples are exercised by real configuration rows, not
  by test constants.

**The stock numbers, and why they are what they are.** Laptop Pro 14: Main Warehouse holds
**4**, East Depot holds **10**, and the demo order is **6**.

Main Warehouse is the cheaper of the two — shipping weight 1.00 against East Depot's 1.40.
Under our rule the cheapest warehouse would ship the whole line alone if it could, but Main
only has 4 of the 6. So the split is forced:

> **4 from Main Warehouse, 2 from East Depot. Two shipments. Estimated cost
> `4 × 1.00 + 2 × 1.40 = 6.80`.**

**The trade-off we want to state before you ask it.** East Depot alone has 10 units and
could have shipped all 6 in a *single* shipment. That is one fewer shipment. But it costs
`6 × 1.40 = 8.40` against our 6.80 — roughly 24 percent more. So we read the problem
statement's "minimise number of shipments" as *weighted by shipping cost*, which is what
the same sentence in section A4 also says. If you ask why not one shipment from East Depot,
the answer is a number already on the screen: 8.40 against 6.80.

We also rejected the strict alternative — fewest shipments first, cost only as a
tie-breaker — in writing, for two reasons. It produces the more expensive plan, and with
this stock it produces no split at all, which would make the acceptance criterion about
splitting across two warehouses impossible to demonstrate.

---

### The contract pass — interfaces agreed before implementations

Before writing a single service body, we wrote the whole services layer as signatures and
docstrings with `NotImplementedError` bodies: **eight modules, thirty-nine functions,
eleven data structures and exception types.** Then we committed that as the integration
contract.

**Why.** Pricing, risk, approval, fulfilment, billing, negotiation, upsell and health all
call each other. Writing them one at a time and discovering at hour eighteen that two of
them disagree about a shape is a predictable, expensive failure. Fixing the interfaces
first makes that impossible.

The contract pins down more than argument lists. Three examples:

- The risk scorer is **pure** — plain dictionaries and decimals in, a result object out, no
  database. That is what lets the specification tests run without fixtures.
- The approval router **raises** when no chain rule matches a score, rather than falling
  through to "no approval needed". Silently skipping governance is the exact failure this
  product exists to prevent, so a misconfigured chain stops the submit.
- Accepting a warehouse split **recomputes at the moment of commit** rather than trusting
  what the screen was showing, because stock can move between the page load and the click.

**Three functions are deliberately blocked rather than guessed.** Subscription proration is
blocked on ADR-008. Discount anomaly detection and delivery slippage are blocked on
ADR-007. Their docstrings name the decision that blocks them and why, so nobody implements
a threshold the problem statement never gave.

**One more thing about the tests.** The two specification tests for the risk score were
written *before* the formula was chosen — that was deliberate, so the PDF's examples are
the specification rather than a description of whatever we happened to build. They live in
`core/tests/test_risk.py` and currently skip, with a reason that names the task that will
make them pass. The moment the risk service is implemented and wrong, they go red.

---

### Status at this round

**Working today:** the app runs; the database rebuilds from nothing in seconds with
`migrate` and `seed_demo`; the full schema with its constraints; Django admin login; the
health page; the seeded demo state with a quotation that scores exactly what the decision
record predicts.

**Not built yet:** every screen. The rep workspace, the quotation builder, the approval
screen, the fulfilment screen and the customer portal are all still to come, as is every
service body. We are being explicit about that rather than describing a plan as if it were
a feature.

**Next:** T-04, internal authentication and role-based access, then registering the
configuration models in Django admin.

---

## Round 3 — Flow A works end to end: quotation to cash

*Logged 05 Sep 2026*

Since Round 2 the application stopped being a schema and became a product. **The first of
our two demo flows now runs end to end in the browser**: a rep builds a quotation, the
system routes it for approval on its own, two approvers act, stock splits across two
warehouses, an invoice is raised and a payment closes it.

Six pieces of work landed: the pricing engine, the risk score, approval routing, the three
internal screens, the warehouse split with its screen, and invoicing with its screen. The
test suite went from 2 tests to **88, all passing, none skipped**.

---

### What we can now show, and what each part is for

**Pricing.** Line total is quantity times unit price less the line discount; the
order-level discount then applies to the *sum* of already-discounted lines. That ordering
matters more than it looks: two units at a thousand, less ten percent then five percent, is
1710.00 — where discounting the gross by fifteen percent would give 1700.00. A test asserts
that difference on purpose, because it is the kind of thing that looks right either way
until somebody checks. Every figure is a `Decimal` computed in Python; nothing sums money
through the database.

**The risk score.** The formula we described last round is now the code, and the two
worked examples from the problem statement are unit tests that **run and pass** rather than
skip. They were written before the formula was chosen, and neither expectation has been
edited since — the same file, unchanged. The Gold example scores exactly 8.00, the
several-small-overages example exactly 7.00.

One correction worth telling you, because it changed our own understanding. We assumed that
raising the Services category ceiling from ten to eighteen would take that quotation's
score to zero. It does not — it takes it to 3.00, because the effective ceiling is the
*stricter* of the tier ceiling and the category ceiling, and the Gold tier caps at fifteen.
Loosening only the category ceiling cannot lift a line past the tier cap. The code was
right and our expectation was wrong. There are now tests for both halves of that rule.

**Approval routing.** This is the product's thesis, so it is worth being precise. The rep
clicks *Submit*. They do not request approval and there is no button that would let them.
The system recomputes the pricing, scores the quotation, reads the approval bands out of
the database and generates the reviewer steps it needs. With the seeded configuration the
worked example produces Manager and then Finance; a smaller overage produces Manager only;
a clean quotation skips approval entirely and goes straight to approved.

If a score matches no configured band, the submit **stops with an error** rather than
falling through to "no approval needed". Silently skipping governance is the exact failure
this product exists to prevent, so a misconfigured chain must be loud.

Approve, reject and return-for-revision each require a reason, and each writes an audit row
with the user, the reason and the timestamp. Reject is terminal and leaves the untouched
Finance step in place so the trail shows how far the deal got. Return sends the quotation
back to draft and clears the pending steps, because the next submit re-scores and the
numbers will have changed. A quotation cannot reach approved while any step is still
pending, and a rep calling the approval function is refused by the service itself, not by a
hidden button.

**The three internal screens.** The quotation list is cards in stage columns, following the
mockup — a rep scans a pipeline, they do not read a spreadsheet. The builder has a product
picker by category, quantity steppers and per-line discount inputs, and beside every line a
**Discount / Limit / Status** column that shows `OK` or `OVER +8 pt` the moment a discount
is typed, not at submit. Every edit swaps one region of the page, so the line totals, the
order total, the live margin indicator and the ceiling check are produced together by the
same two service calls and cannot drift apart. There is no full page reload anywhere in the
builder.

The approval screen shows the blended score with the **given / allowed / over-by breakdown
that produced it** directly underneath, footed by the score itself, so an approver can add
the column up by hand. That is deliberate: a score somebody cannot check is a score they
will not trust.

**The warehouse split.** Computed from live stock every time it is asked for — never cached
and never seeded. On the demo order of six laptops it pulls **four from Main Warehouse and
two from East Depot**: two shipments at an estimated cost of 6.80.

We say on the screen, not just in a document, that this is a heuristic and not an optimiser,
and that lines are solved independently so the shipment count across a multi-line order is
not globally optimal. The screen also explains that shipments are minimised *weighted by
shipping cost* — which is the answer to "why not one shipment from East Depot?" before
anyone has to ask it. That plan is one fewer shipment but costs 8.40 against our 6.80.

The screen also names the lines that are **not warehoused** — the setup service — and says
they are skipped rather than backordered. You do not warehouse a consulting engagement, and
a naive implementation would have reported that line as a total backorder and made the
screen look broken. We found that while writing the seed, before writing the split, and
wrote it into the task as an acceptance criterion.

**Invoicing and payment.** One-time lines bill through an invoice. Recurring lines do not —
they bill on a schedule instead, and the screen shows them in a separate table and says in
plain words that they are deliberately excluded. On the demo order the invoice is 7740.60,
with 456.00 of subscription value correctly left off it.

Invoice status is **derived** from the sum of payments, never assigned. Half paid derives
partial; paid in full derives paid and moves the order to paid. Paying more than the
outstanding amount is refused and writes no payment row at all — refused rather than
clamped, because capping an overpayment silently would make the status a lie. SQLite cannot
express that rule as a database constraint, so the billing service is the only thing in the
codebase permitted to write a payment or move an invoice status, and the admin registers
payments read-only to match.

---

### How we verified it

Not by loading a page and looking at it. We drove the whole flow through the real views as
a browser would — every step an HTTP request, no service called directly — and asserted
what came back:

| Criterion | Result |
|---|---|
| AC-2 | The 18% service line shows `OVER +8 pt` as it is typed |
| AC-3 | Submit routes to Manager then Finance by itself, score 8.00 |
| AC-5 | Split lands 4 from Main and 2 from East, cost 6.80, two allocation rows, no backorder, and the service line is named as not warehoused |
| AC-6 | Invoice is 7740.60 — the one-time lines only — with 456.00 of recurring excluded |
| AC-8 | Overpayment refused with no payment row; half payment derives partial; the remainder derives paid and the order reaches paid |

The audit trail that run produced, in order: submitted for approval, approved, approved,
order confirmed, split accepted, invoice generated, and two payments recorded — each with a
user, a reason and a timestamp.

We also closed the one piece of scaffolding we told you about last round. The seed script
carried provisional copies of the pricing and risk arithmetic, because it had to store
numbers before either service existed. **Both are deleted.** The seed now calls the real
services, so the seeded score of 8.00 comes from the same code path that scores a quotation
at submit time and the demo data cannot drift away from the behaviour it demonstrates. That
was a written acceptance criterion on those two tasks, not a comment we hoped to remember.

**There is now no arithmetic anywhere outside the services layer.** No template computes a
total, no view holds a business rule.

---

### Currently building

The customer portal — T-14 and T-15. That is Flow B, and it is the moment we most want to
show you: a customer counters a discount from a separate, restricted screen with no account
at all, and the quotation re-enters approval on its own.

### Blocked on / open decisions

Nothing on the critical path. The same three decisions remain deliberately open —
deal-health thresholds, the subscription proration basis, and the treatment of tax — and
all three still block only SHOULD-priority features. The proration function raises an error
naming the decision that blocks it, so it cannot be called by accident.

### Risks

- ~~The portal is the last MUST-have screen and it is not built.~~ **Closed at Round 4** —
  built, and all eight acceptance criteria now pass.
- Recurring billing *schedules* are still not built. We can show that subscription lines are
  correctly kept off the invoice; we cannot yet show the schedule they bill on. This is the
  one half-present feature and it is named as such in `docs/NEXT.md`.
- The split is per line, so on a multi-line order it can suggest more shipments than a
  global optimiser would. Documented, tested, and named on the screen rather than hidden.

---

## Round 4 — Both flows complete, and all eight criteria pass

*Logged 05 Sep 2026*

**The application is feature-complete against every MUST in the problem statement, and all
eight acceptance criteria pass.** We ran them in one continuous sitting against a database
rebuilt from nothing, driving the real screens over HTTP — 44 individual checks, no
failures.

Since Round 3: the customer portal, the negotiation loop, the upsell panel, signup, the
acceptance gate, a validation and offline pass, and the two closing deliverables.

---

### The customer portal, and why it is a separate application

The problem statement is specific that the customer-facing screen must be a genuinely
separate, restricted view and not an internal screen with a different label. So it is a
separate Django app, on its own URL prefix, with its own base template and a **light**
theme that shares no chrome at all with the dark internal workspace. A customer should
never wonder whether they are looking at somebody's back office.

Access is a signed token in the link, and nothing else. There is no customer account, no
password and no email. The token resolves to exactly one quotation, and we check that twice
on purpose: the signature already binds it to one id, and the quotation must also still hold
that exact token, so a link that was rotated or never issued is refused as well.

Every way of arriving without the right token — missing, malformed, tampered, unknown, or a
token the quotation does not hold — returns the **same** 403. One response for all of them,
because telling the difference between "bad signature" and "no such quotation" would tell
somebody which quotation ids exist. Never the quotation, and never a redirect to our
internal login.

Two things we test that are easy to leave untested: the portal code contains neither
`request.user` nor `login_required` anywhere in its executable body, and an authenticated
superuser gets **no** special treatment — the portal is scoped by token, not by permission.

What the customer sees is deliberately not an admin table. Lines are readable blocks with the
discount called out. The conversation is rendered as a conversation — their messages on one
side, the account manager's on the other, each with an author and a time — and it is
append-only, because a negotiation history that can be rewritten is not a history. They never
see an internal approval stage: while a request is with us, the page says exactly that.

---

### The moment the product exists for

A customer, with no account, opens their link, comments on a line, and proposes a different
discount. The quotation re-scores and **re-enters the approval chain by itself**, with fresh
approver steps. Nobody asked it to.

One detail in there is load-bearing and we got it right deliberately, because getting it
wrong would have broken the walkthrough in a way that looks like the product not working.
**A counter-discount replaces the line's discount. It does not stack on top of it.** Beta
Industries is a Silver customer with a 10% ceiling and their service line already carries 8%.
A 15% counter must leave it at 15% — five points over, which routes to the Sales Manager
alone. Stacking would have compounded 8% and 15% into roughly 21.8%, pulled Finance into the
chain, and left the demo waiting for an approval that was never going to appear on screen.

We also refuse to let the customer confirm while an approval is outstanding, and the page
tells them why without naming an internal stage.

---

### The upsell panel, and a mistake worth telling you about

Ranked from co-purchase history with promoted products given a 50% boost, showing the margin
change each suggestion would produce. It lives **inside** the live region of the builder, so
accepting one updates the lines, the order total, the margin indicator and the remaining
suggestions in a single exchange — no page reload. On the demo order the total moves from
7740.60 to 8196.60 and the new margin comes back in that same response.

The mistake: we first applied the minimum-margin threshold to the margin the *order* would be
left with. That does nothing. On a quotation dominated by a six-unit laptop line, adding a
€100 cable with a 1% margin barely moves the total and sailed straight through — which is
exactly the case the rule exists to stop. The threshold is about the **suggested product's
own** margin. Our tests caught it, we corrected it, and the reasoning is written beside the
check so nobody re-introduces it.

---

### Signup, and a decision we thought was worth making carefully

The acceptance test opens with "sign up or log in", and we had no signup page. Now we do,
and it creates a **Sales Rep** — nothing else.

There is no role dropdown, and `role` is not in the form's field list, so a crafted request
carrying `role=MANAGER` has nothing to bind to. The save then sets the role explicitly rather
than relying on a model default, so the guarantee does not quietly depend on a default
somebody could change later for an unrelated reason. Manager, Finance and Admin are granted
by an administrator.

We want to be clear this is a design decision and not an omission, because the alternative is
worse than a security weakness. This is a product whose entire thesis is that discounts are
governed by somebody other than the person giving them away. A signup form with a role
dropdown would let anyone grant themselves approval rights — and a judge who typed MANAGER
into that box would have disproved the demo in ten seconds. It is written up as ADR-012.

---

### The gate: eight criteria, 44 checks, one pass

`scripts/ac_gate.py` runs all eight acceptance criteria in sequence against a freshly seeded
database. The observed result for each is recorded in `docs/ACCEPTANCE.md` rather than
summarised as a tick.

| # | Criterion | Result |
|---|---|---|
| AC-1 | Sign up, then set up a tier, a warehouse and a plan | **PASS** — Platinum, North Hub and Gate Monthly created through the admin and still there on reload |
| AC-2 | A line discounted beyond what is allowed | **PASS** — saves at 18% and shows `OVER +8 pt` as it is typed |
| AC-3 | Confirm; it asks for approval automatically | **PASS** — `PENDING_APPROVAL`, score 8.00, Manager then Finance generated by the system; a rep posting at the approval endpoint gets 403 |
| AC-4 | Accept an upsell; total and margin update right away | **PASS** — 7740.60 → 8196.60 in a partial, no page reload |
| AC-5 | Fulfilment splits across warehouses | **PASS** — 4 from Main, 2 from East, cost 6.80; the service line named as skipped, not backordered |
| AC-6 | One-time and recurring billed separately | **PASS** — 7740.60 invoiced, 456.00 excluded |
| AC-7 | Customer requests a bigger discount | **PASS** — replaced 8% with 15%, re-scored to 5.00, back to approval on its own with a Manager step only |
| AC-8 | Record a payment; status updates | **PASS** — overpayment refused with no payment row; PARTIAL then PAID |

Three caveats we would rather say than have found. The pass is automated, so it proves values
and not appearance — that is what the rehearsal is for. AC-6 proves the separation is real but
the recurring *schedule* is not built. And AC-1 was satisfied through Django admin, which is
the backend configuration area by design, not a shortcut.

---

### Two things Odoo scores regardless of features

**The demo no longer depends on the venue wifi.** Tailwind and HTMX were CDN script tags; they
are now files in our own static directory, and a test fails if any template ever reaches for a
CDN again. The whole application runs with the network unplugged.

**Validation and layout.** Eleven tests push bad input through the real endpoints — a discount
of 150 and of "twelve", a zero quantity, a blank approval reason, an override beyond available
stock, an overpayment, a portal counter of 250 — and assert a visible message, never a 500,
and nothing written. Layout is checked as containment: every wide table scrolls inside its own
container rather than the page, no fixed width exceeds a 375-pixel viewport, and four real
overflow risks were fixed. That is a mechanical check, not a rendered one, and we say so.

---

### Status at this round

**Working:** every MUST feature. Configuration, quotation building with a live margin and
per-line ceiling checks, automatic approval routing with a full audit trail, the warehouse
split, invoicing and payment, the customer portal with the automatic re-approval loop, the
upsell panel, and signup. **170 tests, all passing.**

**Deliverables:** the one-page architecture diagram (`docs/architecture.html`, self-contained,
opens with no network) and the what-we-would-build-next note (`docs/NEXT.md`).

**Not built, and labelled as such in the product itself:** recurring billing schedules, the
deal health dashboard, and reporting. The workspace greys those tabs out and names the task
behind each rather than hiding them.

**Next:** rehearse and record the five-minute demo.

---

## Likely questions and our answers

*Standing reference for any round. One paragraph each, written to be said out loud.*

### Why does the risk score ignore how much a line is worth?

Because the problem statement's own worked examples are stated purely in percentage points,
with no quantities and no prices anywhere in them. A value-weighted score cannot reproduce
them — the eight-point service line would be diluted to almost nothing sitting next to six
laptops, and the example the PDF chose to complain about would stop flagging. We treated
those examples as the specification and made the formula follow them. We know the
limitation: a twenty percent discount on a five-euro item scores the same as one on a
five-thousand-euro item. The live margin indicator is the separate signal that carries
value, and value-weighting the risk score is the first item on our "what we would build
next" list. It is recorded as a deliberate simplification in ADR-005, not discovered now.

### Is anything hardcoded or faked for the demo?

One thing, and we would rather tell you about it than have you find it. The seed script
contains two helper functions, `_totals` and `_risk_score`, that duplicate arithmetic which
properly belongs in the pricing and risk services. They exist because the seed has to store
totals and a risk score onto quotations, and those two services are not written yet — and a
quotation list where every card reads zero is not a demo. They are marked `PROVISIONAL` in
capitals in the file, with a comment saying which task deletes each one and that if a
service and a helper ever disagree, the service is right. Deleting them is a written
acceptance criterion on T-08 and T-09 in the backlog, not a comment we hope to remember.
Beyond that: nothing is hardcoded. The risk score, the approval routing thresholds, the
category ceilings, the shipping weights and the stock levels are all database rows, and the
verification we ran reads them out of the database rather than asserting constants.

### Why SQLite and not PostgreSQL?

We were told to use a local database, and SQLite is local in the strictest sense — one file
inside the repository folder. Postgres is not installed on this machine and Docker is not
available, so choosing it would have meant installing and configuring a database service
during the build for no benefit at demo scale. It is Django's default backend, so it is the
same ORM, the same models and the same migrations as any other database; nothing about the
data model is compromised, and we avoid Postgres-only field types so the backend stays
swappable. The one real consequence is that SQLite has no decimal type, which is why every
money calculation happens in Python with `Decimal` inside the services layer and never
through a database aggregate — a `SUM` over a decimal column can come back as a float and
drift. That was decided up front rather than debugged later, and it is written in ADR-002.

### Why Django rather than FastAPI or Next.js?

Because Django ships the parts of this problem we would otherwise hand-write. The problem
statement asks for a backend configuration area — products, price lists, discount tiers,
category ceilings, approval chains, warehouses, stock. That is about seven CRUD screens,
and Django's admin gives them to us driven straight from the models, with search, filters
and validation. Its authentication gives us sessions and password hashing already correct.
FastAPI would have meant roughly sixty hand-written endpoints plus a separate React
frontend, with the entities defined twice — once in Pydantic, once in TypeScript — and
nothing keeping the two in sync. Next.js we rejected on fluency rather than merit. The
hours saved on plumbing go into the discount governance and the warehouse splitting, which
is what the problem statement says it is actually testing. We use the admin for the
configuration area only; the rep workspace, the approval screen, the fulfilment screen and
the portal are all hand-built, because leaning on the admin for those would read as
unfinished.

### Why is the customer portal a separate app rather than a flag on the internal one?

Because the problem statement requires it to be a genuinely separate, restricted view and
not an internal screen with a different label, and a flag would be exactly the second
thing. The portal is its own Django app with its own URL prefix, its own base template and
its own access rule. Access is a signed token that resolves to exactly one quotation — so a
customer seeing only their own quotation is enforced by the URL itself rather than by a
permission check somebody could forget to write. Portal views are forbidden from sitting
behind the login decorator and forbidden from reading the current user at all, because a
customer has no account. A tampered or unknown token returns a 403, never the quotation and
never a redirect to the internal login page. The app exists in the repository today with
its URL file reserved and mounted; the views land in T-14, and it returns a 404 until then,
which is honest rather than a stub pretending to work.

### Why are three lower-priority entities already in the schema?

Product variants, product co-purchase pairs and billing schedule entries are all marked
SHOULD in our specification, and their features are not built yet. They are in the schema
because a migration wave is the one thing that is genuinely expensive to redo, and adding
three small tables now costs three tables — whereas adding them later costs three separate
migration waves at exactly the point in the build when we can least afford them. The tables
are empty of behaviour: no service reads them yet, and nothing in the application pretends
they do anything. The seed does put rows in them, so that when the upsell panel and the
subscription screen are built there is real data waiting rather than a fixture written that
afternoon.

### What is not built yet, and why that order?

Every screen. The rep workspace, quotation builder, approval screen, fulfilment screen and
customer portal are all still to come, and so is every service body — they are signatures
and docstrings today. The order is dependency-driven, and it is in `tasks/BACKLOG.md` where
you can check it. Authentication comes next because everything else sits behind a role
check. Then the configuration screens, because until a discount ceiling can be edited
through a screen, the first acceptance criterion in the test flow cannot be demonstrated at
all. Then pricing, then the risk score, then approval routing — that chain is the critical
path, because the automatic routing is the product's entire thesis and nothing else is
worth showing without it. Fulfilment, billing and the portal follow. The deal health
dashboard and reporting are last on purpose: they are the two things we would cut first if
we run out of hours, and putting them last means running out of hours cuts them
automatically rather than by panic.

### Can someone sign themselves up as a manager and approve their own discounts?

No, and it is worth explaining why rather than just saying no. Self-signup creates a Sales
Rep and nothing else. There is no role dropdown on the form, and the role field is not in the
form's field list at all, so a crafted request carrying `role=MANAGER` has nothing to bind to
— it is not filtered out afterwards, it never had anywhere to land. The save then sets the
role explicitly rather than trusting a model default. Manager, Finance and Admin are granted
by an administrator through the backend. We made this decision deliberately and wrote it up
as ADR-012, because the alternative is worse than a security weakness: this is a product
whose whole thesis is that discounts are governed by somebody other than the person giving
them away, and a role dropdown would let a visitor disprove that in ten seconds. There is a
test that a signup attempting to be a manager still lands as a rep and still gets a 403 from
the approvals screen.

### Does the demo need the internet?

No. It did until Round 4 — Tailwind and HTMX were CDN script tags — and now they are files in
our own static directory, served by Django. There is a test that fails if any template ever
references a CDN again, or any absolute http asset URL. The database is a single local file,
no email is sent, and there is no external integration of any kind. The whole application
runs with the network unplugged, which is what Odoo's guidance about planning for offline
operation actually asks for.

### Did you use AI?

Yes. Claude Code was used as a pair programmer throughout — writing code, reviewing it, and
working through the design. What that did not do is make the decisions. Every architectural
choice in this project is written up in `docs/DECISIONS.md` as a numbered decision record
with the context, the decision, the reasoning and the consequences, including the
alternatives that were rejected and why. There are ten of them. Ask me about any one and I
will explain it — why the risk score adds percentage points instead of weighting by value,
why the warehouse rule prefers a cheaper two-shipment plan over a more expensive
single-shipment one, why the portal uses a signed token instead of customer accounts, why
three decisions are still deliberately open. The specification tests for the risk formula
were written before the formula was chosen, precisely so that the examples in the problem
statement drove the implementation rather than the other way round.

---

## Open decisions we deliberately have not made

Three decision records in `docs/DECISIONS.md` are still marked open. That is on purpose,
not an oversight. Each one is a place where the problem statement genuinely does not
specify an answer, and each blocks only lower-priority work. Deciding them now would mean
inventing a number and writing it into code before the task that needs it exists.

**ADR-007 — deal health thresholds.** The problem statement says a stalled deal is one
inactive for "a configured number of days" but gives no default, and defines a discount
anomaly as one "well above a rep's historical average" without quantifying "well above" or
saying over what window the average is computed. It also lists delivery promise slippage,
and there is no promise-date field anywhere in the problem statement to measure against.
Safe to defer because the deal health dashboard is a SHOULD, not a MUST, and it appears in
none of the eight acceptance criteria. **Forced by T-21.** If it is still open when that
task starts, we ship stalled-deal detection alone and label the rest incomplete, which is
what our own task file already instructs.

**ADR-008 — subscription proration basis.** Mid-cycle changes have to be prorated, but
whether that is daily pro-rata, whole-period, or something else is not stated, and neither
is how a cancellation refund is computed. Safe to defer because the acceptance criterion
that involves subscriptions checks that a one-time product and a recurring subscription on
one order bill *correctly and separately* — it does not exercise a mid-cycle change. So
hybrid billing can be demonstrated without proration being settled. **Forced by T-20.**
Until then the field on the subscription plan holds the literal value `UNDECIDED`, and the
proration function raises with a message naming the decision record, so it cannot be
accidentally called.

**ADR-009 — tax, sales teams, and replenishment rules.** Three fields the problem statement
names without defining. Tax is listed as a product field but no tax rules are given, so we
store the percentage and it participates in no total and no margin — which is written on
the model rather than left to be inferred. "Sales Team" appears as a reporting filter but
no team entity is described anywhere else. Replenishment rules are named for warehouses
without any statement of what a replenishment rule does. All three are peripheral to all
eight acceptance criteria. **Forced by T-05 and T-23** when the product configuration and
reporting screens are built.

---

## Known risks

Four things we know are fragile or unfinished. Listing them here so they are said out loud
rather than discovered.

**The split rule must skip lines for products that are not stocked.** Services and
subscriptions have no stock rows at all, which is correct — you do not warehouse a
consulting engagement. But a naive implementation of the split would report the Onsite
Setup Service line as a total backorder and the fulfilment screen would look broken during
the demo. We found this while writing the seed, before writing the split. It is recorded as
an acceptance criterion on T-16 rather than left to be discovered on stage.

**A portal counter-offer must replace a line's discount, not stack on top of it.** In the
demo's second flow, Beta Industries is a Silver customer with a ten percent ceiling and
counters at fifteen percent. Replacing the line's discount makes that five points over,
which routes to the Sales Manager only — and the demo script shows exactly one approver.
Stacking fifteen percent on top of the line's existing eight percent as a second
order-level discount would give roughly twenty-one points over, pull Finance into the
chain, and leave the walkthrough waiting for an approval that never comes. Recorded as an
acceptance criterion on T-15.

**~~No configuration model is registered in Django admin yet~~ — closed at Round 3.** All
twenty-two models are now registered and grouped into sections, so AC-1 is demonstrable: a
discount tier, a warehouse and a subscription plan can be created through a screen and are
still there on reload. We proved the configuration is real rather than decorative by
editing a ceiling *through the admin form* and watching a quotation's routing change with
no code change — 8.00 to 3.00 to 0.00 and back.

**~~The provisional arithmetic in the seed can rot silently~~ — closed at Round 3.** Both
helper functions have been deleted. The seed calls `pricing.recompute_quotation()` and
`risk.score_for_quotation()`, so there is no second implementation left to drift. Verified
by rebuilding the database from nothing and seeding three times: identical row counts, and
the same 8.00.

---

## Final submission summary — *(to be filled in)*

**Working end to end:**

**Built but not demonstrated:**

**Not built, and why:**

**What we would build next:**
