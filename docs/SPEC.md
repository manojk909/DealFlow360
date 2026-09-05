# SPEC — DealFlow360

Structured form of `../Problem statements/DealFlow360.pdf`. The PDF is the source of truth;
this file restates it so requirements can become tasks. Anything the PDF does not state is
marked **DECISION NEEDED** rather than filled in.

---

## 1. Problem statement

Simple sales tools handle create-quote → confirm-order → invoice well. Real B2B sales teams
operate in messier conditions: multi-level discount approvals, partial stock spread across
warehouses, bundled subscriptions mixed with one-time hardware, customers who want to
negotiate inside a portal rather than over email, and managers who only discover a deal is
stuck after it has already lost momentum.

## 2. Main goal

Build a complete sales flow including backend configuration and a frontend
quotation-to-cash experience — a self-governing deal engine that enforces pricing
discipline, reacts to inventory reality in real time, keeps subscriptions and one-time
sales reconciled on a single order, and gives reps and customers a living, negotiable
document instead of a static PDF.

## 3. Target users / roles

| Role | Responsibilities (from PDF §3) |
|---|---|
| **Sales Rep** | Builds quotations, applies discounts, adds upsell items. Tracks approval status and fulfilment progress. Responds to customer negotiation requests. |
| **Sales Manager / Approver** | Reviews and approves or rejects quotations exceeding discount thresholds. Configures discount tiers and approval chains. Monitors deal health dashboard. |
| **Finance / Operations** | Handles second-level approvals for high-risk discounts. Manages warehouse fulfilment splits and backorder decisions. Reconciles recurring billing and credit notes. |
| **Customer (Portal User)** | Views quotation online. Requests changes, asks line-level questions, counters a discount. Confirms final terms with one click. |
| **Admin** | Manages backend setup: products, price lists, discount tiers, warehouses, subscription plans. Views platform-wide analytics and reporting. |

## 4. Core modules / features

### A) Sales Backend — configuration area

| ID | Feature | Priority |
|---|---|---|
| A1 | **Authentication.** Internal users sign up / log in with standard credentials. Customers access quotations via portal login (magic link, or email + password). After login internal users reach backend config and a sales workspace. | MUST |
| A2 | **Product & price list management.** General info: name, category, price, unit, tax, description. Variants: attribute (e.g. Size, Pack), values, extra prices. Price lists: customer-tier-based pricing, currency-specific rules. | MUST (variants: SHOULD) |
| A3 | **Discount tier & approval chain setup.** Discount ceilings per customer tier (e.g. Bronze ≤5%, Silver ≤10%, Gold ≤15%). Category-specific ceilings. Approval chain config: which discount range needs Sales Manager only, which needs Sales Manager then Finance. | MUST |
| A4 | **Warehouse & fulfilment setup.** Create/manage warehouses (e.g. "Main Warehouse", "East Depot"). Stock levels and replenishment rules per warehouse. Shipping cost weighting used by auto-split logic to minimise shipments. | MUST (replenishment rules: SHOULD) |
| A5 | **Subscription / recurring plan setup.** Recurring plans (monthly, quarterly, yearly) attachable to products or services. Proration rules for mid-cycle quantity or plan changes. Cancellation and partial refund rules. | **Split.** Plan setup — the `SubscriptionPlan` entity and its admin CRUD — is **MUST**, because AC-1 requires a subscription plan to be created and to persist. Recurring billing behaviour — schedules, proration, cancellation refunds — remains **SHOULD**. |
| A6 | **Upsell / cross-sell rule setup.** *(PDF marks this section Optional.)* Product pairings from historical co-purchase data. Promoted-product flag ranks suggestions higher. Minimum margin thresholds so only healthy-margin suggestions surface. | BONUS |
| A7 | **Reporting & dashboard configuration.** Dashboard plus reporting menu for sales performance. Export to PDF / XLS. Filters: Period, Sales Team / Rep, Approval Status, Product / Category. | SHOULD (export: BONUS) |

### B) Sales Frontend — rep workspace

