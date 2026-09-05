# DATA MODEL — DealFlow360

Stack-neutral. Entities derive from SPEC.md; fields the PDF does not state are marked
**DECISION NEEDED** rather than invented.

## ER diagram

```
                         ┌──────────────┐
                         │     User     │ role: REP|MANAGER|FINANCE|ADMIN
                         └──────┬───────┘
                                │ owns (rep)
                                │
  ┌────────────┐  tier   ┌──────▼────────┐  1     n  ┌──────────────────┐
  │CustomerTier│◄────────│   Customer    │──────────►│    Quotation     │
  └─────┬──────┘         └───────────────┘           └────────┬─────────┘
        │ max_discount_pct                                    │ 1
        │                                                     │
        │              ┌──────────────────────────────────────┼──────────────┐
        │              │ n                    n               │ n            │ n
        │      ┌───────▼────────┐   ┌─────────▼────────┐ ┌────▼──────┐ ┌─────▼────────┐
        │      │ QuotationLine  │   │  ApprovalStep    │ │ AuditLog  │ │PortalMessage │
        │      └───────┬────────┘   └──────────────────┘ └───────────┘ └──────────────┘
        │              │ n                                              (line-level
        │              │ 1                                               comments +
        │      ┌───────▼────────┐  n      1  ┌──────────────┐            counter-offer)
        │      │    Product     │───────────►│   Category   │
        │      └───┬────────┬───┘            └──────┬───────┘
        │          │        │                       │ n
        │          │        │                       │ 1
        │          │        │   ┌───────────────────▼──────────────┐
        └──────────┼────────┼──►│ CategoryDiscountCeiling          │
     (tier × category)      │   │  tier + category → max_pct       │
                   │        │   └──────────────────────────────────┘
                   │        │
                   │        └──► PriceListEntry (tier → price)
                   │        └──► ProductVariant  [SHOULD]
                   │        └──► SubscriptionPlan  [SHOULD]
                   │
                   │ n           n
              ┌────▼──────────────────┐   n      1  ┌─────────────┐
              │        Stock          │────────────►│  Warehouse  │
              │ product × warehouse   │             │ ship_weight │
              │ qty_on_hand, reserved │             └─────────────┘
              └───────────────────────┘

  Quotation ──1──n──► FulfilmentAllocation ──n──1──► Warehouse
  Quotation ──1──n──► Invoice ──1──n──► Payment
  Quotation ──1──n──► BillingScheduleEntry        [SHOULD]
  Product   ──n──n──► Product  via ProductPair (co-purchase count)  [SHOULD]
  ApprovalChainRule: score range → required approver levels  (config)
```

## Entities

### User
`id`, `email` (unique), `password_hash`, `name`, `role` (`REP|MANAGER|FINANCE|ADMIN`),
`created_at`.
Roles are exactly SPEC.md §3. Customers are **not** Users — portal access is token-based.

### CustomerTier
`id`, `name` (Bronze / Silver / Gold), `max_discount_pct`.
PDF example: Bronze ≤5, Silver ≤10, Gold ≤15.

### Customer
`id`, `name`, `email`, `tier_id` → CustomerTier.

### Category
`id`, `name` (Hardware / Services / Subscriptions per PDF §B3).

### Product
`id`, `name`, `category_id`, `list_price`, `cost`, `unit`, `tax_pct`, `description`,
`is_promoted` (bool, ranks higher in upsell suggestions — PDF A6), `active`.
`cost` is required: the live margin indicator (B3) cannot exist without it, even though
the PDF's field list for A2 does not name it.
**DECISION NEEDED:** how `tax_pct` participates in totals and margin. PDF lists a Tax
field but specifies no tax rules (ADR-009).

### ProductVariant *(SHOULD)*
`id`, `product_id`, `attribute` (e.g. Size, Pack), `value`, `extra_price`.

### PriceListEntry
`id`, `product_id`, `tier_id`, `price`, `currency`.
Currency-specific rules are named in A2; multi-currency is a BONUS per PDF §7.

