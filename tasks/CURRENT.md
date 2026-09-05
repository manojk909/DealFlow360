# CURRENT TASK

**Status: NOT STARTED**

T-00 and T-01 are done — see `tasks/DONE.md`. The app runs, `AUTH_USER_MODEL` is set to
`core.User` and was set before the first migration, and the four ADRs that blocked P0 are
closed. **No P0 task is blocked by an open decision.**

---

## T-02 — Schema and migrations for the P0 entities

### Objective

Turn DATA_MODEL.md's MUST entities into tables, in **one migration wave**, so all four
tracks can start building against a real schema.

### Context

T-01 shipped exactly one model — the custom `User` in `core/models/parties.py`. Everything
else in DATA_MODEL.md is still just a document.

**The coordination rule that matters more than the code.** One person runs
`makemigrations` for this wave. Two developers generating migrations for `core` in parallel
produces a conflict that breaks `migrate` for everybody, and at hour 20 that is an hour
nobody has. Announce the schema to the team **before** pushing it.

**Decisions already made that this task must honour:**

- **ADR-010** fixes the `Quotation.stage` enum: `DRAFT · PENDING_APPROVAL · REJECTED ·
  APPROVED · SENT · UNDER_NEGOTIATION · CONFIRMED · FULFILLED · INVOICED · PAID`. `SENT` is
  a real stage reachable **only** from `APPROVED`. There is no second portal-status field —
  portal status is a display mapping over `stage`.
- **ADR-005** fixes `ApprovalChainRule` as `score_min` / `score_max` / `requires_manager` /
  `requires_finance`, with the bands as data.
- **ADR-004** means `Quotation.portal_token` holds a signed `TimestampSigner` value and
  there is no customer user table.
- **The A5 split** (DECISIONS.md, second-pass consistency check) makes `SubscriptionPlan`
  a **P0 entity** — AC-1 requires a subscription plan to be created and to persist.
  `BillingScheduleEntry` stays out of P0 and arrives with T-20.

### Scope

User (exists), CustomerTier, Customer, Category, Product, PriceListEntry,
CategoryDiscountCeiling, ApprovalChainRule, Quotation, QuotationLine, ApprovalStep,
AuditLog, Warehouse, Stock, FulfilmentAllocation, Invoice, Payment, PortalMessage,
**SubscriptionPlan**.

Models are split by domain across `core/models/` — `catalogue.py`, `parties.py`,
`sales.py`, `inventory.py`, `billing.py` — per ARCHITECTURE.md, to keep four developers off
each other's diffs. Re-export everything from `core/models/__init__.py`.

Money fields are `DecimalField`. No `FloatField` anywhere near a price, a percentage or a
margin (ADR-002).

### Acceptance criteria

- [ ] Migration applies cleanly to an empty database (`rm db.sqlite3 && python manage.py migrate`).
- [ ] Unique constraint on `Stock (product, warehouse)` enforced at database level, not
      just in a form.
- [ ] DATA_MODEL.md invariant 8 (`qty_reserved <= qty_on_hand`) expressed as a
      `CheckConstraint`.
- [ ] DATA_MODEL.md invariant 11 (Σ payments ≤ invoice amount) expressed where SQLite
      allows; where it cannot be a constraint, it is enforced in the service and that is
      stated in a comment rather than assumed.
- [ ] DATA_MODEL.md invariant 9 (`RECURRING` line has a plan, `ONE_TIME` does not)
      expressed as a `CheckConstraint`.
- [ ] `Quotation.stage` uses exactly ADR-010's enum, as `TextChoices`.
- [ ] Every model is importable from `core.models` and `python manage.py check` is clean.
- [ ] `python manage.py test` still passes (the two ADR-005 spec tests still skip).
- [ ] Schema announced to the team before the migration is pushed.

### Out of scope

Admin registration (T-05, T-06, T-07), the seed script (T-03), and every service module.
Do not write `core/services/risk.py` here — T-09 owns it, and `core/tests/test_risk.py` is
already waiting for it.

### Verification plan

1. `rm db.sqlite3 && python manage.py migrate` from clean — no warnings, no interactive prompts.
2. In `manage.py shell`, create one row of each entity and read it back.
3. Deliberately violate each constraint above and confirm the database refuses it.
4. `python manage.py test` — green, with the two risk tests still skipping.

### Then what

T-03 (seed script) immediately after, and it is the highest-leverage task in the build:
every other track needs data. The seeded stock — **Main Warehouse 4, East Depot 10, demo
order of 6** — is what makes the warehouse split actually trigger on stage, and without it
AC-5 cannot be demonstrated at all.
