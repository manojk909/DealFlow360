"""T-18: the eight acceptance criteria from SPEC.md section 9, in ONE continuous pass.

Freshly seeded database, real views, HTTP requests only. No service is called directly
except to read a value back for an assertion.
"""
from decimal import Decimal

from django.test import Client

from core.models import (
    CustomerTier, Invoice, Product, Quotation, Stock, SubscriptionPlan, User, Warehouse,
)

results = []
failures = []


def observe(criterion, label, actual, expected=None):
    ok = True if expected is None else actual == expected
    mark = "PASS" if ok else "FAIL"
    line = f"    {mark}  {label}: {actual!r}"
    if not ok:
        line += f"  expected {expected!r}"
        failures.append(f"{criterion} {label}")
    print(line)
    results.append((criterion, label, actual, ok))
    return ok


def heading(criterion, text):
    print()
    print("=" * 78)
    print(f"{criterion}  {text}")
    print("=" * 78)


anon = Client(SERVER_NAME="localhost")
admin = Client(SERVER_NAME="localhost")
rep = Client(SERVER_NAME="localhost")
mgr = Client(SERVER_NAME="localhost")
fin = Client(SERVER_NAME="localhost")
buyer = Client(SERVER_NAME="localhost")     # portal. No account, never logs in.

# ---------------------------------------------------------------------------- AC-1

heading("AC-1", "Sign up / log in, then set up a tier, a warehouse and a plan")

r = anon.post("/signup/", {
    "email": "gate.rep@dealflow.test", "name": "Gate Rep",
    "password1": "gate-pass-phrase-99", "password2": "gate-pass-phrase-99",
})
new_user = User.objects.filter(email="gate.rep@dealflow.test").first()
observe("AC-1", "signup succeeds", r.status_code, 302)
observe("AC-1", "and creates a REP, not an approver", new_user.role, "REP")

assert admin.login(email="admin@dealflow.test", password="dealflow360")
observe("AC-1", "admin reaches the backend config area", admin.get("/admin/").status_code, 200)

r = admin.post("/admin/core/customertier/add/", {
    "name": "Platinum", "max_discount_pct": "18",
    "category_ceilings-TOTAL_FORMS": "0", "category_ceilings-INITIAL_FORMS": "0",
    "category_ceilings-MIN_NUM_FORMS": "0", "category_ceilings-MAX_NUM_FORMS": "1000",
    "_save": "Save",
}, follow=True)
observe("AC-1", "discount tier created", CustomerTier.objects.filter(name="Platinum").exists(), True)

r = admin.post("/admin/core/warehouse/add/",
               {"name": "North Hub", "shipping_cost_weight": "1.20", "_save": "Save"}, follow=True)
observe("AC-1", "warehouse created", Warehouse.objects.filter(name="North Hub").exists(), True)

r = admin.post("/admin/core/subscriptionplan/add/", {
    "name": "Gate Monthly", "interval": "MONTHLY",
    "proration_method": "UNDECIDED", "cancellation_policy": "UNDECIDED", "_save": "Save",
}, follow=True)
observe("AC-1", "subscription plan created", SubscriptionPlan.objects.filter(name="Gate Monthly").exists(), True)

# "visible on reload" — fetch the changelists again in fresh requests.
for model, needle in [("customertier", "Platinum"), ("warehouse", "North Hub"),
                      ("subscriptionplan", "Gate Monthly")]:
    body = admin.get(f"/admin/core/{model}/").content.decode()
    observe("AC-1", f"{needle} still visible on reload", needle in body, True)

# ---------------------------------------------------------------------------- AC-2

heading("AC-2", "Create a quotation, add a line discounted beyond what is allowed")

assert rep.login(email="rep@dealflow.test", password="dealflow360")
quote = Quotation.objects.get(number="Q-2026-0001")   # Acme, Gold, empty draft
laptop = Product.objects.get(name="Laptop Pro 14")
setup = Product.objects.get(name="Onsite Setup Service")

rep.post(f"/workspace/quotations/{quote.pk}/lines/add/", {"product_id": laptop.pk})
laptop_line = quote.lines.get(product=laptop)
rep.post(f"/workspace/quotations/{quote.pk}/lines/{laptop_line.pk}/", {"qty": "6"})
body = rep.post(f"/workspace/quotations/{quote.pk}/lines/{laptop_line.pk}/",
                {"discount_pct": "12"}).content.decode()
observe("AC-2", "hardware at 12% is inside its 15% ceiling", "OK" in body, True)

