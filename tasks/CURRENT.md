# CURRENT TASK

**Status: NONE IN PROGRESS.**

Everything in the P0 and P1 backlogs is shipped and green. **306 tests pass.** The three
ADRs that were blocking P1 — ADR-007 (deal health thresholds), ADR-008 (proration basis),
ADR-009 (tax / sales team / replenishment) — are closed and recorded in `docs/DECISIONS.md`.

## What remains

**T-35 — rehearse and record the five-minute demo.** The last required deliverable. Two
flows end to end, per `docs/DEMO.md`. Record it while things work, not at 09:45.

## Before the recording, in this order

1. `python manage.py migrate` — ADR-007/009 added `SalesSetting` plus three fields.
2. `python manage.py seed_demo` — the dataset grew: 10 users across two sales teams,
   8 customers, 18 products, 3 warehouses, ~25 quotations including the history that makes
   Deal Health show real alerts.
3. `python manage.py test` — expect 257 passing.
4. Walk the eight PDF §9 steps once by hand.

## Recently closed

| Task | What shipped |
|---|---|
| T-20 | Billing schedules, daily pro-rata proration, cancel with credit note (B7) |
| T-21 | Deal health: stalled, anomalies, slippage, all thresholds configured (B9) |
| T-22 | Pipeline Kanban split from the Quotations table (B1/B2) |
| T-23 | Reporting with the four PDF filters, CSV export, print-to-PDF (A7) |
| T-24 | Consolidate remaining backorder (B6) |
| T-25 | Product variant picker on the quotation line (A2) |
| T-29 | Nudge / escalate from a deal health alert |
| T-30 | Subscription cancel with credit note |
| T-31 | Replenishment as a reorder point per stock row (A4) |
| T-36 | Sidebar navigation, KPI tiles, light mode, and three bug fixes below |
| T-37 | Profile screen with four tabs, role-correct navigation, rebuilt pipeline board |

> **Re-seed before recording.** Clicking around the live app leaves real rows behind —
> Q-2026-0001 currently holds a monitor at 54%, which the anomaly detector correctly
> flags. `seed_demo` restores it to the empty draft `docs/DEMO.md` step A2 expects.

## The bugs found by clicking through the running app

1. **Sign-out was a GET.** Django 5's `LogoutView` refuses GET, so the control returned a
   405 page and left the session signed in — and the demo needs three role switches.
2. **Locked quotations were editable over HTTP.** The builder page hid the product picker
   past DRAFT, but the five HTMX mutation endpoints never checked the stage.
3. **Rejected input was silent.** HTMX discards the body of a non-2xx by default, so the
   view's error partial was rendered and thrown away.

4. **Role-correct navigation.** Approvals, Deal Health and Reports were offered to Reps
   and then refused; a Rep opening the approval screen for their own quote got a 403,
   despite "tracks approval status" being their job in PDF section 3.
5. **The light-mode toggle deleted its own icon**, and every gradient tile stayed dark
   because Tailwind writes `--tw-gradient-stops` as well as `--tw-gradient-from`.

Covered by `core/tests/test_stage_lock.py` and `core/tests/test_end_to_end_roles.py`.
