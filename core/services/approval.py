"""
Approval routing and the audit trail — BR-2, BR-3, ADR-005, ADR-010.

Implements FR-13, FR-15 and FR-16. Owned by **T-10**.

**The rep never requests approval.** `submit()` scores the quotation, reads the
`ApprovalChainRule` rows and generates the steps the chain requires, on its own. That is
AC-3 and it is the product's whole thesis; a "request approval" button anywhere in the
application is a bug.

Invariants this module is responsible for:

* 1 — a quotation cannot reach APPROVED while any step is PENDING.
* 2 — a quotation with `risk_score > 0` cannot reach APPROVED with no ApprovalStep row.
* 3 — steps are created by the system from `ApprovalChainRule`, never by a Rep.
* 4 — every transition out of PENDING writes an AuditLog row with actor, reason and time.

Reject and return-for-revision are **different outcomes** (ADR-010): reject is terminal,
return sends the quotation back to DRAFT for the rep to fix.
"""


class ApprovalConfigurationError(Exception):
    """No `ApprovalChainRule` matches a score, or the bands do not tile.

    Raised loudly and never swallowed. A score that matches no rule must **not** fall
    through to "no approval needed" — silently skipping governance is the exact failure
    this product exists to prevent, so a misconfigured chain stops the submit instead.
    """


class ApprovalPermissionError(Exception):
    """The acting user's role does not match the step's level.

    A Rep attempting an approval is refused here, in the service, as well as in the view.
    T-04's acceptance is that the refusal is server-side and not a hidden button.
    """


def required_levels(score):
    """Which approver levels a score requires, read from `ApprovalChainRule`.

    Bands are inclusive at both ends and must tile the whole space with no gap and no
    overlap (ADR-005 seeds 0.00 / 0.01-7.99 / 8.00+). Configuration, not code: changing
    a row in the admin changes routing on the next quotation.

    Args:
        score: Decimal, as produced by `risk.score_quotation()`.

    Returns:
        tuple `(requires_manager: bool, requires_finance: bool)`.

    Raises:
        ApprovalConfigurationError: if no rule matches, or more than one does.
    """
    raise NotImplementedError("T-10 — automatic approval routing and audit trail")


def submit(quotation, actor):
    """Submit a quotation. Scores it, routes it, and moves the stage. One transaction.

    Sequence:
      1. `pricing.recompute_quotation()` so the score is computed on current numbers.
      2. `risk.score_for_quotation()`; snapshot the result on `Quotation.risk_score`.
      3. `required_levels()` on that score.
      4. If neither level is required, stage goes straight to APPROVED — the zero-score
         edge in ADR-010's transition table, and the only route into APPROVED that
         bypasses PENDING_APPROVAL.
      5. Otherwise create the ApprovalStep rows in sequence (Manager 1, Finance 2 when
         required) and set stage to PENDING_APPROVAL.
      6. Write an AuditLog row and touch `last_activity_at`.

    Mixed-category quotations route to the **highest** required level (BR-2) — which falls
    out of the score being order-wide rather than per-line.

    Args:
        quotation: a `core.models.Quotation` in DRAFT or UNDER_NEGOTIATION.
        actor: the `core.models.User` submitting, or `None` for a portal-triggered
            re-entry (BR-6), where there is no user.

    Returns:
        list of created `ApprovalStep` rows — empty when no approval was required.

    Raises:
        ApprovalConfigurationError: propagated from `required_levels()`.
        ValueError: if the quotation's stage cannot be submitted from.
    """
    raise NotImplementedError("T-10 — automatic approval routing and audit trail")


def approve(step, actor, reason):
    """Approve one step. Advances the quotation when it was the last pending step.

    Writes the audit row before returning, always — invariant 4 is not conditional.
    Moves the quotation to APPROVED only when no step remains PENDING (invariant 1).

    Args:
        step: a PENDING `core.models.ApprovalStep`.
        actor: the acting `core.models.User`; role must match `step.level`.
        reason: required non-empty string (BR-3).

    Returns:
        The updated `Quotation`.

    Raises:
        ApprovalPermissionError: if the actor's role does not match the step level.
        ValueError: if the step is not PENDING, or `reason` is empty.
    """
    raise NotImplementedError("T-10 — automatic approval routing and audit trail")


def reject(step, actor, reason):
    """Reject one step. **Terminal** — the quotation goes to REJECTED (ADR-010).

    Any still-pending steps are left as PENDING rather than cancelled, so the audit trail
    shows exactly how far the deal got before it died.

    Raises:
        ApprovalPermissionError, ValueError: as for `approve()`.
    """
    raise NotImplementedError("T-10 — automatic approval routing and audit trail")


def return_for_revision(step, actor, reason):
    """Send the quotation back to DRAFT for the rep to fix.

    A **different action from reject** — PDF B4 lists both, so they differ. The step is
    marked RETURNED, the quotation returns to DRAFT, and any remaining steps are deleted:
    the next submit re-scores and generates fresh ones, because the numbers will have
    changed.

    Raises:
        ApprovalPermissionError, ValueError: as for `approve()`.
    """
    raise NotImplementedError("T-10 — automatic approval routing and audit trail")


def record(quotation, action, actor=None, reason="", payload=None):
    """Append one AuditLog row. The only writer of that table.

    `actor` is `None` for portal actions — a customer has no `User` row (ADR-004), and
    attribution runs through the quotation's Customer instead.

    Args:
        quotation: the `core.models.Quotation` the action happened to.
        action: short uppercase verb, e.g. `"APPROVED"`, `"COUNTER_OFFER_RECEIVED"`.
        actor: `core.models.User` or None.
        reason: free text; required by BR-3 for approvals, rejections and edits.
        payload: JSON-serialisable dict of supporting detail, e.g. the score and the
            per-line breakdown that produced a routing decision.

    Returns:
        The created `AuditLog`.
    """
    raise NotImplementedError("T-10 — automatic approval routing and audit trail")
