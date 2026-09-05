# System design, latency and scale

What this project is actually judged on, answered with measurements rather than adjectives.
Every number below comes from `core/tests/test_query_budget.py`, which runs in CI with the
rest of the suite — so these claims fail the build if they stop being true.

---

## 1. The shape of the system

```
                     ┌────────────────────────────────────────────┐
   internal user ───►│  core/views.py      thin: HTTP in, HTML out│
                     │        │                                   │
   customer     ───►│  portal/views.py    token-scoped, no auth   │
   (signed link)     │        │                                   │
                     │        ▼                                   │
                     │  core/services/     ALL business logic      │
                     │   pricing · risk · approval · fulfilment    │
                     │   billing · upsell · negotiation · health   │
                     │        │                                   │
                     │        ▼                                   │
                     │  core/models/       schema + invariants     │
                     └────────────────────────────────────────────┘
```

**One rule holds the design together: business logic lives in `core/services/` and nowhere
else.** Views read the request, call a service, render. The portal is a separate Django app
with its own templates and no access to `request.user` at all, yet it reaches the same
services — so a counter-offer from a customer runs exactly the code an internal edit runs,
and cannot drift from it.

That is what makes the governance claim true rather than decorative. The blended risk score
is computed in `risk.py` and read by the builder, the approval screen, the portal
re-approval loop and the reports screen. There is one implementation to be right.

### Why this matters for expansion

Adding a channel — a mobile client, a partner API, a bulk importer — means a new caller of
the same services, not a second copy of the rules. The pieces already prove it: the
customer portal was added as a whole new app without touching a single service.

---

## 2. Latency

Measured on the seeded dataset, warm, SQLite on a laptop. Queries first, because query
count is what survives a change of database and hardware.

| Screen | Queries | Render |
|---|---|---|
| Quotations / Pipeline | 3 | 8 ms |
| Warehouses | 3 | 5 ms |
| Approvals | 4 | 5 ms |
| Fulfilment list | 5 | 9 ms |
| Subscriptions | 5 | 8 ms |
| Profile | 6 | 5 ms |
| Reports (filtered) | 7 | 12 ms |
| Deal Health | 12 | 15 ms |
| Quotation builder | 25 | 20 ms |

The builder is the outlier and the reason is known: `pricing`, `risk` and `upsell` each read
the quotation's lines independently. That is a **constant** cost, not one per line — asserted
by `test_the_quotation_builder_does_not_query_per_line`, which adds ten lines and requires
the query count not to rise. Collapsing those reads into one shared pass would take the
builder to roughly eight queries; it was not done because it means threading a line list
through three services that are currently independent, and independence is what keeps the
scoring honest. It is the first thing in `docs/NEXT.md`.

---

## 3. Traffic: what actually breaks first

The failure mode that kills applications like this is not CPU. It is a query issued per row,
which looks instant on demo data and collapses at a few thousand rows. Three were found and
removed by measuring, not by reading:

| Where | Was | Now |
|---|---|---|
| `fulfilment_list` — allocations fetched inside the loop | 18 queries | 5 |
| `subscription_list` — `upcoming_schedule()` and `.count()` per order | 13 queries | 5 |
| `health.discount_anomalies` — one `AVG` per rep | grew with headcount | 1 grouped query |
| `pricing.resolve_unit_price` — `.filter()` on a related manager, ignoring prefetch | 1 query per upsell suggestion | 0 |

That last one is the instructive one. `.filter()` on a related manager *always* issues a
query, silently discarding any `prefetch_related` the caller set up. Switching to `.all()`
and filtering in Python makes the prefetch work and costs nothing when there is none.

**The guarantee, asserted in CI:** `test_query_counts_do_not_grow_with_the_number_of_quotations`
loads every list screen, inserts 250 more quotations, loads them again, and fails if any
screen issues even one extra query. Every screen is O(1) in row count.

### Indexes

Four on `Quotation` and one on `BillingScheduleEntry`, each chosen from the query log of a
real screen rather than sprinkled: `(stage, -last_activity_at)` for every board and list,
`(last_activity_at)` for stall detection, `(rep, -created_at)` for reports,
`(promised_delivery_date)` for slippage, `(status, due_date)` for the billing schedule.

### What is not done, honestly

* **Pagination.** Lists render every matching row. Correct to about a thousand; past that
  the cost is HTML size, not queries. `Paginator` is a small change and is listed in NEXT.
* **SQLite.** One writer at a time. Every query in this codebase is ORM-portable and the
  only raw SQL is a `sqlite_version()` call on the health page, so PostgreSQL is a settings
  change plus a data migration. ADR-002 chose SQLite so the demo has no service to install.
* **Caching.** Only the currency setting is cached, because it is read fifty times per page.
  Nothing else was cached, because nothing else measured slow enough to justify the
  invalidation bugs that come with it.

---

## 4. Real users

* **Governance is automatic.** The rep never clicks "request approval" — the score routes
  the deal. That is the difference between a policy and a form.
* **Refusals explain themselves.** A locked quotation says it is locked and disables its own
  controls; a rejected discount says why; a screen belonging to another role says which role
  and links somewhere useful. Silent refusal was a real bug here and was fixed as one.
* **Navigation never lies.** A role is shown exactly the links it can open — the sidebar and
  the server read the same `SCREEN_ROLES` table, and a test asserts they agree for every
  role and every screen.
* **The customer never sees an internal screen.** The portal is a separate app on a signed
  link with no login, and a test asserts it leaks no internal navigation.
* **Currency is configuration.** ₹ by default, with Indian digit grouping (₹12,34,567.89),
  read from one settings row rather than a hundred template literals.
* **Dates are the user's, not the server's.** They are computed in the configured timezone —
  which was a live bug: between 18:30 and midnight IST the application was a day behind.
