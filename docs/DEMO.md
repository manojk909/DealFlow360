# DEMO — DealFlow360

PDF §8 requires: a five-minute live demo covering **at least two full flows end to end**,
from quotation to fulfilment or billing.

## 5-minute demo goal

By the end, judges should understand three things:

1. **The system governs itself.** The rep never clicks "request approval" — the blended
   risk score reads every line against its own category ceiling and routes the deal on its
   own. That is the product's whole thesis.
2. **It reacts to inventory reality.** Stock is not a number on a form; an order splits
   across warehouses because the stock genuinely isn't in one place.
3. **The customer is inside the deal, not emailing about it.** A separate, restricted
   portal where a counter-offer pushes the quote back into approval automatically.

Everything else — the dashboard, subscriptions, reporting — is supporting evidence.

## Demo scenario

Acme Corp, a **Gold** tier customer, is buying laptops plus a setup service. Gold allows
up to 15% overall, but Services are capped at 10% because their margins are thin. The rep
gets generous on the service line. The system notices.

This is the PDF's own worked example from §10, run live.

## Exact walkthrough

### Flow A — quotation to cash with discount governance (~2 min 30 s)

| # | Action | Expected system behaviour |
|---|---|---|
| A1 | Log in as **rep@dealflow.test** | Lands in the sales workspace. Quotation list shows Acme Corp (Draft) and Beta Industries (Pending Approval). |
| A2 | Open the Acme Corp draft | Quotation builder opens. Empty cart, margin indicator neutral. |
| A3 | Add **Laptop Pro 14** × 6, discount **12%** | Line total recalculates. Margin indicator green. No approval flag — Hardware ceiling is 15%, so 12% is inside it. |
| A4 | Add **Onsite Setup Service** × 1, discount **18%** | Line saves. The quotation now shows a risk flag: Services ceiling is 10%, so this line is **8 points over**. |
| A5 | Accept the top upsell suggestion (**Care Plan 2yr**) | Line is added, order total and **margin indicator update immediately** — this is AC-4, so pause on it. |
| A6 | Click **Submit for Approval** | Stage flips to Pending Approval **by itself**. Say out loud: *"the rep never requested approval — the blended score routed it."* This is AC-3. |
| A7 | Log in as **manager@dealflow.test**, open the approval screen | Blended risk score shown with the **per-line breakdown**: given / allowed / over-by for each line. The 8-point service line is visibly the cause. |
| A8 | Approve | Audit row written with user, timestamp, reason. Because the score is above the high threshold, a **Finance step appears**. |
| A9 | Log in as **finance@dealflow.test**, approve | Stage → Approved. Full audit trail visible. |
| A10 | Open Fulfilment | Suggested split appears: Laptop Pro 14 pulled **4 from Main Warehouse, 2 from East Depot** — because Main only has 4. Shipment count and cost shown. This is AC-5. |
| A11 | Accept Suggested Split → Confirm order | Stock reserved in both warehouses. Invoice generated for the one-time lines; the Care Plan appears on a **separate billing schedule**. This is AC-6. |
| A12 | Record payment against the invoice | Invoice status → Paid. This is AC-8. |

### Flow B — customer portal negotiation loop (~1 min 30 s)

Open this in a **second browser profile** so the two UIs are visibly different products.

| # | Action | Expected system behaviour |
|---|---|---|
| B1 | Open the portal link for the **Beta Industries** quotation | A different, restricted UI. Status: Sent. No internal nav, no other customers' quotations reachable. |
| B2 | Comment on a line: *"can you do better on the service?"* | Comment appears in the negotiation thread, attributed to the customer. |
| B3 | Enter a **counter-discount of 20%** and Submit Request | Status → Under Negotiation. |
| B4 | Switch back to the internal workspace | The quotation has **re-entered Pending Approval on its own** — the counter pushed the score past the threshold. This is AC-7 and the single best moment of the demo. |
| B5 | Manager approves | Stage → Approved. |
| B6 | Back in the portal, click **Confirm Quotation** | Status → Confirmed, order moves to fulfilment. |

### Close (~1 min)

Architecture diagram on screen. One sentence on the data model. Then the "what we'd build
next" note — the honest list of what is unbuilt, which reads as judgement rather than
omission.

