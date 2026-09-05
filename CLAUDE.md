# CLAUDE.md — DealFlow360

## Project identity

**DealFlow360** — an intelligent, self-governing sales operations platform.

A B2B sales platform that goes beyond quote-to-invoice: it enforces pricing discipline
through multi-tier discount governance and automated approval routing, reacts to live
inventory by splitting fulfilment across warehouses, keeps one-time and recurring
subscription lines reconciled on a single order, and gives customers a living, negotiable
quotation in their own portal instead of a static PDF.

**Hackathon context:** Odoo Hackathon 2026 final round, 24 hours (05 Sep 10:00 IST →
06 Sep 10:00 IST). Team 317, 4 members. Evaluator: Karan Israni (kais@odoo.com,
GitHub `kais-odoo` / `hackathon-odoo`). Deliverables due: video links 06 Sep 10:30,
presentation 13:00.

The problem statement PDF at `../Problem statements/DealFlow360.pdf` is the ultimate
source of truth for product requirements. `docs/SPEC.md` is its structured form.

## Source of truth — read these before working

- @docs/SPEC.md — structured product requirements (MUST / SHOULD / BONUS)
- @docs/ARCHITECTURE.md — stack, layers, module boundaries
- @docs/DATA_MODEL.md — entities, relationships, invariants
- @docs/DEMO.md — the 5-minute demo this project must survive
- @docs/DECISIONS.md — ADR log and open DECISION NEEDED items
- @tasks/BACKLOG.md — all tasks, P0/P1/P2
- @tasks/CURRENT.md — the single task to work on right now

If SPEC.md and the PDF disagree, the PDF wins — and fix SPEC.md in the same change.

## Development principles

- Inspect existing code before modifying it. Read the files a change touches, and trace
  the flow end to end, before editing.
- Do not invent APIs, models, routes, or files. If it is not in SPEC.md or DATA_MODEL.md,
  it does not exist yet.
- Prefer small, focused changes. One task from CURRENT.md at a time.
- No unrelated refactoring. Notice something ugly, note it in BACKLOG.md, move on.
- Keep business logic centralised in `core/services/` (see ARCHITECTURE.md). Views and
  templates call it; they do not reimplement it. Services take plain data and model
  instances and return results — no HTTP, no request objects.
- Do not hardcode core business rules. Discount ceilings, approval thresholds, warehouse
  shipping weights and subscription plans are configuration rows in the database, editable
  through the backend config screens. A number typed into a component is a bug.
- Preserve data consistency. Money, quantities and stock move inside one transaction or
  not at all. Every approval, rejection, edit and portal action writes an audit row.
- Use existing project conventions. Match the file layout, naming and patterns already in
  the repo rather than introducing a second style.
- Update tests when behaviour changes.
- Verify before marking a task complete. "It compiles" is not verification.

## Stack — settled, do not re-litigate

**Django 5 (Python 3.10) + SQLite** (`db.sqlite3`, local file). Django templates + HTMX,
Tailwind via CDN, `django.contrib.auth` with a custom `User` model carrying a `role` field.
Tests via `python manage.py test`. See ADR-001 and ADR-002.

Two rules that follow from it:

- **Django admin is the backend configuration area** (SPEC §4 A2–A7). Register the models;
  do not hand-write those CRUD screens. The rep workspace, approval screen, fulfilment
  screen and portal *are* hand-built.
- **SQLite has no decimal type.** Do money arithmetic in Python with `Decimal` inside
  `core/services/`. Never sum money through a `Sum()` aggregate — it can return a float and
  drift. This applies to line totals, order totals, margins and the risk score.

## Hackathon integrity

Core functionality must be **real application logic**, not mocked or hardcoded for the
demo. Specifically, per the problem statement and Odoo's stated must-haves:

- Approval routing, discount governance, warehouse splitting and billing proration are
  computed in application code from database state. They are not scripted for the demo.
- Data is real and dynamic. Static JSON is acceptable only as a seed source loaded into
  the database, never as a stand-in for a working query.
- The customer portal is a genuinely separate, access-restricted view — not an internal
  screen with a different label. This is called out explicitly in the PDF.
- If a feature is not finished, it is absent or clearly labelled incomplete. Never fake a
  result to make the walkthrough work.
- Git history must show commits from **all four members**. Odoo lists this as a must-have.

## Resolving open decisions — YOU are authorised to close these

`docs/DECISIONS.md` contains ADRs marked **Decision Needed**. These are places where the
problem statement genuinely does not specify an answer. They were left open deliberately so
they would be resolved consciously rather than by accident.

You may resolve them. When a task is blocked by one:

1. Read the ADR. It already lists the constraints any valid answer must satisfy.
2. Pick the simplest option that satisfies every stated constraint. Prefer a rule you can
   explain in one sentence to a judge over a clever one you cannot.
3. **Rewrite the ADR in place:** change Status to `Accepted`, add the Decision, the Reason,
   and the Consequences. Do not leave the old open questions dangling above it.
4. Where the ADR names worked examples from the PDF, write a unit test asserting each one
   **before** the implementation. Those tests are the specification.
5. Say in your response which ADR you closed and how, so a human can override it cheaply.

Do not silently invent an answer without recording it, and do not stall waiting for a human.
An explained, tested, written-down decision is what is wanted here.

If you hit an ambiguity that has **no** ADR yet, add one at the end of `docs/DECISIONS.md`
in the same format, resolve it the same way, and note it in your response.

## Working with subagents

Use subagents for work that is genuinely independent. Do not use them for anything that
touches migrations or shared models.

**Safe to parallelise**

- Reading and summarising the docs before a task, so the main thread stays focused.
- Building the pure logic in `core/services/` — `risk.py`, `fulfilment.py`, `pricing.py`,
  `billing.py` — once the models exist. These are plain Python with no shared files.
- Writing tests for a service that another agent is implementing.
- Template and CSS work on screens that do not overlap.
- A verification pass against the eight acceptance criteria in SPEC.md §9.

**Never parallelise**

- `makemigrations`. Two agents generating migrations for the same app produces a conflict
  that breaks `migrate` for the whole team. One migration wave at a time, always.
- Edits to `core/models/`. Serialise these through the main thread.
- `settings.py`, `config/urls.py`, `requirements.txt` — single-file bottlenecks.
- Anything on the same template file.

Rule of thumb: if two pieces of work would touch the same file, they are one task.

## Completion protocol

After finishing a task, in this order:

1. Run the relevant tests. Add one if the task introduced non-trivial logic.
2. Inspect the diff. Anything in it that the task did not require comes out.
3. Verify each acceptance criterion in `tasks/CURRENT.md` by actually exercising it.
4. Update `tasks/CURRENT.md` to the next task from BACKLOG.md.
5. Update `docs/DECISIONS.md` if an architectural decision was made or an open
   DECISION NEEDED was resolved.
6. Move the task into `tasks/DONE.md` only when it genuinely works end to end.
7. Report remaining risks — what is fragile, what is untested, what could break on stage.

Also update `docs/EVALUATOR_UPDATES.md` when a milestone lands. That file is read aloud
to the invigilator at each check-in round.
