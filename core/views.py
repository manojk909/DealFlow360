"""
Entry layer for the internal application.

Per ARCHITECTURE.md these views authenticate, authorise by role, validate input and then
**call a service**. They hold no business rules: every number on every screen below comes
from `core/services/`, so the figure the rep sees is the figure the system computed.

HTMX endpoints here return HTML partials, not JSON. That is the point of choosing HTMX
over a JSON API plus a client renderer (ADR-001).
"""

from decimal import Decimal, InvalidOperation
from functools import wraps

from django.contrib.auth import login as auth_login
from django.contrib.auth.decorators import login_required
from django.db import connection
from django.db.migrations.recorder import MigrationRecorder
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from urllib.parse import quote

from core.models import (
    ApprovalStep,
    Category,
    Invoice,
    Product,
    Quotation,
    QuotationLine,
    Role,
    Stock,
    User,
)
from core.forms import SignupForm
from core.services import approval, billing, fulfilment, negotiation, pricing, risk, upsell


# --------------------------------------------------------------------- health


def health(request):
    """
    Prove the whole round trip: URL -> view -> ORM -> SQLite -> template.

    Every number on this page is read from db.sqlite3. None of it is a constant; if the
    database is missing or unmigrated this page fails loudly rather than rendering a
    reassuring lie.
    """
    with connection.cursor() as cursor:
        cursor.execute("SELECT sqlite_version()")
        sqlite_version = cursor.fetchone()[0]

    applied = MigrationRecorder(connection).migration_qs
    users = User.objects.all()

    context = {
        "db_vendor": connection.vendor,
        "db_name": str(connection.settings_dict["NAME"]),
        "sqlite_version": sqlite_version,
        "applied_migrations": applied.count(),
        "latest_migration": applied.order_by("-applied").values_list("app", "name").first(),
        "user_count": users.count(),
        "users_by_role": list(
            users.values_list("role", flat=True).order_by("role").distinct()
        ),
        "auth_user_model": f"{User._meta.app_label}.{User.__name__}",
    }
    return render(request, "core/health.html", context)


# --------------------------------------------------------------------- signup


def signup(request):
    """FR-01. Self-service signup, which creates a **Sales Rep** and only a Sales Rep.

    The form has no role field and `SignupForm.Meta.fields` excludes it, so a POST
    carrying `role=MANAGER` is not merely ignored — there is nothing for it to bind to.
    ADR-012 records why: a visitor who could grant themselves approval rights would defeat
    the premise of a product built to stop reps approving their own discounts.

    Manager, Finance and Admin are assigned by an administrator in Django admin.
    """
    if request.user.is_authenticated:
        return redirect("core:quotation_list")

    form = SignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        auth_login(request, user)
        return redirect("core:quotation_list")

    return render(request, "core/signup.html", {"form": form})


# --------------------------------------------------------------------- authorisation


def require_roles(*roles):
    """Refuse the request server-side when the signed-in user holds the wrong role.

    Returns **403, not a redirect to login** — an authenticated user with the wrong role
    has a different problem from an anonymous one, and conflating them hides the refusal.
    T-04's acceptance is that a Rep posting to an approval URL is stopped here rather than
    by an absent button.
    """

    def decorator(view):
        @wraps(view)
        @login_required
        def wrapper(request, *args, **kwargs):
            if request.user.role not in roles:
                return HttpResponseForbidden(
                    f"Your role ({request.user.get_role_display()}) may not perform this "
                    f"action. Required: {', '.join(roles)}."
                )
            return view(request, *args, **kwargs)

        return wrapper

    return decorator


# --------------------------------------------------------------------- helpers


# Tabs the mockup names that are not built yet. Shown greyed in the workspace nav with
# the owning task, rather than hidden — an absent feature honestly labelled costs less
# than one quietly missing (CLAUDE.md hackathon integrity).
UNBUILT_TABS = [
    ("Subscriptions", "T-20"),
    ("Deal Health", "T-21"),
    ("Reports", "T-23"),
]


STAGE_COLUMNS = [
    (Quotation.Stage.DRAFT, "Draft"),
    (Quotation.Stage.PENDING_APPROVAL, "Pending approval"),
    (Quotation.Stage.APPROVED, "Approved"),
    (Quotation.Stage.SENT, "Sent"),
    (Quotation.Stage.UNDER_NEGOTIATION, "Negotiation"),
    (Quotation.Stage.CONFIRMED, "Confirmed"),
]


