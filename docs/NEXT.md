# What we would build next

PDF §8 asks for a short note on what we would build with more time. This is that note, and
it is meant to be honest rather than flattering: everything below is either a limitation we
chose knowingly, a decision we deliberately did not make, or a feature we did not reach.

Nothing here is half-built and described as finished. Where something is unbuilt, the
application says so — the workspace greys out the tabs it has not implemented and names the
task, and the services that are blocked raise an error naming the decision that blocks them.

---

## 1. Weight the risk score by line value

**This is the first thing we would change, and it is the most likely question a judge will
ask.**

The blended risk score is the total number of discount percentage points given away above
ceiling. It ignores what a line is worth. A 20% discount on a €5 item scores exactly the
same as a 20% discount on a €5,000 item.

**Why it is that way.** The two worked examples in PDF §10 are stated purely in percentage
points — no quantities, no prices, nothing to weight by. A value-weighted score cannot
reproduce them: the eight-point Setup Service line, the very line the PDF chose to complain
about, would be diluted to almost nothing sitting beside six laptops, and would stop
flagging. We treated the PDF's examples as the specification and made the arithmetic follow
them. That reading is written down in ADR-005, along with the value-weighted alternative and
why it was rejected — it was a decision, not an oversight.

**What we would build.** Keep the per-line breakdown exactly as it is, because it is what
makes the score explainable, and add a second, value-weighted figure beside it — points over
ceiling weighted by each line's share of order value. Route on whichever is higher. That
catches both failure modes: the rep who gives away a lot on one small line, and the rep who
gives away a little on the biggest line in the order. It is roughly a day's work, most of it
in deciding how the approval screen shows two numbers without confusing anyone.

---

## 2. Close the three decisions we deliberately left open

Three ADRs are still marked *Decision Needed*. Each is a place where the problem statement
genuinely does not specify an answer, and each blocks only lower-priority work. We would
rather show you three open decisions with their constraints written out than three invented
numbers presented as facts.

**ADR-007 — deal health thresholds.** A stalled deal is one inactive for "a configured
number of days", with no default given. A discount anomaly is one "well above a rep's
historical average", with "well above" unquantified and the averaging window unstated.
Delivery promise slippage is listed with no promise date defined anywhere in the data model.
`health.py` is written as a contract; `stalled_deals` could ship as soon as a window is
agreed, and `discount_anomalies` and `delivery_slippage` currently raise an error naming
this ADR so nobody implements a threshold nobody chose. **Next:** pick a stall window, define
the anomaly as a number of standard deviations above the rep's trailing-quarter mean, and add
a promise-date field — then build the dashboard.

**ADR-008 — subscription proration basis.** Mid-cycle changes must be prorated, but whether
that is daily pro-rata, whole-period, or something else is not stated, and neither is how a
cancellation refund is computed. `SubscriptionPlan.proration_method` literally holds the
value `UNDECIDED`, and `prorate_quantity_change` raises an error naming the ADR. **Next:**
choose daily pro-rata (the least surprising to a customer), write it on the plan row so it
stays configuration, then build the billing schedule and the subscription screen — see item 3.

**ADR-009 — tax, sales teams, replenishment rules.** Three fields the PDF names without
defining. Tax is a product field with no tax rules, so we store `tax_pct` and it participates
in no total and no margin — stated on the model rather than left to be discovered. "Sales
Team" appears as a reporting filter with no team entity described anywhere. Replenishment
rules are named for warehouses with no statement of what one does. **Next:** tax as an
order-level exclusive line so totals stay tax-exclusive and margin is unaffected; a Team
model with rep membership; and replenishment as a reorder point that raises a flag rather
than acting on its own.

---

## 3. Recurring billing schedules (T-20)

The one genuinely half-present feature, and we would rather name it than let you find it.

Hybrid billing **works** in the sense the acceptance test asks for: a single order can carry
one-time and recurring lines, the invoice bills the one-time lines only, and the recurring
value is correctly kept off it and shown separately on the screen. On the demo order that is
€7,740.60 invoiced and €456.00 held back.

What does not exist is the schedule those recurring lines bill *on*. `BillingScheduleEntry`
is in the schema, and `build_billing_schedule` and `upcoming_schedule` are written contracts
that raise `NotImplementedError`. So we can show you that the separation is real; we cannot
show you twelve months of upcoming charges. **Next:** generate the schedule at confirmation
from the plan interval, render it on the order screen, and add mid-cycle proration once
ADR-008 is closed.

---

## 4. The rest of the P1 backlog, in the order we would take it

- **Deal health dashboard (T-21).** Blocked on ADR-007. Stalled-deal detection alone could
  ship today; the anomaly and slippage panels cannot, honestly.
- **Pipeline Kanban (T-22).** The quotation list already groups into stage columns, so this
  is drag-to-move plus a stage transition guard — small, and mostly about not letting a drag
  bypass governance.
- **Reporting with filters (T-23).** Period, rep, approval status, product. Straightforward
  once ADR-009 settles whether "Sales Team" is an entity.
- **Consolidate remaining backorder (T-24).** The prompt when stock arrives for a
  backordered line. `consolidate_backorder` is a contract that reuses the existing split
  rule rather than inventing a second one.
- **Product variants on a quotation line (T-25).** The model and admin exist and the pricing
  service already handles a variant surcharge; what is missing is the picker.

---

## 5. Things we would do differently, not just next

**A global warehouse split.** Ours solves each line independently, so across a multi-line
order it can suggest more shipments than necessary — two lines each picking a different
cheapest warehouse where one warehouse could have covered both. ADR-006 documents this and
the fulfilment screen says it on the page. A global optimiser is a genuinely different piece
of work and was out of scope for 24 hours.

**A configuration row for the upsell margin threshold.** ADR-011: no entity holds it, because
the PDF introduces it only inside the Optional A6 screen. It is a named constant with an
explicit override parameter, documented as a placeholder rather than pretended to be
configuration. Everything else that governs behaviour — ceilings, approval bands, shipping
weights, subscription plans — is a database row, and we would want this to join them.

**Email.** ADR-004 declined it: the portal link is copied from the internal screen and no
mail is sent. That is right for a demo, where SMTP is a live dependency that can only fail,
and wrong for a real deployment.

**Password reset and email verification.** Neither exists. Neither is required by any
acceptance criterion, and both need the mail infrastructure above.

---

## What we are confident about

The parts the problem statement said it was actually testing are real and tested. Approval
routing, discount governance, the warehouse split and the invoice-versus-schedule separation
are computed in application code from database state, not scripted for the demo. There are
**170 tests**, and all **eight acceptance criteria** were verified in one continuous pass
against a database rebuilt from nothing, driving the real views over HTTP — the observed
result for each is recorded in `docs/ACCEPTANCE.md`.

The two worked examples from PDF §10 were written as unit tests **before** the formula was
chosen, and neither expectation has been edited since.