### CategoryDiscountCeiling
`id`, `tier_id`, `category_id`, `max_discount_pct`.
The per-line ceiling in BR-1. Effective ceiling for a line =
`min(tier.max_discount_pct, this.max_discount_pct)`.

### ApprovalChainRule
`id`, `score_min`, `score_max`, `requires_manager` (bool), `requires_finance` (bool).
Configuration, not code — CLAUDE.md forbids hardcoding these thresholds.

### Quotation
`id`, `number`, `customer_id`, `rep_id` → User, `stage`, `order_discount_pct`,
`subtotal`, `total`, `margin_amount`, `margin_pct`, `risk_score`, `portal_token`,
`created_at`, `last_activity_at`.
`last_activity_at` drives the stalled-deal detector (BR-8).

**Stage lifecycle:**
```
DRAFT → PENDING_APPROVAL → APPROVED → CONFIRMED → FULFILLED → INVOICED → PAID
  │            │  ▲                        ▲
  │            │  └────────────────────────┘  portal counter-offer re-entry (BR-6)
  │            └─► REJECTED
  └─► SENT → UNDER_NEGOTIATION → (back to PENDING_APPROVAL or straight to CONFIRMED)
```
`SENT`, `UNDER_NEGOTIATION`, `CONFIRMED` are the three portal-visible statuses named in
PDF B8. **DECISION NEEDED:** whether `SENT` is a distinct stage or a flag on `APPROVED`
(ADR-010).

### QuotationLine
`id`, `quotation_id`, `product_id`, `variant_id` (nullable), `qty`, `unit_price`,
`discount_pct`, `line_total`, `line_cost`, `line_type` (`ONE_TIME|RECURRING`),
`subscription_plan_id` (nullable), `added_via_upsell` (bool).
`line_type` is what lets one order mix one-time and recurring lines (BR-5, B7).

### ApprovalStep
`id`, `quotation_id`, `sequence`, `level` (`MANAGER|FINANCE`), `status`
(`PENDING|APPROVED|REJECTED|RETURNED`), `actor_id` (nullable), `reason`, `acted_at`.
Steps are generated by the chain rule matching the quotation's score. Finance rows exist
only when required — PDF B4: Finance is "only shown when required".

### AuditLog
`id`, `quotation_id`, `actor_id` (nullable — portal actions have no User), `action`,
`reason`, `payload`, `created_at`.
BR-3 requires user, timestamp and reason on every approval, rejection and edit.

### Warehouse
`id`, `name`, `shipping_cost_weight`.
PDF examples: "Main Warehouse", "East Depot".
**DECISION NEEDED:** replenishment rule fields (A4 names them, does not define them).

### Stock
`id`, `product_id`, `warehouse_id`, `qty_on_hand`, `qty_reserved`.
Unique on (`product_id`, `warehouse_id`). Available = `qty_on_hand − qty_reserved`.

### FulfilmentAllocation
`id`, `quotation_id`, `quotation_line_id`, `warehouse_id`, `qty`, `is_backorder`,
`is_manual_override`, `created_at`.
Shipment count = distinct warehouses across a quotation's allocations (BR-4).

### SubscriptionPlan *(SHOULD)*
`id`, `name`, `interval` (`MONTHLY|QUARTERLY|YEARLY`), `proration_method`,
`cancellation_policy`.
**DECISION NEEDED:** proration basis — daily or whole-period (ADR-008).

### BillingScheduleEntry *(SHOULD)*
`id`, `quotation_id`, `quotation_line_id`, `due_date`, `amount`, `status`
(`SCHEDULED|BILLED|CANCELLED`), `is_proration_adjustment`.

### Invoice
`id`, `quotation_id`, `number`, `amount`, `status` (`DRAFT|UNPAID|PARTIAL|PAID`),
`issue_date`, `due_date`, `is_credit_note`.

### Payment
`id`, `invoice_id`, `amount`, `method`, `paid_at`.