def _decimal(raw, field, minimum=None, maximum=None):
    """Parse a posted number, refusing anything a service would later choke on.

    Robust input validation is an explicitly scored requirement, and the failure mode we
    care about is a discount of 150 or -5 reaching the database and being refused there
    with a 500 instead of a message.
    """
    try:
        value = Decimal(str(raw).strip())
    except (InvalidOperation, AttributeError, TypeError):
        raise ValueError(f"{field} must be a number, got {raw!r}.")
    if minimum is not None and value < minimum:
        raise ValueError(f"{field} must be at least {minimum}.")
    if maximum is not None and value > maximum:
        raise ValueError(f"{field} must be at most {maximum}.")
    return value


def _builder_state(quotation, error=None, dismissed=()):
    """Everything the builder's live region needs, recomputed from the services.

    Called on first render and again after every HTMX edit, so the totals, the margin and
    the per-line ceiling check can never drift apart — they are produced together, by the
    same two service calls the rest of the application uses.
    """
    totals = pricing.recompute_quotation(quotation)
    result = risk.score_for_quotation(quotation)
    by_line = {line.line_id: line for line in result.breakdown}

    rows = []
    for line in quotation.lines.select_related("product", "product__category").all():
        rows.append({"line": line, "risk": by_line.get(line.pk)})

    return {
        "quotation": quotation,
        "rows": rows,
        "totals": totals,
        "risk": result,
        "error": error,
        # Rendered inside the live region on purpose: adding a suggestion has to update
        # the margin indicator in the SAME swap (AC-4), and the panel itself has to
        # refresh so the product just added stops being suggested.
        "suggestions": upsell.suggest(quotation, exclude_product_ids=dismissed),
        "min_margin_pct": upsell.DEFAULT_MIN_MARGIN_PCT,
    }


def _render_builder_region(request, quotation, error=None, status=200):
    """Swap only the live region — no full page reload. This is what makes AC-4 work."""
    return render(
        request,
        "core/partials/builder_region.html",
        _builder_state(
            quotation,
            error=error,
            dismissed=request.session.get("upsell_dismissed", []),
        ),
        status=status,
    )


# --------------------------------------------------------------------- T-11 list


@login_required
def quotation_list(request):
    """FR-09 / B2. The workspace landing page: quotations as selectable cards.

    Grouped into stage columns the way the mockup lays them out. Deliberately cards
    rather than a table — a rep scans a pipeline, they do not read a spreadsheet.
    """
    quotations = (
        Quotation.objects.select_related("customer", "customer__tier", "rep")
        .order_by("-last_activity_at")
    )
    by_stage = {stage: [] for stage, _ in STAGE_COLUMNS}
    other = []
    for quotation in quotations:
        (by_stage[quotation.stage] if quotation.stage in by_stage else other).append(quotation)

    columns = [
        {"stage": stage, "label": label, "quotations": by_stage[stage]}
        for stage, label in STAGE_COLUMNS
    ]
    return render(
        request,
        "core/quotation_list.html",
        {
            "active": "quotations",
            "unbuilt": UNBUILT_TABS,
            "columns": columns,
            "closed": other,
            "total_count": quotations.count(),
            "pending_count": len(by_stage[Quotation.Stage.PENDING_APPROVAL]),
        },
    )


# --------------------------------------------------------------------- T-12 builder


@login_required
def quotation_builder(request, pk):
    """FR-10 / B3. Pick products, adjust quantities, discount lines, watch the margin."""
    quotation = get_object_or_404(
        Quotation.objects.select_related("customer", "customer__tier", "rep"), pk=pk
    )
    context = _builder_state(
        quotation, dismissed=request.session.get("upsell_dismissed", [])
    )
    context["active"] = "quotations"
    context["unbuilt"] = UNBUILT_TABS
    context["categories"] = (
        Category.objects.prefetch_related("products").order_by("name")
    )
    context["products_by_category"] = [
        (category, list(category.products.filter(active=True).order_by("name")))
        for category in Category.objects.order_by("name")
    ]
    context["portal_url"] = (
        negotiation.portal_link(quotation, request) if quotation.portal_token else None
    )
    context["can_share"] = quotation.stage in {
        Quotation.Stage.APPROVED,
        Quotation.Stage.SENT,
        Quotation.Stage.UNDER_NEGOTIATION,
    }
    context["editable"] = quotation.stage in {
        Quotation.Stage.DRAFT,
        Quotation.Stage.UNDER_NEGOTIATION,
    }
    return render(request, "core/quotation_builder.html", context)


