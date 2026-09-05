# ACCEPTANCE — the eight criteria from SPEC.md §9

**T-18, the gate.** BACKLOG says P1 does not start until this passes and any failure
becomes a task rather than a footnote.

Run: `python manage.py shell -c "exec(open('scripts/ac_gate.py').read())"` against a
database rebuilt with `migrate` + `seed_demo`. The script drives the **real views** over
HTTP; no service is called directly except to read a value back for an assertion.

---

## Result — 06 Sep 2026 (re-run after the P1 wave)

Fresh database (`db.sqlite3` deleted, `migrate`, `seed_demo`), one continuous pass.
Re-run after subscriptions, deal health, reporting, assets and the new screens landed,
to confirm none of it regressed the eight criteria.

| # | Criterion | Verdict | Checks |
|---|---|---|---|
| AC-1 | Sign up / log in, set up a tier, a warehouse and a plan | **PASS** | 9/9 |
| AC-2 | Add a line discounted beyond what is allowed | **PASS** | 3/3 |
| AC-3 | Confirm; it asks for approval automatically | **PASS** | 4/4 |
| AC-4 | Accept an upsell; total and margin update right away | **PASS** | 6/6 |
| AC-5 | Approved, then fulfilment splits across warehouses | **PASS** | 8/8 |
| AC-6 | One-time and recurring billed separately | **PASS** | 3/3 |
| AC-7 | Customer requests a bigger discount in the portal | **PASS** | 8/8 |
| AC-8 | Record a payment; invoice status updates | **PASS** | 4/4 |

**45 checks, all passing.**

One assertion in the gate had to be corrected, and it is worth recording why. AC-5 failed
on the first re-run because the seed had gained a **third warehouse** — North Hub, weight
1.75, holding 3 Laptop Pro 14. The split itself was still correct (4 from Main, 2 from
East, exactly as before, because North Hub is the dearest and never gets picked), but the
gate compared the whole reservation dictionary and now saw an extra key sitting at zero.
The claim being tested is *pulled from the correct warehouses*, so it now compares the
non-zero reservations and additionally asserts the dearest warehouse reserved nothing —
a stronger check than the one it replaced. **The product was right and the test was
stale**, which is the only reason this counts as a corrected assertion rather than a bug.

---

## What was actually observed

**AC-1.** Signup at `/signup/` returned 302 and created `gate.rep@dealflow.test` with role
`REP` — not an approver, per ADR-012. An admin then created a **Platinum** tier (18%), a
**North Hub** warehouse (weight 1.20) and a **Gate Monthly** subscription plan through the
admin forms. All three were still present when their changelists were re-fetched in fresh
requests, which is the "visible on reload" half of the criterion.

**AC-2.** Laptop Pro 14 × 6 at 12% rendered `OK` — inside the 15% Hardware ceiling for a
Gold customer. Onsite Setup Service at 18% **saved** with `discount_pct = 18.00` and the
same response rendered `OVER +8 pt`, so the overage is recognised as it is typed, not at
submit.

**AC-3.** One POST to submit. Stage moved to `PENDING_APPROVAL` with **no manual request**,
`risk_score` snapshotted at `8.00`, and the system generated `MANAGER` then `FINANCE`
itself. A rep POSTing directly at the approval endpoint got **403**.

**AC-4.** Care Plan 2yr was the top suggestion. Accepting it returned a partial with no
`<html>` — no page reload — and the order total moved **7740.60 → 8196.60** with the new
margin figure present in that same response.

**AC-5.** Manager approved; the quotation correctly stayed `PENDING_APPROVAL` while Finance
was outstanding. After Finance approved it reached `APPROVED`. The fulfilment screen showed
both warehouses, an estimated cost of **6.80**, and named the non-warehoused service line as
*skipped, not backordered*. Accepting the split reserved **4 at Main Warehouse and 2 at East
Depot** and moved the order to `FULFILLED`.

**AC-6.** Invoice raised at **7740.60** — the one-time lines only — with **456.00** of
recurring value excluded and shown separately on the screen.

**AC-8.** An overpayment was refused and wrote **no** Payment row. Half payment derived
`PARTIAL`; the remainder derived `PAID` and the order reached `PAID`. Status was never
assigned, only derived.

**AC-7.** The portal opened on its signed token with no internal navigation reachable; a
tampered token returned **403**. A line comment and a 15% counter replaced the service
line's discount (from 8%), re-scored to **5.00**, and the quotation went back to
`PENDING_APPROVAL` **on its own** with a fresh `MANAGER` step and no Finance step. After the
manager approved, the customer confirmed and it reached `CONFIRMED`.

---

## Caveats worth stating

- The pass is **automated**, driving the views over HTTP. It is stronger than clicking
  through once because it asserts values rather than impressions, but it does not prove the
  screens *look* right. That is what the demo rehearsal (T-35) is for.
- AC-6 proves one-time and recurring are billed through **separate artefacts**, which is
  what invariant 10 and the criterion require. It does not show a populated billing
  schedule — `build_billing_schedule` is T-20 and is still a stub. The recurring value is
  correctly kept off the invoice; the schedule it goes to is now built (T-20, B7).
- AC-1 was satisfied through Django admin, which **is** the backend configuration area by
  ADR-001. That is the design, not a shortcut, but it is worth saying out loud.
