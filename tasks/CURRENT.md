# CURRENT TASK

**Status: NOT STARTED**

**Both demo flows now run end to end.** Every MUST-have screen exists.

Flow A: build a quotation, watch the ceiling check and margin update by HTMX swap, accept
an upsell suggestion, submit, route to Manager then Finance automatically, approve, split
4 + 2 across two warehouses at cost 6.80, invoice the one-time lines only, record a
payment, reach PAID.

Flow B: open the portal on a signed token, comment on a line, counter at 15 percent, watch
the quotation re-enter approval on its own with a Manager step and no Finance step, approve
internally, confirm in the portal.

Seven of the eight acceptance criteria are demonstrable today. **139 tests, all passing.**

---

## T-18 — Verification pass against the eight acceptance criteria

**This is the gate.** BACKLOG says P1 does not start until it passes, and any failure
becomes a task rather than a note.

AC-2, AC-3, AC-4, AC-5, AC-6, AC-7 and AC-8 have each been driven through the real views
and asserted. What remains is to run all eight in one sitting, by hand, against a freshly
seeded database, and record the result.

### The one that is not yet proven

**AC-1** — sign up or log in, then set up a discount tier, a warehouse and a subscription
plan, and confirm all three persist and are visible on reload. The rows exist and the
admin screens exist, but nobody has performed that criterion as written from a clean
database. Do it and record it.

Note the wording is *sign up* or log in. There is a login page but **no signup page** —
FR-01 asks for one. Decide whether to build it or to record its absence honestly; if it is
built, decide and write down whether self-signup may create a MANAGER or FINANCE account,
because an unauthenticated visitor granting themselves approval rights would make the whole
governance story hollow.

### Acceptance

- [ ] All eight criteria run by hand against a clean `migrate` + `seed_demo`, results recorded.
- [ ] Any failure becomes a numbered task, not a note.
- [ ] `docs/EVALUATOR_UPDATES.md` Round 4 written from the result.

### Then what

P1, in the order the backlog already sets: T-20 hybrid billing schedules (ADR-008 must be
closed first), T-21 deal health (ADR-007), T-22 pipeline Kanban, T-23 reporting. Then the
three PDF section 8 deliverables: the architecture diagram, the what-we-would-build-next
note, and the rehearsed recording.