@require_POST
@login_required
def line_add(request, pk):
    quotation = get_object_or_404(Quotation, pk=pk)
    try:
        product = Product.objects.select_related("subscription_plan").get(
            pk=request.POST.get("product_id"), active=True
        )
    except (Product.DoesNotExist, ValueError):
        return _render_builder_region(request, quotation, "That product does not exist.", 400)

    recurring = product.subscription_plan is not None
    QuotationLine.objects.create(
        quotation=quotation,
        product=product,
        qty=1,
        unit_price=pricing.resolve_unit_price(product, quotation.customer),
        discount_pct=Decimal("0"),
        # Keeps DATA_MODEL invariant 9 satisfied without the caller thinking about it.
        line_type=(
            QuotationLine.LineType.RECURRING if recurring else QuotationLine.LineType.ONE_TIME
        ),
        subscription_plan=product.subscription_plan if recurring else None,
    )
    return _render_builder_region(request, quotation)


@require_POST
@login_required
def line_update(request, pk, line_id):
    """Quantity stepper and per-line discount. One endpoint, one partial back."""
    quotation = get_object_or_404(Quotation, pk=pk)
    line = get_object_or_404(QuotationLine, pk=line_id, quotation=quotation)

    try:
        if "qty" in request.POST:
            qty = int(_decimal(request.POST["qty"], "Quantity", minimum=Decimal("1")))
            line.qty = qty
        if "discount_pct" in request.POST:
            line.discount_pct = _decimal(
                request.POST["discount_pct"], "Discount",
                minimum=Decimal("0"), maximum=Decimal("100"),
            )
    except ValueError as exc:
        return _render_builder_region(request, quotation, str(exc), 400)

    line.save(update_fields=["qty", "discount_pct"])
    return _render_builder_region(request, quotation)


@require_POST
@login_required
def line_delete(request, pk, line_id):
    quotation = get_object_or_404(Quotation, pk=pk)
    get_object_or_404(QuotationLine, pk=line_id, quotation=quotation).delete()
    return _render_builder_region(request, quotation)


@require_POST
@login_required
def order_discount(request, pk):
    quotation = get_object_or_404(Quotation, pk=pk)
    try:
        quotation.order_discount_pct = _decimal(
            request.POST.get("order_discount_pct", "0"), "Order discount",
            minimum=Decimal("0"), maximum=Decimal("100"),
        )
    except ValueError as exc:
        return _render_builder_region(request, quotation, str(exc), 400)

    quotation.save(update_fields=["order_discount_pct"])
    return _render_builder_region(request, quotation)


@require_POST
@login_required
def quotation_submit(request, pk):
    """AC-3. The rep submits the quote; the **system** decides whether approval follows."""
    quotation = get_object_or_404(Quotation, pk=pk)
    try:
        approval.submit(quotation, request.user)
    except (ValueError, approval.ApprovalConfigurationError) as exc:
        return _render_builder_region(request, quotation, str(exc), 400)
    return redirect("core:quotation_builder", pk=quotation.pk)


# --------------------------------------------------------------------- T-13 approval


@require_roles(Role.MANAGER, Role.FINANCE, Role.ADMIN)
def approval_list(request):
    """Quotations waiting on somebody. Reps are refused this screen by the decorator."""
    pending = (
        Quotation.objects.filter(stage=Quotation.Stage.PENDING_APPROVAL)
        .select_related("customer", "customer__tier", "rep")
        .prefetch_related("approval_steps")
        .order_by("-risk_score")
    )
    rows = []
    for quotation in pending:
        steps = list(quotation.approval_steps.all())
        waiting = next((s for s in steps if s.status == ApprovalStep.Status.PENDING), None)
        rows.append({"quotation": quotation, "steps": steps, "waiting_on": waiting})
    return render(
        request,
        "core/approval_list.html",
        {"rows": rows, "active": "approvals", "unbuilt": UNBUILT_TABS},
    )


