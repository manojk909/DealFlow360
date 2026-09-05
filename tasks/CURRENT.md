# CURRENT TASK

**Status: NOT STARTED**

Done — see `tasks/DONE.md` and `git log`: T-00, T-01, T-02+T-03, the services contract,
T-05/T-06/T-07 (admin as the configuration area), T-08 (pricing), T-09 (risk), T-10
(approval routing) and T-11/T-12/T-13 (the three internal screens).

The workspace runs end to end: build a quotation, watch the margin and the per-line
ceiling check update by HTMX swap, submit, and the system routes it to Manager then
Finance on its own. 55 tests, all passing, none skipped.

---

## T-16 — Warehouse split and backorders

**Blocked by nothing.** ADR-006 is Accepted and `core/services/fulfilment.py` is a written
contract with signatures and docstrings; this task fills in the bodies and builds the
fulfilment screen.

### The two things that must not be got wrong

1. **Non-stocked lines are skipped, not backordered.** Services and Subscriptions have no
   `Stock` rows at all — correctly, you do not warehouse an engagement. A naive
   implementation reports the Onsite Setup Service line as a total backorder and the
   fulfilment screen looks broken on stage. Those line ids belong in
   `SplitSuggestion.skipped_line_ids`.
2. **The seeded case must produce 4 + 2.** Laptop Pro 14, quantity 6, Main Warehouse 4 at
   weight 1.00, East Depot 10 at 1.40. Main is cheapest but cannot cover the line, so the
   single-shipment shortcut does not fire: 4 from Main, 2 from East, two shipments,
   estimated cost 6.80. Not one shipment of 6 from East at 8.40 — ADR-006 explains why,
   and the reasoning matters as much as the number.

### Acceptance

- [ ] Split computed from **live** stock, never cached or seeded.
- [ ] Shows warehouse, quantity from each, shipment count and estimated cost.
- [ ] Accept Suggested Split and Manual Override both work; override is re-validated
      through the same availability rule and refused by the service, not by hiding a control.
- [ ] Shortfall becomes a backorder row; a non-stocked line does not.
- [ ] Invariants 6, 7 and 8 hold.
- [ ] `accept_split` recomputes at commit time rather than trusting the rendered suggestion.

### Then what

T-17 (invoice and payment) completes the cash path, then T-14/T-15 build the customer
portal — which is the demo's best moment and the last MUST-have screen.