rep.post(f"/workspace/quotations/{quote.pk}/lines/add/", {"product_id": setup.pk})
setup_line = quote.lines.get(product=setup)
body = rep.post(f"/workspace/quotations/{quote.pk}/lines/{setup_line.pk}/",
                {"discount_pct": "18"}).content.decode()
setup_line.refresh_from_db()
observe("AC-2", "the over-limit line saves", setup_line.discount_pct, Decimal("18.00"))
observe("AC-2", "and the system flags it immediately", "OVER +8 pt" in body, True)

# ---------------------------------------------------------------------------- AC-4

heading("AC-4", "Accept one upsell suggestion while building")

quote.refresh_from_db()
before_total, before_margin = quote.total, quote.margin_pct
care = Product.objects.get(name="Care Plan 2yr")
body = rep.get(f"/workspace/quotations/{quote.pk}/").content.decode()
observe("AC-4", "Care Plan 2yr is the top suggestion", "Care Plan 2yr" in body, True)

r = rep.post(f"/workspace/quotations/{quote.pk}/upsell/add/", {"product_id": care.pk})
swap = r.content.decode()
quote.refresh_from_db()
observe("AC-4", "no full page reload", "<html" in swap, False)
observe("AC-4", "order total updates", f"{before_total} -> {quote.total}", f"{before_total} -> {quote.total}")
observe("AC-4", "total actually changed", quote.total != before_total, True)
observe("AC-4", "margin actually changed", quote.margin_pct != before_margin, True)
observe("AC-4", "new margin is in the same response", f"{quote.margin_pct:.2f}" in swap, True)

# ---------------------------------------------------------------------------- AC-3

heading("AC-3", "Confirm the quotation; it must ask for approval on its own")

r = rep.post(f"/workspace/quotations/{quote.pk}/submit/")
quote.refresh_from_db()
observe("AC-3", "stage moved without any manual request", quote.stage, "PENDING_APPROVAL")
observe("AC-3", "score snapshotted", quote.risk_score, Decimal("8.00"))
steps = list(quote.approval_steps.order_by("sequence").values_list("level", "status"))
observe("AC-3", "steps generated by the system", steps, [("MANAGER", "PENDING"), ("FINANCE", "PENDING")])
observe("AC-3", "a rep cannot approve their own quote",
        rep.post(f"/workspace/approvals/{quote.pk}/act/",
                 {"step_id": quote.approval_steps.first().pk, "action": "approve",
                  "reason": "self approval attempt"}).status_code, 403)

# ---------------------------------------------------------------------------- AC-5

heading("AC-5", "Approve, then check fulfilment splits across two warehouses")

assert mgr.login(email="manager@dealflow.test", password="dealflow360")
assert fin.login(email="finance@dealflow.test", password="dealflow360")
mgr.post(f"/workspace/approvals/{quote.pk}/act/",
         {"step_id": quote.approval_steps.get(level="MANAGER").pk, "action": "approve",
          "reason": "Volume justifies the service overage."})
quote.refresh_from_db()
observe("AC-5", "still pending while Finance is outstanding", quote.stage, "PENDING_APPROVAL")
fin.post(f"/workspace/approvals/{quote.pk}/act/",
         {"step_id": quote.approval_steps.get(level="FINANCE").pk, "action": "approve",
          "reason": "Within policy for a Gold account."})
quote.refresh_from_db()
observe("AC-5", "approved", quote.stage, "APPROVED")

body = rep.get(f"/workspace/fulfilment/{quote.pk}/").content.decode()
observe("AC-5", "split shows both warehouses",
        "Main Warehouse" in body and "East Depot" in body, True)
observe("AC-5", "estimated cost shown", "6.80" in body, True)
observe("AC-5", "non-warehoused line named as skipped", "skipped, not backordered" in body, True)

rep.post(f"/workspace/fulfilment/{quote.pk}/accept/")
quote.refresh_from_db()
reserved = {s.warehouse.name: s.qty_reserved
            for s in Stock.objects.filter(product=laptop).select_related("warehouse")}
observe("AC-5", "stock pulled from the correct warehouses", reserved,
        {"Main Warehouse": 4, "East Depot": 2})
observe("AC-5", "stage fulfilled", quote.stage, "FULFILLED")

# ---------------------------------------------------------------------------- AC-6

heading("AC-6", "One-time product and a recurring subscription, billed separately")