@require_roles(Role.MANAGER, Role.FINANCE, Role.ADMIN)
def approval_detail(request, pk):
    """FR-14 / B4. The score, and the per-line breakdown that produced it.

    The breakdown is not decoration: a score an approver cannot check by hand is a score
    they will not trust. `risk.score_for_quotation` returns it alongside the number, and
    this screen renders both.
    """
    quotation = get_object_or_404(
        Quotation.objects.select_related("customer", "customer__tier", "rep"), pk=pk
    )
    result = risk.score_for_quotation(quotation)
    steps = list(quotation.approval_steps.select_related("actor").order_by("sequence"))
    waiting = next((s for s in steps if s.status == ApprovalStep.Status.PENDING), None)

    actionable = waiting is not None and request.user.role in (
        {Role.MANAGER, Role.ADMIN} if waiting.level == ApprovalStep.Level.MANAGER
        else {Role.FINANCE, Role.ADMIN}
    )

    return render(
        request,
        "core/approval_detail.html",
        {
            "active": "approvals",
            "unbuilt": UNBUILT_TABS,
            "quotation": quotation,
            "risk": result,
            "steps": steps,
            "waiting_on": waiting,
            "actionable": actionable,
            "audit": quotation.audit_log.select_related("actor").order_by("created_at"),
            "error": request.GET.get("error"),
        },
    )


@require_POST
@require_roles(Role.MANAGER, Role.FINANCE, Role.ADMIN)
def approval_act(request, pk):
    """Approve / Reject / Return, each demanding a reason (BR-3).

    The role check happens twice on purpose: once in the decorator for the screen, and
    again inside `approval.py` for the specific step level. The service is the boundary
    that actually matters — this view could be bypassed, the service cannot.
    """
    quotation = get_object_or_404(Quotation, pk=pk)
    step = get_object_or_404(
        ApprovalStep, pk=request.POST.get("step_id"), quotation=quotation
    )
    action = request.POST.get("action")
    reason = request.POST.get("reason", "")

    handlers = {
        "approve": approval.approve,
        "reject": approval.reject,
        "return": approval.return_for_revision,
    }
    if action not in handlers:
        return redirect(f"/workspace/approvals/{pk}/?error=Unknown+action.")

    try:
        handlers[action](step, request.user, reason)
    except (ValueError, approval.ApprovalPermissionError) as exc:
        return redirect(f"/workspace/approvals/{pk}/?error={quote(str(exc))}")

    return redirect("core:approval_detail", pk=quotation.pk)


# --------------------------------------------------------------------- T-16 fulfilment


@login_required
def fulfilment_list(request):
    """Orders that have cleared approval and are waiting to ship, or already have."""
    orders = (
        Quotation.objects.filter(
            stage__in=[
                Quotation.Stage.APPROVED,
                Quotation.Stage.CONFIRMED,
                Quotation.Stage.FULFILLED,
                Quotation.Stage.INVOICED,
                Quotation.Stage.PAID,
            ]
        )
        .select_related("customer", "rep")
        .order_by("stage", "-last_activity_at")
    )
    rows = []
    for order in orders:
        rows.append(
            {
                "quotation": order,
                "allocations": order.allocations.select_related("warehouse").all(),
                "awaiting": order.stage == Quotation.Stage.APPROVED,
            }
        )
    return render(
        request,
        "core/fulfilment_list.html",
        {
            "rows": rows,
            "stock": Stock.objects.select_related("product", "warehouse").order_by(
                "product__name", "warehouse__name"
            ),
            "active": "fulfilment",
            "unbuilt": UNBUILT_TABS,
        },
    )


