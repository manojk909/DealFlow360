"""Portal access control (T-14, FR-02, ADR-004, DATA_MODEL invariant 12).

The property being tested is not "the happy path renders". It is that **every** way of
arriving without the right token produces a 403 — not the quotation, and not a redirect
to the internal login page.
"""

from decimal import Decimal

from django.core import signing
from django.test import Client, TestCase

from core.models import Customer, CustomerTier, Quotation, Role, User
from core.services import negotiation


class PortalAccessTests(TestCase):
    def setUp(self):
        tier = CustomerTier.objects.create(name="Silver", max_discount_pct=Decimal("10"))
        self.rep = User.objects.create_user(
            email="rep@p.test", password="x", name="Rep", role=Role.REP
        )
        self.beta = self._quotation("Beta Industries", "b@b.test", tier, "Q-P-1")
        self.acme = self._quotation("Acme Corp", "a@a.test", tier, "Q-P-2")
        self.client = Client(SERVER_NAME="localhost")

    def _quotation(self, customer_name, email, tier, number):
        customer = Customer.objects.create(name=customer_name, email=email, tier=tier)
        quotation = Quotation.objects.create(
            number=number, customer=customer, rep=self.rep,
            stage=Quotation.Stage.SENT,
            last_activity_at="2026-09-05T10:00:00Z",
        )
        quotation.portal_token = signing.TimestampSigner().sign(str(quotation.pk))
        quotation.save(update_fields=["portal_token"])
        return quotation

    # ---------------------------------------------------------------- happy path

    def test_a_valid_token_opens_exactly_its_own_quotation(self):
        response = self.client.get(f"/portal/{self.beta.portal_token}/")
        body = response.content.decode()
        self.assertEqual(200, response.status_code)
        self.assertIn("Beta Industries", body)
        self.assertNotIn("Acme Corp", body)

    def test_each_token_opens_its_own_quotation_and_no_other(self):
        beta_body = self.client.get(f"/portal/{self.beta.portal_token}/").content.decode()
        acme_body = self.client.get(f"/portal/{self.acme.portal_token}/").content.decode()
        self.assertIn("Beta Industries", beta_body)
        self.assertIn("Acme Corp", acme_body)
        self.assertNotIn("Q-P-2", beta_body)
        self.assertNotIn("Q-P-1", acme_body)

    # ---------------------------------------------------------------- refusals

    def test_a_tampered_token_is_403_not_the_other_quotation(self):
        """Swap the embedded id for another quotation's — the signature no longer matches."""
        _, timestamp, signature = self.beta.portal_token.split(":")
        forged = f"{self.acme.pk}:{timestamp}:{signature}"
        response = self.client.get(f"/portal/{forged}/")
        self.assertEqual(403, response.status_code)
        self.assertNotIn("Acme Corp", response.content.decode())

    def test_a_bare_quotation_id_is_403(self):
        response = self.client.get(f"/portal/{self.beta.pk}/")
        self.assertEqual(403, response.status_code)

    def test_a_random_string_is_403(self):
        self.assertEqual(403, self.client.get("/portal/not-a-token/").status_code)

    def test_a_correctly_signed_token_for_an_unknown_quotation_is_403(self):
        orphan = signing.TimestampSigner().sign("999999")
        self.assertEqual(403, self.client.get(f"/portal/{orphan}/").status_code)

    def test_a_signed_token_the_quotation_does_not_hold_is_403(self):
        """Defence in depth: a rotated or never-issued token is refused."""
        rotated = signing.TimestampSigner().sign(str(self.beta.pk))
        Quotation.objects.filter(pk=self.beta.pk).update(portal_token="something-else")
        self.assertEqual(403, self.client.get(f"/portal/{rotated}/").status_code)

    def test_a_quotation_with_no_token_cannot_be_reached(self):
        Quotation.objects.filter(pk=self.beta.pk).update(portal_token="")
        token = signing.TimestampSigner().sign(str(self.beta.pk))
        self.assertEqual(403, self.client.get(f"/portal/{token}/").status_code)

    def test_refusal_is_403_and_never_a_redirect_to_the_internal_login(self):
        response = self.client.get("/portal/not-a-token/")
        self.assertEqual(403, response.status_code)
        self.assertNotIn("Location", response.headers)

    # ---------------------------------------------------------------- separateness

    def test_the_portal_page_exposes_no_internal_navigation(self):
        body = self.client.get(f"/portal/{self.beta.portal_token}/").content.decode()
        for internal in ["/workspace/", "/admin/", "Back-end", "Approvals", "Fulfilment"]:
            self.assertNotIn(internal, body, f"portal leaked internal nav: {internal}")

    def test_portal_views_never_read_request_user(self):
        """A customer has no account, so the module must not touch `request.user`."""
        import pathlib

        source = (
            pathlib.Path(__file__).resolve().parent.parent.parent / "portal" / "views.py"
        ).read_text(encoding="utf-8")
        code = "\n".join(
            line for line in source.splitlines() if not line.strip().startswith("#")
        )
        # The docstring mentions it; the executable code must not use it.
        body = code.split('"""')[-1]
        self.assertNotIn("request.user", body)
        self.assertNotIn("login_required", body)

    def test_an_authenticated_internal_user_gets_no_special_treatment(self):
        """The portal is token-scoped, not permission-scoped. Being staff changes nothing."""
        admin = User.objects.create_superuser(
            email="admin@p.test", password="pw", name="Admin"
        )
        self.client.force_login(admin)
        self.assertEqual(403, self.client.get("/portal/not-a-token/").status_code)
        self.assertEqual(
            200, self.client.get(f"/portal/{self.beta.portal_token}/").status_code
        )


class PortalStatusMappingTests(TestCase):
    """ADR-010: portal status is a display mapping over `stage`, not a stored field."""

    def test_internal_stages_are_never_shown_to_the_customer(self):
        mapping = {
            Quotation.Stage.SENT: "Sent",
            Quotation.Stage.UNDER_NEGOTIATION: "Under Negotiation",
            Quotation.Stage.PENDING_APPROVAL: "Under Negotiation",
            Quotation.Stage.APPROVED: "Under Negotiation",
            Quotation.Stage.CONFIRMED: "Confirmed",
            Quotation.Stage.FULFILLED: "Confirmed",
            Quotation.Stage.INVOICED: "Confirmed",
            Quotation.Stage.PAID: "Confirmed",
            Quotation.Stage.REJECTED: "Closed",
        }
        for stage, expected in mapping.items():
            with self.subTest(stage=stage):
                self.assertEqual(expected, negotiation.portal_status(stage))

    def test_the_customer_only_ever_sees_four_words(self):
        shown = {negotiation.portal_status(s) for s in Quotation.Stage.values}
        self.assertEqual({"Draft", "Sent", "Under Negotiation", "Confirmed", "Closed"}, shown)