| ID | Feature | Priority |
|---|---|---|
| B1 | **Sales workspace top menu.** Nav: Quotations (list of active and draft), Pipeline (Kanban deal view). Actions: Reload Data (refresh pricing, stock, approval data), Go to Back-end, Close Workspace. | MUST (Pipeline Kanban: SHOULD) |
| B2 | **Quotation list / pipeline view.** Quotations as selectable cards showing customer, amount, stage. Example entries: "Acme Corp, Draft", "Beta Industries, Pending Approval". Selecting opens the Quotation Builder. | MUST |
| B3 | **Quotation builder.** Pick products across categories (Hardware, Services, Subscriptions). Adjust quantities (+/−). Apply line-level or order-level discounts. Order lines with price totals and a **live margin indicator**. Confirm → approval, or straight to fulfilment if no approval required. | MUST |
| B4 | **Discount approval screen.** Blended risk score for the quotation. Approval steps list: Sales Manager, and Finance only when required. Each reviewer can Approve / Reject / Return for revision. Confirmation screen with full audit trail entry. | MUST |
| B5 | **Upsell & cross-sell panel.** Shown alongside the cart while building. Ranked suggestions from co-purchase history and active promotions. Displays suggested product, margin delta if added, promotion tag. Buttons: Add to Quote, Dismiss. Margin indicator updates immediately after adding. | SHOULD |
| B6 | **Fulfilment & warehouse split screen.** Recommended split based on live stock. Displays warehouse name, quantity fulfilled from it, estimated shipment count and cost. Buttons: Accept Suggested Split, Manual Override. If stock arrives mid-fulfilment, a "Consolidate Remaining Backorder" prompt appears automatically. | MUST (consolidate prompt: SHOULD) |
| B7 | **Subscription & billing screen.** One-time lines and recurring lines shown separately within the same order. Upcoming billing schedule for recurring lines. Mid-cycle proration when quantity changes. Cancel / modify subscription controls, with automatic partial refund or credit note trigger when applicable. | SHOULD |
| B8 | **Customer portal negotiation screen.** Customer-facing, **separate from the internal workspace**. Shows quotation details and status (Sent, Under Negotiation, Confirmed). Line-level comment and change-request tool. Counter-discount proposal field. Buttons: Submit Request, Confirm Quotation. After confirmation: if final terms exceed approval thresholds the quotation automatically re-enters the approval flow (B4); otherwise the order moves directly to fulfilment. | MUST |
| B9 | **Deal health & anomaly dashboard.** Stalled deals (inactive more than a configured number of days). Discount anomaly alerts (a discount well above a rep's historical average). Delivery promise slippage indicators. Clicking an alert opens the related quotation. An automated nudge or escalation action can be triggered from an alert. | SHOULD (nudge/escalation: BONUS) |

## 5. End-to-end workflow (PDF §5)

1. Sales rep signs up (first time) or logs in.
2. Admin configures the backend: products, price lists, discount tiers, approval chains, warehouses, subscription plans.
3. Rep opens the workspace and creates a new quotation for a customer.
4. Rep adds products, applies discounts, reviews upsell suggestions in the panel.
5. If the discount or blended risk score exceeds a threshold, the quotation is **automatically** routed for approval (Sales Manager, then Finance if required).
6. Once approved — or immediately if no approval was needed — the system suggests a warehouse fulfilment split.
7. Order may include recurring subscription lines, which generate a billing schedule alongside any one-time invoice.
8. Customer receives the quotation link and negotiates through the portal.
9. If terms change beyond thresholds during negotiation, the quote re-enters the approval flow automatically.
10. Once confirmed, the order proceeds to fulfilment and billing.
11. Manager reviews the Deal Health dashboard throughout the cycle.
12. Reports are reviewed using filters (Period / Sales Team / Approval Status / Product).

## 6. Business rules

### BR-1 — Blended discount risk score (PDF §10)
The score decides whether a quotation needs manager approval, and whether it also needs
finance approval. Every line is checked against **its own** category ceiling, not one
overall order limit.

- **Worked example from the PDF:** a Gold customer is allowed up to 15%. Hardware allows
  15%, Services allow 10%. A Laptop (Hardware) at 12% is fine. A Setup Service at 18%
  against a 10% ceiling is 8 points over its limit. The whole quotation is flagged for
  approval because of that one line, even though 15% "sounds fine on paper" for a Gold
  customer.
- **Why blended:** sometimes no single line is badly over, but many are each a little
  over — one 2 points over, another 3, another 2. None looks alarming alone, but across
  the order the rep has quietly given away a lot of margin. The blended score looks at the
  total pattern across the order, not just the single worst line, so small violations
  spread across many lines cannot slip through unnoticed.
- **Purpose:** it decides who reviews the deal, so managers are not stuck reviewing every
  quotation by hand; and it stops a rep keeping every line technically within limits while
  discounting the order more than the company intends overall.

**The formula (ADR-005, Accepted).** The blended risk score is **the total number of
discount percentage points given away above ceiling across the whole quotation, where every
line is measured against the stricter of its customer tier's ceiling and its category's.**

For each line:

- `given = 100 × (1 − (1 − line_discount_pct/100) × (1 − order_discount_pct/100))` — an
  order-level discount is a real discount on every line, so it is scored as one.
- `allowed = min(tier.max_discount_pct, categoryCeiling.max_discount_pct)`.
- `over_by = max(0, given − allowed)`. A line inside its ceiling contributes nothing.

Then `risk_score = Σ over_by`, as `Decimal` quantised to `0.01`, and the quotation is
**flagged for approval whenever `risk_score > 0`**. The service returns the score together
with a per-line given / allowed / over-by breakdown, because the approval screen (FR-14)
cannot explain the number without it.

Both PDF §10 examples are reproduced, and are asserted by `core/tests/test_risk.py`, which
was written before the implementation and is the specification for it: the single
8-points-over Services line scores 8.00 and flags the quotation; three lines at 2, 3 and 2
points over score 7.00 and flag it too.

**Routing thresholds are configuration, not code** (FR-07). They live in
`ApprovalChainRule` rows: `0.00–0.00` → no approval; `0.01–7.99` → Sales Manager only;
`8.00` and above → Sales Manager then Finance. Ranges are inclusive and must tile the whole
space; a score matching no rule is a configuration error and fails loudly rather than
silently skipping governance.

### BR-2 — Approval routing
- When a quote mixes categories with different ceilings, the system computes a blended
  risk score and routes to **the highest required level**.
- Routing is automatic. The rep does not manually request approval.
- Approval chain configuration (which discount range needs Manager only vs Manager then
  Finance) lives in the backend config (A3), not in code.

### BR-3 — Audit trail
All approvals, rejections and edits must be logged with **user, timestamp, and reason**.

### BR-4 — Warehouse split
- Split is computed from **live stock**.
- Shipping cost weighting per warehouse is used to **minimise the number of shipments**.
- The user may accept the suggestion or manually override it.
- If stock arrives mid-fulfilment, a "Consolidate Remaining Backorder" prompt appears
  automatically.
- **The split rule (ADR-006, Accepted) — a documented greedy heuristic, described as one.**
  **Fill each line from the cheapest warehouse first and spill into the next cheapest,
  except that if the cheapest warehouse can cover the whole line by itself it ships alone;
  whatever is left over becomes a backorder.** Warehouses are ranked by ascending
  `shipping_cost_weight`, tie-broken by descending available quantity
  (`qty_on_hand − qty_reserved`) then by warehouse id, so the suggestion is deterministic.
  Shipment count is the number of distinct warehouses in the non-backorder allocations, and
  estimated cost is `Σ (allocated qty × shipping_cost_weight)`.
  With the seeded demo stock — 6 × Laptop Pro 14, Main Warehouse 4 at weight 1.0, East Depot
  10 at weight 1.4 — this splits **4 + 2** at a cost of 6.80. One shipment of 6 from East
  Depot alone would cost 8.40, so "minimise the number of shipments" is read as *weighted by
  shipping cost*, which is what PDF A4's same sentence also says. See ADR-006 for the
  trade-off in full.

### BR-5 — Hybrid billing
- A single order can mix one-time products and recurring subscription lines.
- Both must be billed **correctly and separately**, with correct proration and billing
  schedules.
- Mid-cycle quantity or plan changes are prorated per the configured proration rules.
- Cancellation triggers an automatic partial refund or credit note when applicable.

### BR-6 — Portal renegotiation loop
After a customer confirms in the portal: if final terms exceed approval thresholds, the
quotation **automatically re-enters the approval flow (B4)**. Otherwise the order moves
directly to fulfilment.

### BR-7 — Upsell suggestions
Ranked by co-purchase history and active promotions. Only suggestions above the configured
minimum margin threshold surface. Adding one updates the margin indicator immediately.

### BR-8 — Deal health
- Stalled = quotation inactive for more than a **configured** number of days.
- Discount anomaly = a discount well above a rep's **historical average**.
- **DECISION NEEDED — anomaly threshold definition.** "Well above" is not quantified in
  the PDF. See ADR-007.

## 7. Functional requirements

Each of these is directly implementable and testable. IDs map to backlog tasks.

**MUST HAVE**

- FR-01 Internal user signup and login with role assignment (Rep, Manager, Finance, Admin).
- FR-02 Customer portal access to a specific quotation, restricted so a customer sees only their own quotation.
- FR-03 CRUD for products with name, category, price, unit, tax, description.
- FR-04 CRUD for price lists with customer-tier-based pricing.
- FR-05 CRUD for discount tiers with per-tier ceilings.
- FR-06 CRUD for category-specific discount ceilings.
- FR-07 CRUD for approval chain configuration (discount range → required approver levels).
- FR-08 CRUD for warehouses with per-warehouse stock levels and shipping cost weighting.
- FR-09 Quotation list showing customer, amount, stage.
- FR-10 Quotation builder: add/remove products, adjust quantity, apply line-level discount, apply order-level discount.
- FR-11 Live margin indicator recalculating on every quotation change.
- FR-12 Blended risk score computed on quotation submit.
- FR-13 Automatic approval routing to the required approver level(s) based on that score.
- FR-14 Approval screen showing the blended score and the per-line breakdown that produced it.
- FR-15 Approve / Reject / Return-for-revision actions per approval step.
- FR-16 Audit log entry for every approval action with user, timestamp, reason.
- FR-17 Warehouse split suggestion from live stock, showing warehouse, qty, shipment count, cost.
- FR-18 Accept suggested split, or manual override.
- FR-19 Backorder row when stock is insufficient.
- FR-20 Order confirmation → invoice generation → payment recording → invoice status update.
- FR-21 Customer portal: view quotation with current status (Sent / Under Negotiation / Confirmed).
- FR-22 Customer portal: line-level comment / change request.
- FR-23 Customer portal: counter-discount proposal; on submit, re-scoring and automatic re-entry into approval when thresholds are exceeded.
- FR-24 Customer portal: Confirm Quotation.
- FR-25 Seed data sufficient to demonstrate every MUST flow.
- FR-29 Subscription plan configuration: CRUD for plans with a name and an interval
  (monthly / quarterly / yearly), attachable to a product. **Promoted from SHOULD to
  MUST** because AC-1 requires a subscription plan to be set up and to persist. Only the
  plan record and its admin screen are MUST; the proration and cancellation *rules* the
  plan carries are exercised by FR-31 and FR-32, which stay SHOULD/BONUS.

**SHOULD HAVE**

- FR-26 Product variants with attributes, values and extra prices.
- FR-27 Kanban pipeline view of quotations by stage.
- FR-28 Upsell / cross-sell panel with ranked suggestions, margin delta, promotion tag, Add / Dismiss.
- FR-30 Order screen separating one-time and recurring lines, with upcoming billing schedule.
- FR-31 Mid-cycle proration on quantity change.
- FR-32 Subscription cancel / modify with partial refund or credit note trigger.
- FR-33 Deal health dashboard: stalled deals, discount anomalies, delivery slippage, click-through to quotation.
- FR-34 Reporting with Period / Rep / Approval Status / Product filters.
- FR-35 "Consolidate Remaining Backorder" prompt when stock arrives mid-fulfilment.
- FR-36 Replenishment rules per warehouse.

**BONUS**

- FR-37 Upsell rule configuration screen (PDF marks A6 Optional).
- FR-38 Report export to PDF / XLS.
- FR-39 Automated nudge / escalation action from a deal health alert.
- FR-40 Multi-currency or multi-company support (PDF §7: "a bonus, not a requirement").

## 8. Important constraints (PDF §7 Technical Guidelines + Odoo event page)

From the problem statement:

- Any tech stack — any backend language, any frontend framework, any relational or document database.
- Core business rules (approval routing, discount governance, warehouse splitting, billing proration) **must be implemented in application logic, not hardcoded or faked for the demo**.
- The customer-facing negotiation screen **must be a real, separate, restricted view**, not another internal screen with a different label.
- Multi-currency / multi-company is a bonus, not a requirement.

From the Odoo event page — **must have**:

- Use real-time or dynamic data sources; avoid static JSON except for initial prototyping.
- Responsive and clean UI with a consistent colour scheme and layout.
- Validate user input robustly.
- Intuitive navigation with proper menu placement and spacing.
- Use version control properly — **one member managing the repo is not enough**.

From the Odoo event page — **nice to have**:

- Ability to design backend APIs, model data, set up a local database.
- Understand any AI-generated code before using it.
- Plan for offline / local operation; do not depend entirely on internet connectivity.
- Use trendy technologies only where they add real value.

## 9. Acceptance criteria

The PDF's §9 "Quick Test Flow (Login to Payment)" is the definitive acceptance test. Each
step must produce a visible, correct result before the next.

| # | Step | Pass condition |
|---|---|---|
| AC-1 | Sign up or log in, set up basic backend data: a discount tier, a warehouse, a subscription plan | All three persist and are visible on reload |
| AC-2 | Create a quotation, add a product line with a discount higher than normally allowed | Line saves; system recognises the overage |
| AC-3 | Confirm the quotation | It **automatically** asks for manager approval, without the rep manually requesting it |
| AC-4 | While building, accept one upsell suggestion | Order total and margin update **right away** |
| AC-5 | Get the quotation approved, then check fulfilment | Stock pulled from the correct warehouse, splitting across two warehouses if needed |
| AC-6 | Order containing a one-time product and a recurring subscription | Both billed correctly and separately |
| AC-7 | Open the customer portal view, request a bigger discount as the customer | Quote goes back for approval **automatically** |
| AC-8 | Confirm the order, record a payment | Invoice status updates correctly |

The PDF: "If all eight steps work smoothly and each result matches what is expected, the
core flow is solid."

## 10. Required hackathon deliverables (PDF §8)

- A working application (backend plus frontend) with **sample seed data**.
- A **five-minute live demo** covering at least **two full flows end to end**, from quotation to fulfilment or billing.
- A **one-page architecture diagram** showing the data model and how the major modules connect.
- A **short note on what the team would build next** with more time.

Event schedule deliverables: video links submitted 06 Sep 10:30 IST; presentation 13:00 IST.
Evaluator `kais-odoo` / `hackathon-odoo` added as GitHub collaborator.

## 11. Bonus / non-required features

- Multi-currency or multi-company support (PDF §7 — explicitly a bonus).
- Upsell / cross-sell rule configuration screen (PDF §4 A6 — explicitly Optional).
- Report export to PDF / XLS.
- Automated nudge / escalation from a deal health alert.
- Admin / Reporting dashboard (labelled "Optional" on mockup screen 16).

## 12. Open ambiguities

Tracked as DECISION NEEDED entries in `DECISIONS.md`. Still open:

- Discount anomaly threshold; "well above historical average" is unquantified (ADR-007).
- Stalled-deal day count — PDF says "configured", default not given (ADR-007).
- Proration method for mid-cycle changes — daily vs monthly basis not specified (ADR-008).
- Tax handling: products carry a Tax field but no tax rules are specified (ADR-009).
- "Sales Team" appears as a reporting filter but no team entity is described (ADR-009).

All three remaining ADRs block P1 tasks only (T-20, T-21, T-23), so no P0 work is waiting
on them.

**Closed by T-00** and now stated above rather than deferred: the blended risk score formula
and routing thresholds (ADR-005, see BR-1), the warehouse split algorithm (ADR-006, see
BR-4), the customer portal access mechanism (ADR-004 — a signed quotation-scoped token in
the URL, no customer accounts and no email), and the quotation stage machine (ADR-010 — one
`stage` enum, `SENT` a real stage reachable only from `APPROVED`, `REJECTED` terminal, with
return-for-revision as a separate action sending the quotation back to `DRAFT`).