def _fulfilment_context(quotation, error=None, message=None):
    """Suggestion plus whatever has actually been committed, side by side."""
    suggestion = fulfilment.suggest_split(quotation)
    lines = {line.pk: line for line in quotation.lines.select_related("product").all()}

    suggested_rows = [
        {"allocation": a, "line": lines.get(a.quotation_line_id)}
        for a in suggestion.allocations
    ]
    committed = list(
        quotation.allocations.select_related("warehouse", "quotation_line__product").all()
    )

    # Only stocked lines can be overridden; the rest have nowhere to ship from.
    overridable = [
        {
            "line": line,
            "stock": Stock.objects.filter(product=line.product)
            .select_related("warehouse")
            .order_by("warehouse__shipping_cost_weight"),
        }
        for line in lines.values()
        if line.pk not in suggestion.skipped_line_ids
    ]

    return {
        "quotation": quotation,
        "suggestion": suggestion,
        "suggested_rows": suggested_rows,
        "committed": committed,
        "skipped_lines": [lines[pk] for pk in suggestion.skipped_line_ids if pk in lines],
        "overridable": overridable,
        "can_accept": quotation.stage
        in {Quotation.Stage.APPROVED, Quotation.Stage.CONFIRMED},
        "error": error,
        "message": message,
        "active": "fulfilment",
        "unbuilt": UNBUILT_TABS,
    }


@login_required
def fulfilment_detail(request, pk):
    """FR-17 / B6. The suggested split from live stock: warehouse, qty, shipments, cost."""
    quotation = get_object_or_404(
        Quotation.objects.select_related("customer", "rep"), pk=pk
    )
    context = _fulfilment_context(
        quotation, error=request.GET.get("error"), message=request.GET.get("message")
    )
    return render(request, "core/fulfilment_detail.html", context)


@require_POST
@login_required
def fulfilment_accept(request, pk):
    """FR-18. Accept the suggested split — recomputed at commit time, not trusted."""
    quotation = get_object_or_404(Quotation, pk=pk)
    try:
        fulfilment.accept_split(quotation, request.user)
    except (ValueError, fulfilment.InsufficientStock) as exc:
        return redirect(f"/workspace/fulfilment/{pk}/?error={quote(str(exc))}")
    return redirect("core:fulfilment_detail", pk=pk)


@require_POST
@login_required
def fulfilment_override(request, pk):
    """FR-18. Manual override, re-validated through the same availability rule."""
    quotation = get_object_or_404(Quotation, pk=pk)
    line = get_object_or_404(
        QuotationLine, pk=request.POST.get("line_id"), quotation=quotation
    )

    pairs = []
    for key, value in request.POST.items():
        if not key.startswith("wh_"):
            continue
        try:
            qty = int(_decimal(value or "0", "Quantity", minimum=Decimal("0")))
        except ValueError as exc:
            return redirect(f"/workspace/fulfilment/{pk}/?error={quote(str(exc))}")
        if qty:
            pairs.append((int(key[3:]), qty))

    if not pairs:
        return redirect(
            f"/workspace/fulfilment/{pk}/?error={quote('An override needs at least one quantity.')}"
        )

    try:
        fulfilment.apply_manual_override(line, pairs, request.user)
    except (ValueError, fulfilment.InsufficientStock) as exc:
        return redirect(f"/workspace/fulfilment/{pk}/?error={quote(str(exc))}")
    return redirect(
        f"/workspace/fulfilment/{pk}/?message={quote('Manual override applied.')}"
    )


# --------------------------------------------------------------------- T-17 invoicing


@login_required
def billing_list(request):
    """Every invoice raised, with what has actually been paid against it."""
    invoices = (
        Invoice.objects.select_related("quotation", "quotation__customer")
        .prefetch_related("payments")
        .order_by("-issue_date", "-id")
    )
    rows = [
        {
            "invoice": invoice,
            "paid": billing._amount_paid(invoice),
            "outstanding": invoice.amount - billing._amount_paid(invoice),
        }
        for invoice in invoices
    ]
    awaiting = Quotation.objects.filter(stage=Quotation.Stage.FULFILLED).select_related(
        "customer"
    )
    return render(
        request,
        "core/billing_list.html",
        {"rows": rows, "awaiting": awaiting, "active": "invoices", "unbuilt": UNBUILT_TABS},
    )


