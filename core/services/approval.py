"""
Approval routing and the audit trail — BR-2, BR-3, ADR-005, ADR-010.

Implements FR-13, FR-15 and FR-16. Owned by **T-10**.

**The rep never requests approval.** `submit()` scores the quotation, reads the
`ApprovalChainRule` rows and generates the steps the chain requires, on its own. That is
AC-3 and it is the product's whole thesis; a "request approval" button anywhere in the
application is a bug. The builder's button says *Submit for Approval* because that is what
the rep does — submit the quote — and the system decides whether an approval follows.

Invariants this module is responsible for:

* 1 — a quotation cannot reach APPROVED while any step is PENDING.
* 2 — a quotation with `risk_score > 0` cannot reach APPROVED with no ApprovalStep row.
* 3 — steps are created by the system from `ApprovalChainRule`, never by a Rep.
* 4 — every transition out of PENDING writes an AuditLog row with actor, reason and time.

Reject and return-for-revision are **different outcomes** (ADR-010): reject is terminal,
return sends the quotation back to DRAFT for the rep to fix.
"""

from django.db import transaction
from django.utils import timezone


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


# Which roles may act on which step level. ADMIN is included so a single seeded admin can
# drive an end-to-end demo; REP is deliberately absent from both.
_ROLES_FOR_LEVEL = {
    "MANAGER": {"MANAGER", "ADMIN"},
    "FINANCE": {"FINANCE", "ADMIN"},
}


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
    from core.models import ApprovalChainRule

    rules = list(
        ApprovalChainRule.objects.filter(score_min__lte=score, score_max__gte=score)
    )
    if not rules:
        raise ApprovalConfigurationError(
            f"No ApprovalChainRule covers a risk score of {score}. The bands must tile "
            f"the whole range — refusing to route rather than skipping governance."
        )
    if len(rules) > 1:
        overlapping = ", ".join(f"{r.score_min}-{r.score_max}" for r in rules)
        raise ApprovalConfigurationError(
            f"Risk score {score} matches {len(rules)} overlapping ApprovalChainRules "
            f"({overlapping}). Bands must not overlap."
        )
    rule = rules[0]
    return rule.requires_manager, rule.requires_finance


def record(quotation, action, actor=None, reason="", payload=None):
    """Append one AuditLog row. The only writer of that table.

    `actor` is `None` for portal actions — a customer has no `User` row (ADR-004), and
    attribution runs through the quotation's Customer instead.
    """
    from core.models import AuditLog

    return AuditLog.objects.create(
        quotation=quotation,
        actor=actor,
        action=action,
        reason=reason or "",
        payload=payload or {},
    )


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
    from core.models import ApprovalStep, Quotation
    from core.services import pricing, risk

    submittable = {Quotation.Stage.DRAFT, Quotation.Stage.UNDER_NEGOTIATION}
    if quotation.stage not in submittable:
        raise ValueError(
            f"A quotation in {quotation.stage} cannot be submitted; expected one of "
            f"{sorted(submittable)}."
        )
    if not quotation.lines.exists():
        raise ValueError("An empty quotation cannot be submitted.")

    with transaction.atomic():
        pricing.recompute_quotation(quotation)
        result = risk.score_for_quotation(quotation)
        needs_manager, needs_finance = required_levels(result.score)

        # A resubmit re-scores from scratch: stale steps from a previous round would
        # otherwise sit alongside the new ones.
        quotation.approval_steps.all().delete()

        steps = []
        if needs_manager:
            steps.append(ApprovalStep(quotation=quotation, sequence=1, level=ApprovalStep.Level.MANAGER))
        if needs_finance:
            steps.append(
                ApprovalStep(quotation=quotation, sequence=len(steps) + 1, level=ApprovalStep.Level.FINANCE)
            )
        ApprovalStep.objects.bulk_create(steps)

        quotation.risk_score = result.score
        quotation.stage = (
            Quotation.Stage.PENDING_APPROVAL if steps else Quotation.Stage.APPROVED
        )
        quotation.last_activity_at = timezone.now()
        quotation.save(update_fields=["risk_score", "stage", "last_activity_at"])

        record(
            quotation,
            action="SUBMITTED_FOR_APPROVAL" if steps else "AUTO_APPROVED",
            actor=actor,
            reason=(
                f"Automatic: blended risk score {result.score} routed to "
                f"{' then '.join(s.level for s in steps)}."
                if steps
                else "Automatic: risk score 0.00 — no approval required."
            ),
            payload={
                "risk_score": str(result.score),
                "steps": [s.level for s in steps],
                "breakdown": [
                    {
                        "label": line.label,
                        "category": line.category,
                        "given_pct": str(line.given_pct),
                        "allowed_pct": str(line.allowed_pct),
                        "over_by_pct": str(line.over_by_pct),
                    }
                    for line in result.breakdown
                ],
            },
        )
    return steps


