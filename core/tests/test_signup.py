"""Self-signup (FR-01, AC-1, ADR-012).

The test that matters is not "signup works". It is that **signup cannot mint an approver**.
A visitor who could grant themselves approval rights would defeat the premise of a product
built to stop reps approving their own discounts.
"""

from django.test import Client, TestCase

from core.models import Role, User


class SignupTests(TestCase):
    URL = "/signup/"

    def setUp(self):
        self.client = Client(SERVER_NAME="localhost")
        self.valid = {
            "email": "new.rep@dealflow.test",
            "name": "New Rep",
            "password1": "a-strong-passphrase-42",
            "password2": "a-strong-passphrase-42",
        }

    def test_the_page_renders_and_says_what_it_creates(self):
        body = self.client.get(self.URL).content.decode()
        self.assertIn("Create an account", body)
        self.assertIn("Sales Rep", body)

    def test_the_form_has_no_role_field_at_all(self):
        body = self.client.get(self.URL).content.decode()
        self.assertNotIn('name="role"', body)
        self.assertNotIn("id_role", body)

    def test_a_valid_signup_creates_a_rep_and_signs_them_in(self):
        response = self.client.post(self.URL, self.valid)
        user = User.objects.get(email="new.rep@dealflow.test")
        self.assertEqual(302, response.status_code)
        self.assertEqual(Role.REP, user.role)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertTrue(user.check_password("a-strong-passphrase-42"))

    # ------------------------------------------------------------ the important one

    def test_a_crafted_request_asking_for_MANAGER_still_creates_a_REP(self):
        """ADR-012. `role` is not in Meta.fields, so there is nothing for it to bind to."""
        self.client.post(self.URL, {**self.valid, "role": Role.MANAGER})
        user = User.objects.get(email="new.rep@dealflow.test")
        self.assertEqual(Role.REP, user.role)

    def test_a_crafted_request_cannot_mint_any_privileged_role(self):
        for attempted in (Role.MANAGER, Role.FINANCE, Role.ADMIN):
            with self.subTest(attempted=attempted):
                User.objects.filter(email="new.rep@dealflow.test").delete()
                self.client.post(self.URL, {**self.valid, "role": attempted})
                user = User.objects.get(email="new.rep@dealflow.test")
                self.assertEqual(Role.REP, user.role)

    def test_a_crafted_request_cannot_set_is_staff_or_is_superuser(self):
        self.client.post(
            self.URL,
            {**self.valid, "is_staff": "on", "is_superuser": "on", "role": Role.ADMIN},
        )
        user = User.objects.get(email="new.rep@dealflow.test")
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertEqual(Role.REP, user.role)

    def test_a_fresh_signup_is_refused_by_the_approvals_screen(self):
        """End to end: the role check the rest of the app relies on still holds."""
        self.client.post(self.URL, {**self.valid, "role": Role.MANAGER})
        self.assertEqual(403, self.client.get("/workspace/approvals/").status_code)

    def test_a_fresh_signup_can_reach_the_workspace(self):
        self.client.post(self.URL, self.valid)
        self.assertEqual(200, self.client.get("/workspace/").status_code)

    # ------------------------------------------------------------ validation

    def test_a_duplicate_email_is_refused_with_a_visible_message(self):
        User.objects.create_user(
            email="new.rep@dealflow.test", password="x", name="Existing", role=Role.REP
        )
        response = self.client.post(self.URL, self.valid)
        self.assertEqual(200, response.status_code)
        self.assertIn("already exists", response.content.decode())
        self.assertEqual(1, User.objects.filter(email="new.rep@dealflow.test").count())

    def test_mismatched_passwords_are_refused_with_a_visible_message(self):
        response = self.client.post(
            self.URL, {**self.valid, "password2": "something-else-entirely"}
        )
        self.assertEqual(200, response.status_code)
        self.assertIn("didn", response.content.decode().lower())
        self.assertFalse(User.objects.filter(email="new.rep@dealflow.test").exists())

    def test_a_weak_password_is_refused(self):
        response = self.client.post(
            self.URL, {**self.valid, "password1": "abc", "password2": "abc"}
        )
        self.assertEqual(200, response.status_code)
        self.assertFalse(User.objects.filter(email="new.rep@dealflow.test").exists())

    def test_an_empty_form_shows_field_errors_rather_than_a_500(self):
        response = self.client.post(self.URL, {})
        self.assertEqual(200, response.status_code)
        self.assertIn("required", response.content.decode().lower())

    def test_email_is_normalised_to_lower_case(self):
        self.client.post(self.URL, {**self.valid, "email": "New.Rep@DealFlow.Test"})
        self.assertTrue(User.objects.filter(email="new.rep@dealflow.test").exists())

    def test_an_authenticated_user_is_sent_to_the_workspace(self):
        User.objects.create_user(
            email="someone@dealflow.test", password="pw12345678", name="X", role=Role.REP
        )
        self.client.login(email="someone@dealflow.test", password="pw12345678")
        response = self.client.get(self.URL)
        self.assertEqual(302, response.status_code)
        self.assertIn("/workspace/", response.headers["Location"])