def _billing_context(quotation, error=None):
    invoice = quotation.invoices.first()
    one_time = quotation.lines.filter(line_type=QuotationLine.LineType.ONE_TIME)
    recurring = quotation.lines.exclude(line_type=QuotationLine.LineType.ONE_TIME)

    context = {
        "quotation": quotation,
        "invoice": invoice,
        "one_time_lines": one_time.select_related("product"),
        "recurring_lines": recurring.select_related("product", "subscription_plan"),
        "can_generate": invoice is None
        and quotation.stage
        in {Quotation.Stage.CONFIRMED, Quotation.Stage.FULFILLED}
        and one_time.exists(),
        "error": error,
        "active": "invoices",
        "unbuilt": UNBUILT_TABS,
    }
    if invoice is not None:
        paid = billing._amount_paid(invoice)
        context.update(
            {
                "paid": paid,
                "outstanding": invoice.amount - paid,
                "derived_status": billing.derive_invoice_status(invoice),
                "payments": invoice.payments.order_by("paid_at"),
            }
        )
    return context


@login_required
def billing_detail(request, pk):
    """FR-20. Generate the invoice, record a payment, watch the status derive itself."""
    quotation = get_object_or_404(
        Quotation.objects.select_related("customer", "rep"), pk=pk
    )
    return render(
        request,
        "core/billing_detail.html",
        _billing_context(quotation, error=request.GET.get("error")),
    )


@require_POST
@login_required
def billing_generate(request, pk):
    quotation = get_object_or_404(Quotation, pk=pk)
    try:
        invoice = billing.generate_invoice(quotation)
    except ValueError as exc:
        return redirect(f"/workspace/invoices/{pk}/?error={quote(str(exc))}")
    if invoice is None:
        return redirect(
            f"/workspace/invoices/{pk}/?error="
            + quote(
                "This order has no one-time lines, so there is no invoice to raise. "
                "Recurring lines bill on a schedule (T-20)."
            )
        )
    return redirect("core:billing_detail", pk=pk)


@require_POST
@login_required
def billing_pay(request, pk):
    """Record a payment. Status is derived by the service, never posted from this form."""
    quotation = get_object_or_404(Quotation, pk=pk)
    invoice = quotation.invoices.first()
    if invoice is None:
        return redirect(f"/workspace/invoices/{pk}/?error={quote('No invoice yet.')}")

    try:
        amount = _decimal(request.POST.get("amount", ""), "Amount", minimum=Decimal("0.01"))
        billing.record_payment(
            invoice, amount, method=request.POST.get("method", "BANK_TRANSFER")
        )
    except (ValueError, billing.OverpaymentError) as exc:
        return redirect(f"/workspace/invoices/{pk}/?error={quote(str(exc))}")
    return redirect("core:billing_detail", pk=pk)


@require_POST
@login_required
def quotation_share(request, pk):
    """Mint the portal link and mark the quotation as sent (ADR-010: APPROVED -> SENT).

    No email is sent — ADR-004 closed that. The rep copies the link from the screen.
    """
    quotation = get_object_or_404(Quotation, pk=pk)
    if quotation.stage != Quotation.Stage.APPROVED:
        return redirect("core:quotation_builder", pk=pk)

    negotiation.portal_link(quotation, request)
    quotation.stage = Quotation.Stage.SENT
    quotation.save(update_fields=["stage"])
    approval.record(
        quotation,
        action="PORTAL_LINK_SHARED",
        actor=request.user,
        reason="Portal link created and shared with the customer.",
    )
    return redirect("core:quotation_builder", pk=pk)


# --------------------------------------------------------------------- T-19 upsell


@require_POST
@login_required
def upsell_add(request, pk):
    """AC-4. Add a suggestion and swap the whole live region back.

    The margin indicator, the totals and the remaining suggestions all come back in this
    one response, which is what makes the update feel immediate.
    """
    quotation = get_object_or_404(Quotation, pk=pk)
    try:
        product = Product.objects.select_related("subscription_plan").get(
            pk=request.POST.get("product_id"), active=True
        )
    except (Product.DoesNotExist, ValueError):
        return _render_builder_region(request, quotation, "That product does not exist.", 400)

    upsell.add_to_quotation(quotation, product)
    return _render_builder_region(request, quotation)


@require_POST
@login_required
def upsell_dismiss(request, pk):
    """Stop offering one suggestion for the rest of this editing session."""
    quotation = get_object_or_404(Quotation, pk=pk)
    upsell.dismiss(request.session, request.POST.get("product_id"))
    return _render_builder_region(request, quotation)