## Critical demo flows

Ranked. If time runs short on stage, cut from the bottom.

1. **Automatic approval routing from the blended score** (A4→A6→A7). Without this there is
   no product.
2. **Portal counter-offer re-entering approval** (B3→B4). The clearest evidence the logic
   is real and not scripted.
3. **Warehouse split from live stock** (A10). Proves inventory awareness.
4. **Live margin update on upsell** (A5). Cheap, visual, instantly legible.
5. **Hybrid billing — one-time invoice plus recurring schedule** (A11).
6. Deal health dashboard. Nice, not load-bearing.
7. Reporting filters. Cut first.

## Demo seed data

Minimum set. Everything below must exist before the demo runs.

**Users** — `rep@dealflow.test` (REP), `manager@dealflow.test` (MANAGER),
`finance@dealflow.test` (FINANCE), `admin@dealflow.test` (ADMIN). One shared password.

**Tiers** — Bronze 5%, Silver 10%, Gold 15%.

**Categories** — Hardware, Services, Subscriptions.

**Category ceilings (Gold)** — Hardware 15%, Services 10%, Subscriptions 12%.
The Hardware-15 / Services-10 pair is what makes the PDF's worked example runnable.

**Approval chain rules** — thresholds per ADR-005, configured as rows so the demo can show
them on the config screen.

**Customers** — Acme Corp (Gold), Beta Industries (Silver), Cirrus Ltd (Bronze).

**Products** — at least 8, spread across all three categories, each with a `cost` so the
margin indicator has something to show. Must include: Laptop Pro 14 (Hardware), Onsite
Setup Service (Services), Care Plan 2yr (Subscriptions, monthly plan).

**Subscription plans** — one monthly plan, attached to Care Plan 2yr. Required by AC-1.

**Warehouses** — Main Warehouse (shipping weight 1.0), East Depot (1.4).

**Stock — the most important seed decision.** Main Warehouse holds **4** Laptop Pro 14;
East Depot holds **10**. The demo orders **6**. Single-warehouse fulfilment is therefore
impossible and the split logic is forced to run. Without this the split never triggers and
AC-5 cannot be demonstrated.

**Product pairs** — Laptop Pro 14 ↔ Care Plan 2yr with a high co-purchase count, so the
upsell panel's top suggestion is predictable on stage.

**Quotations** — Acme Corp in Draft (Flow A starts here), Beta Industries in Sent with a
live portal token (Flow B starts here), plus three more across Pending Approval, Approved
and Paid so the list and pipeline views are not empty. One quotation with
`last_activity_at` backdated so the deal health dashboard has a genuine stalled deal.

## Demo reset procedure

`python manage.py seed_demo` drops and reseeds to the exact state above. Idempotent —
running it twice gives the same result.

Nuclear option if the database gets into a bad state: delete `db.sqlite3`, then
`python manage.py migrate && python manage.py seed_demo`. Takes seconds, since SQLite is
just a file.

Rehearse this: **run the reset, then the full walkthrough, at least twice** before the
real thing. A reset that has never been tested is not a reset.

Have a second seeded user set (`rep2@`, etc.) as a fallback if a live account gets into a
bad state mid-demo.

## Failure / fallback plan

| If this breaks | Do this |
|---|---|
| Upsell panel | Skip A5. Mention it, move on. Flow A survives intact. |
| Warehouse split | Confirm the order anyway and go straight to billing. Say the split is built and show the config screen. |
| Subscription billing schedule | Show the one-time invoice only. Note hybrid billing as built-but-unshown. |
| Deal health dashboard | Cut entirely. It is not in the critical five. |
| Portal (Flow B) | This is the demo's best moment — do not cut it. If the portal UI fails, show the counter-offer re-entering approval from the internal side and the audit trail proving it happened. |
| Approval routing | Stop. Fix it. Nothing else is worth showing without it. |
| Whole app down | Fall back to the recorded video. **Record it at hour 20, not at 09:45.** |

Per CLAUDE.md's hackathon integrity rule: do not fake a result to make the walkthrough
work. A missing feature honestly named costs less than a fabricated one found out.