def _act(step, actor, reason, status, action, next_stage, clear_remaining=False):
    """Shared body for approve / reject / return. Enforces the rules once, not three times."""
    from core.models import ApprovalStep, Quotation

    if step.status != ApprovalStep.Status.PENDING:
        raise ValueError(f"Step {step.pk} is already {step.status}.")
    if not (reason or "").strip():
        raise ValueError("A reason is required on every approval action (BR-3).")
    if actor is None or actor.role not in _ROLES_FOR_LEVEL.get(step.level, set()):
        raise ApprovalPermissionError(
            f"Role {getattr(actor, 'role', None)} may not act on a {step.level} step."
        )

    with transaction.atomic():
        step.status = status
        step.actor = actor
        step.reason = reason
        step.acted_at = timezone.now()
        step.save(update_fields=["status", "actor", "reason", "acted_at"])

        quotation = step.quotation
        if clear_remaining:
            quotation.approval_steps.filter(status=ApprovalStep.Status.PENDING).delete()

        if next_stage is None:
            # Approve: the quotation only advances once nothing is still pending.
            still_pending = quotation.approval_steps.filter(
                status=ApprovalStep.Status.PENDING
            ).exists()
            stage = quotation.stage if still_pending else Quotation.Stage.APPROVED
        else:
            stage = next_stage

        quotation.stage = stage
        quotation.last_activity_at = timezone.now()
        quotation.save(update_fields=["stage", "last_activity_at"])

        record(
            quotation,
            action=action,
            actor=actor,
            reason=reason,
            payload={"step": step.sequence, "level": step.level},
        )
    return step.quotation


def approve(step, actor, reason):
    """Approve one step. Advances the quotation when it was the last pending step.

    Writes the audit row before returning, always — invariant 4 is not conditional.
    Moves the quotation to APPROVED only when no step remains PENDING (invariant 1).
    """
    from core.models import ApprovalStep

    return _act(step, actor, reason, ApprovalStep.Status.APPROVED, "APPROVED", None)


def reject(step, actor, reason):
    """Reject one step. **Terminal** — the quotation goes to REJECTED (ADR-010).

    Any still-pending steps are left as PENDING rather than cancelled, so the audit trail
    shows exactly how far the deal got before it died.
    """
    from core.models import ApprovalStep, Quotation

    return _act(
        step, actor, reason, ApprovalStep.Status.REJECTED, "REJECTED", Quotation.Stage.REJECTED
    )


def return_for_revision(step, actor, reason):
    """Send the quotation back to DRAFT for the rep to fix.

    A **different action from reject** — PDF B4 lists both, so they differ. The step is
    marked RETURNED, the quotation returns to DRAFT, and any remaining steps are deleted:
    the next submit re-scores and generates fresh ones, because the numbers will have
    changed.
    """
    from core.models import ApprovalStep, Quotation

    return _act(
        step,
        actor,
        reason,
        ApprovalStep.Status.RETURNED,
        "RETURNED_FOR_REVISION",
        Quotation.Stage.DRAFT,
        clear_remaining=True,
    )