rep.post(f"/workspace/invoices/{quote.pk}/generate/")
quote.refresh_from_db()
invoice = Invoice.objects.get(quotation=quote)
one_time = sum((l.line_total for l in quote.lines.filter(line_type="ONE_TIME")), Decimal("0"))
recurring = sum((l.line_total for l in quote.lines.exclude(line_type="ONE_TIME")), Decimal("0"))
observe("AC-6", "invoice equals the one-time lines", invoice.amount, one_time)
observe("AC-6", "recurring value excluded from it", recurring > 0 and invoice.amount != one_time + recurring, True)
print(f"           one-time {one_time} invoiced, recurring {recurring} on a separate schedule")
body = rep.get(f"/workspace/invoices/{quote.pk}/").content.decode()
observe("AC-6", "screen shows them separately", "Recurring lines" in body, True)

# ---------------------------------------------------------------------------- AC-8

heading("AC-8", "Record a payment; invoice status updates")

r = rep.post(f"/workspace/invoices/{quote.pk}/pay/",
             {"amount": str(invoice.amount + Decimal("1")), "method": "BANK_TRANSFER"})
invoice.refresh_from_db()
observe("AC-8", "overpayment refused, no payment row", invoice.payments.count(), 0)

half = (invoice.amount / 2).quantize(Decimal("0.01"))
rep.post(f"/workspace/invoices/{quote.pk}/pay/", {"amount": str(half), "method": "BANK_TRANSFER"})
invoice.refresh_from_db()
observe("AC-8", "part payment derives PARTIAL", invoice.status, "PARTIAL")

rep.post(f"/workspace/invoices/{quote.pk}/pay/",
         {"amount": str(invoice.amount - half), "method": "BANK_TRANSFER"})
invoice.refresh_from_db()
quote.refresh_from_db()
observe("AC-8", "full payment derives PAID", invoice.status, "PAID")
observe("AC-8", "order reaches PAID", quote.stage, "PAID")

# ---------------------------------------------------------------------------- AC-7

heading("AC-7", "Customer requests a bigger discount in the portal")

beta = Quotation.objects.get(number="Q-2026-0002")
token = beta.portal_token
service = beta.lines.get(product__name="Onsite Setup Service")

r = buyer.get(f"/portal/{token}/")
body = r.content.decode()
observe("AC-7", "portal opens on the token", r.status_code, 200)
observe("AC-7", "restricted: no internal nav",
        any(x in body for x in ["/workspace/", "/admin/", "Back-end"]), False)
observe("AC-7", "a tampered token is refused",
        buyer.get(f"/portal/{token[:-4]}xxxx/").status_code, 403)

buyer.post(f"/portal/{token}/comment/",
           {"body": "Can you do better on the service?", "line_id": str(service.pk)})
buyer.post(f"/portal/{token}/counter/",
           {"counter_discount_pct": "15", "line_id": str(service.pk)})
beta.refresh_from_db()
service.refresh_from_db()
observe("AC-7", "counter replaced the line discount", service.discount_pct, Decimal("15.00"))
observe("AC-7", "re-scored", beta.risk_score, Decimal("5.00"))
observe("AC-7", "went back for approval automatically", beta.stage, "PENDING_APPROVAL")
observe("AC-7", "with fresh steps, Manager only",
        list(beta.approval_steps.values_list("level", "status")), [("MANAGER", "PENDING")])

mgr.post(f"/workspace/approvals/{beta.pk}/act/",
         {"step_id": beta.approval_steps.get().pk, "action": "approve",
          "reason": "15% holds the account."})
buyer.post(f"/portal/{token}/confirm/")
beta.refresh_from_db()
observe("AC-7", "customer confirms after approval", beta.stage, "CONFIRMED")

# ---------------------------------------------------------------------------- summary

print()
print("=" * 78)
print("SUMMARY")
print("=" * 78)
by_criterion = {}
for criterion, _, _, ok in results:
    by_criterion.setdefault(criterion, []).append(ok)
for criterion in ["AC-1", "AC-2", "AC-3", "AC-4", "AC-5", "AC-6", "AC-7", "AC-8"]:
    checks = by_criterion.get(criterion, [])
    verdict = "PASS" if checks and all(checks) else ("FAIL" if checks else "NOT RUN")
    print(f"  {criterion}  {verdict}   ({sum(checks)}/{len(checks)} checks)")
print()
print(f"{len(results)} checks total")
print("ALL EIGHT PASS" if not failures else "FAILURES: " + ", ".join(failures))
print("=" * 78)
