# CURRENT TASK

**Status: NOT STARTED**

**Flow A works end to end.** Build a quotation, watch the per-line ceiling check and the
margin update by HTMX swap, submit, get routed to Manager then Finance automatically,
approve, split 4 + 2 across two warehouses at cost 6.80, invoice the one-time lines only,
record a payment, reach PAID. 88 tests, all passing, none skipped.

Remaining MUST-have work is the customer portal.

---

## T-14 and T-15 — Customer portal access and the re-approval loop

**Flow B, and the best moment in the demo.** ADR-004 is Accepted and
 is a written contract with signatures and docstrings.

### The rules that are not negotiable

- A signed token grants access to **exactly one** quotation, enforced server-side
  (invariant 12). Changing the token to reach another quotation returns **403**, never
  that quotation and never a redirect to the internal login.
- Portal views must **not** sit behind  and must **never** read
  . A customer has no account. Audit rows for portal actions carry a null
  actor and attribute through the quotation's customer.
- Visually distinct from the internal workspace. PDF §7 requires a genuinely separate
  restricted view, not an internal screen relabelled.
- **A counter-discount replaces the targeted line's discount. It does not stack as a
  second order-level discount.** Beta is Silver with a 10% ceiling; a 15% counter is 5
  points over, which is the Manager-only band and matches DEMO B5. Stacking it on the
  line's existing 8% gives roughly 21 points over, pulls in Finance, and strands the
  demo script waiting for an approval it never shows.

### Acceptance

- [ ] Token-scoped access to one quotation; a tampered token returns 403.
- [ ] Status shown as Sent / Under Negotiation / Confirmed — a display mapping over
      , not a second stored field (ADR-010).
- [ ] Line-level comments and change requests, append-only.
- [ ] Counter-discount re-scores through ; if over threshold the quotation
      **automatically** re-enters PENDING_APPROVAL with fresh steps (AC-7, invariant 13).
- [ ] Confirm Quotation works and is reflected internally.
- [ ] Portal link copyable from the internal quotation screen. No email is sent (ADR-004).

### Then what

T-18, the verification pass over all eight acceptance criteria. AC-1 through AC-6 and AC-8
are already demonstrable; AC-7 is what the portal adds.