### PortalMessage
`id`, `quotation_id`, `quotation_line_id` (nullable — order-level messages exist),
`author` (`CUSTOMER|REP`), `body`, `counter_discount_pct` (nullable), `created_at`.
Covers both the line-level comment tool and the counter-discount field (B8).

### ProductPair *(SHOULD)*
`product_a_id`, `product_b_id`, `co_purchase_count`.
Backs the ranked upsell suggestions (A6, B5).

## Calculated fields

| Field | Derivation | Where |
|---|---|---|
| `QuotationLine.line_total` | `qty × unit_price × (1 − discount_pct/100)` | `core/services/pricing.py` |
| `Quotation.subtotal`, `.total` | sum of lines, then order-level discount | `core/services/pricing.py` |
| `Quotation.margin_amount/pct` | `(total − Σ line_cost) / total` | `core/services/pricing.py` |
| `Quotation.risk_score` | blended over-ceiling score, BR-1 | `core/services/risk.py` |
| effective line ceiling | `min(tier.max_pct, categoryCeiling.max_pct)` | `core/services/risk.py` |
| available stock | `qty_on_hand − qty_reserved` | `core/services/fulfilment.py` |
| shipment count | distinct warehouses in allocations | `core/services/fulfilment.py` |
| upsell margin delta | margin after adding − margin now | `core/services/upsell.py` |
| stalled | `now − last_activity_at > configured days` | `core/services/health.py` |
| discount anomaly | line discount vs rep's historical average | `core/services/health.py` |

Stored where the demo must show a historical value (`risk_score` at approval time);
computed on read where it must be live (margin while editing).

## Critical invariants

1. A Quotation cannot enter `APPROVED` while any ApprovalStep is `PENDING`.
2. A Quotation with `risk_score > 0` cannot reach `APPROVED` without at least one
   ApprovalStep row. Skipping governance is the failure this whole product exists to prevent.
3. ApprovalStep rows are created **by the system** from ApprovalChainRule — never by a Rep.
4. Every ApprovalStep transition out of `PENDING` writes an AuditLog row carrying
   `actor_id`, `reason` and a timestamp (BR-3).
5. A Quotation cannot be `CONFIRMED` unless it is `APPROVED` or its risk_score is 0.
6. Σ FulfilmentAllocation.qty per line ≤ QuotationLine.qty. Any shortfall exists as a
   row with `is_backorder = true`.
7. A FulfilmentAllocation cannot exceed the warehouse's available stock for that product
   at allocation time.
8. `Stock.qty_reserved` ≤ `Stock.qty_on_hand`, always.
9. A line with `line_type = RECURRING` must have a `subscription_plan_id`; a
   `ONE_TIME` line must not.
10. One-time and recurring lines on the same quotation bill through **separate** artefacts —
    an Invoice for one-time, BillingScheduleEntry rows for recurring (BR-5).
11. Σ Payment.amount per Invoice ≤ Invoice.amount. Invoice status is derived from that
    sum, never set by hand.
12. A portal token grants access to **exactly one** Quotation. Enforced server-side.
13. A portal counter-offer that pushes the score past the chain threshold **must** move
    the Quotation back to `PENDING_APPROVAL` and generate fresh ApprovalStep rows (BR-6).
14. `min(tier ceiling, category ceiling)` is the effective ceiling — the stricter of the
    two always wins. This is the mechanism behind the PDF's Gold-customer worked example.

## Ownership

- Quotation → `rep_id` (the owning Sales Rep).
- ApprovalStep → `actor_id` once acted upon.
- AuditLog → `actor_id`, nullable for portal (customer) actions.
- Portal actions are attributed to the Quotation's Customer via the token, not to a User row.

## Audit / history requirements

- Every approval, rejection and edit: user, timestamp, reason (BR-3, non-negotiable).
- `Quotation.last_activity_at` updated on every state-changing action — the deal health
  dashboard is meaningless without it.
- `risk_score` snapshotted on the Quotation so the approval screen shows the score the
  approver actually acted on, not a recomputed one.
- Portal messages are append-only; a negotiation history that can be edited is not a
  negotiation history.
