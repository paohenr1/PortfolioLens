"""Exercise actual session, CSRF, redirects, and ownership behavior."""

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, SimpleTestCase, TestCase
from django.urls import reverse

from accounts.limits import AttemptBudget, attempt_budget

PASSWORD = "fixture-only-sapphire-river-82"
NEW_PASSWORD = "fixture-only-garden-sunrise-91"


class AuthenticationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = get_user_model().objects.create_user("alice", password=PASSWORD)
        cls.bob = get_user_model().objects.create_user("bob", password=PASSWORD)
        cls.inactive = get_user_model().objects.create_user(
            "inactive", password=PASSWORD, is_active=False
        )

    def setUp(self):
        attempt_budget.reset()
        self.addCleanup(attempt_budget.reset)

    def sign_in(self, client=None, **extra):
        return (client or self.client).post(
            reverse("sign_in"), {"username": "alice", "password": PASSWORD, **extra}
        )

    def test_forms_are_public_without_provider_calls(self):
        with patch("market_data.intrinio.IntrinioClient", side_effect=AssertionError):
            for name in ("sign_in", "register"):
                with self.subTest(name=name):
                    response = self.client.get(reverse(name))
                    self.assertEqual(response.status_code, 200)
                    self.assertContains(response, 'name="csrfmiddlewaretoken"')
                    self.assertIn("no-store", response.headers["Cache-Control"])

    def test_private_routes_require_login(self):
        for name in ("account", "password_change", "password_change_done"):
            with self.subTest(name=name):
                url = reverse(name)
                response = self.client.get(url)
                self.assertRedirects(response, f"/sign-in/?next={url}")
                self.assertIn("no-store", response.headers["Cache-Control"])

    def test_registration_hashes_password_and_signs_in(self):
        response = self.client.post(
            "/register/?next=https://outside.example",
            {"username": "new-researcher", "password1": PASSWORD, "password2": PASSWORD},
        )
        self.assertRedirects(response, reverse("account"))
        user = get_user_model().objects.get(username="new-researcher")
        self.assertTrue(user.check_password(PASSWORD))
        self.assertNotEqual(user.password, PASSWORD)
        self.assertEqual(user.email, "")
        self.assertEqual(self.client.session["_auth_user_id"], str(user.pk))

    def test_bad_registration_does_not_create_user_or_echo_password(self):
        cases = [
            ("new", "12345678", "12345678"),
            ("new", "short", "short"),
            ("new", PASSWORD, "different"),
            ("alice", PASSWORD, PASSWORD),
            ("invalid user!", PASSWORD, PASSWORD),
        ]
        for username, first, second in cases:
            with self.subTest(username=username, first=first):
                response = self.client.post(
                    reverse("register"),
                    {"username": username, "password1": first, "password2": second},
                )
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["form"].errors)
                self.assertNotContains(response, f'value="{first}"')
                self.assertEqual(get_user_model().objects.count(), 3)
                self.assertNotIn("_auth_user_id", self.client.session)

    def test_signed_in_registration_does_not_create_another_user(self):
        self.client.force_login(self.alice)
        response = self.client.post(
            reverse("register"),
            {"username": "extra", "password1": PASSWORD, "password2": PASSWORD},
        )
        self.assertRedirects(response, reverse("account"))
        self.assertEqual(get_user_model().objects.count(), 3)
        self.assertIn("no-store", response.headers["Cache-Control"])

    def test_login_rotates_anonymous_session_and_uses_default_destination(self):
        session = self.client.session
        session["anonymous_marker"] = "kept"
        session.save()
        old_key = session.session_key
        self.assertRedirects(self.sign_in(), reverse("account"))
        self.assertNotEqual(self.client.session.session_key, old_key)
        self.assertEqual(self.client.session["anonymous_marker"], "kept")
        self.assertEqual(self.client.session["_auth_user_id"], str(self.alice.pk))

    def test_login_accepts_local_next(self):
        self.assertRedirects(self.sign_in(next="/account/?tab=security"), "/account/?tab=security")

    def test_login_rejects_unsafe_return_destinations(self):
        for target in (
            "https://outside.example/account/",
            "//outside.example/",
            "///outside.example/",
            "\\\\outside.example/",
            "javascript:alert(1)",
            "http:///outside.example/",
        ):
            with self.subTest(target=target):
                self.assertRedirects(self.sign_in(next=target), reverse("account"))

    def test_https_login_rejects_http_return_destination(self):
        response = self.client.post(
            reverse("sign_in"),
            {"username": "alice", "password": PASSWORD, "next": "http://testserver/account/"},
            secure=True,
        )
        self.assertRedirects(response, reverse("account"))

    def test_failed_login_is_generic_and_does_not_echo_password(self):
        errors = []
        for username in ("alice", "unknown", "inactive"):
            response = self.client.post(
                reverse("sign_in"), {"username": username, "password": "bad-credentials"}
            )
            self.assertEqual(response.status_code, 200)
            errors.append(str(response.context["form"].non_field_errors()))
            self.assertNotContains(response, 'value="bad-credentials"')
            self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(len(set(errors)), 1)

    def test_inactive_account_cannot_sign_in_with_valid_password(self):
        response = self.client.post(
            reverse("sign_in"), {"username": "inactive", "password": PASSWORD}
        )
        self.assertTrue(response.context["form"].errors)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_deactivated_user_loses_private_access_on_next_request(self):
        self.sign_in()
        self.alice.is_active = False
        self.alice.save(update_fields=["is_active"])
        self.assertRedirects(self.client.get(reverse("account")), "/sign-in/?next=/account/")

    def test_authentication_posts_are_marked_sensitive_for_error_reports(self):
        for name in ("sign_in", "register"):
            with self.subTest(name=name):
                response = self.client.post(reverse(name), {"username": "missing"})
                self.assertEqual(response.wsgi_request.sensitive_post_parameters, "__ALL__")
        self.client.force_login(self.alice)
        response = self.client.post(reverse("password_change"))
        self.assertEqual(response.wsgi_request.sensitive_post_parameters, "__ALL__")

    def test_account_is_current_user_only_and_private(self):
        for owner, stranger in ((self.alice, self.bob), (self.bob, self.alice)):
            with self.subTest(owner=owner.username):
                self.client.force_login(owner)
                response = self.client.get(
                    reverse("account"), {"user_id": stranger.pk, "username": stranger.username}
                )
                self.assertEqual(response.context["account_user"], owner)
                self.assertContains(response, f"<strong>{owner.username}</strong>")
                self.assertNotContains(response, f"<strong>{stranger.username}</strong>")
                self.assertIn("no-store", response.headers["Cache-Control"])

    def test_account_rejects_mutation_methods(self):
        self.client.force_login(self.alice)
        self.assertEqual(self.client.post(reverse("account")).status_code, 405)

    def test_logout_requires_post_flushes_session_and_has_fixed_destination(self):
        self.sign_in()
        self.assertEqual(self.client.get(reverse("sign_out")).status_code, 405)
        self.assertIn("_auth_user_id", self.client.session)
        response = self.client.post(reverse("sign_out"), {"next": "https://outside.example/"})
        self.assertRedirects(response, reverse("home"))
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertRedirects(self.client.get(reverse("account")), "/sign-in/?next=/account/")

    def test_public_research_remains_available_when_signed_out(self):
        self.assertEqual(self.client.get(reverse("home")).status_code, 200)
        self.assertEqual(self.client.get(reverse("search")).status_code, 200)

    def test_authenticated_navigation_uses_post_logout(self):
        self.client.force_login(self.alice)
        response = self.client.get(reverse("home"))
        self.assertContains(response, 'action="/sign-out/" method="post"')
        self.assertContains(response, "My account")

    def test_csrf_blocks_registration_login_logout_and_password_change(self):
        client = Client(enforce_csrf_checks=True)
        for name in ("register", "sign_in", "sign_out", "password_change"):
            with self.subTest(name=name):
                self.assertEqual(client.post(reverse(name)).status_code, 403)
        self.assertEqual(get_user_model().objects.count(), 3)

    def test_valid_csrf_token_allows_login_and_logout(self):
        client = Client(enforce_csrf_checks=True)
        client.get(reverse("sign_in"))
        token = client.cookies["csrftoken"].value
        self.assertRedirects(self.sign_in(client, csrfmiddlewaretoken=token), reverse("account"))
        # Login rotates the CSRF token too: use the new cookie for sign-out.
        token = client.cookies["csrftoken"].value
        self.assertRedirects(
            client.post(reverse("sign_out"), {"csrfmiddlewaretoken": token}), reverse("home")
        )

    def test_password_change_requires_current_password_and_validation(self):
        self.client.force_login(self.alice)
        for old, first, second in (
            ("wrong", NEW_PASSWORD, NEW_PASSWORD),
            (PASSWORD, "12345678", "12345678"),
            (PASSWORD, NEW_PASSWORD, "different"),
        ):
            response = self.client.post(
                reverse("password_change"),
                {"old_password": old, "new_password1": first, "new_password2": second},
            )
            self.assertTrue(response.context["form"].errors)
            self.assertNotContains(response, f'value="{old}"')
            self.alice.refresh_from_db()
            self.assertTrue(self.alice.check_password(PASSWORD))

    def test_password_change_keeps_current_session_and_invalidates_other_sessions(self):
        other = Client()
        self.sign_in(other)
        self.sign_in()
        response = self.client.post(
            reverse("password_change"),
            {
                "old_password": PASSWORD,
                "new_password1": NEW_PASSWORD,
                "new_password2": NEW_PASSWORD,
            },
        )
        self.assertRedirects(response, reverse("password_change_done"))
        self.assertEqual(self.client.get(reverse("account")).status_code, 200)
        self.assertRedirects(other.get(reverse("account")), "/sign-in/?next=/account/")
        self.alice.refresh_from_db()
        self.assertTrue(self.alice.check_password(NEW_PASSWORD))
        self.assertFalse(self.alice.check_password(PASSWORD))
        self.bob.refresh_from_db()
        self.assertTrue(self.bob.check_password(PASSWORD))

    def test_logout_cookie_is_httponly_and_session_has_idle_expiry(self):
        self.sign_in()
        cookie = self.client.cookies["sessionid"]
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "Lax")
        self.assertEqual(cookie["max-age"], 8 * 60 * 60)
        self.assertEqual(self.client.session.get_expiry_age(), 8 * 60 * 60)

    @patch("accounts.limits.time.monotonic", return_value=65)
    def test_attempt_limit_is_shared_across_login_and_registration(self, _clock):
        for _ in range(10):
            self.client.post(reverse("sign_in"), {"username": "missing", "password": "bad"})
        response = self.client.post(
            reverse("register"),
            {"username": "extra", "password1": PASSWORD, "password2": PASSWORD},
            HTTP_X_FORWARDED_FOR="198.51.100.1",
        )
        self.assertEqual(response.status_code, 429)
        self.assertIn(int(response.headers["Retry-After"]), range(1, 61))
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertEqual(get_user_model().objects.count(), 3)
        self.assertEqual(self.client.get(reverse("sign_in")).status_code, 200)

    @patch("accounts.limits.time.monotonic", return_value=65)
    def test_throttled_password_change_cannot_mutate_credentials(self, _clock):
        self.client.force_login(self.alice)
        for _ in range(10):
            attempt_budget.reserve("127.0.0.1")
        response = self.client.post(
            reverse("password_change"),
            {
                "old_password": PASSWORD,
                "new_password1": NEW_PASSWORD,
                "new_password2": NEW_PASSWORD,
            },
        )
        self.assertEqual(response.status_code, 429)
        self.alice.refresh_from_db()
        self.assertTrue(self.alice.check_password(PASSWORD))


class AttemptBudgetTests(SimpleTestCase):
    def test_concurrent_attempts_obey_client_and_global_limits(self):
        for addresses, allowed in ((["one"] * 100, 10), ([str(n) for n in range(100)], 60)):
            with self.subTest(allowed=allowed):
                budget = AttemptBudget()
                with patch("accounts.limits.time.monotonic", return_value=65):
                    with ThreadPoolExecutor(max_workers=8) as executor:
                        results = list(executor.map(budget.reserve, addresses))
                self.assertEqual(sum(result is None for result in results), allowed)

    def test_fixed_window_recovers_and_limits_clients_without_account_lockout(self):
        budget = AttemptBudget()
        with patch("accounts.limits.time.monotonic", return_value=65):
            for _ in range(10):
                self.assertIsNone(budget.reserve("one"))
            self.assertEqual(budget.reserve("one"), 55)
            self.assertIsNone(budget.reserve("two"))
        with patch("accounts.limits.time.monotonic", return_value=120):
            self.assertIsNone(budget.reserve("one"))

    def test_global_limit_bounds_memory_without_eviction(self):
        budget = AttemptBudget()
        with patch("accounts.limits.time.monotonic", return_value=0):
            for number in range(60):
                self.assertIsNone(budget.reserve(f"address-{number}"))
            for number in range(60, 160):
                self.assertEqual(budget.reserve(f"address-{number}"), 60)
        self.assertEqual(len(budget._clients), 60)
        self.assertNotIn("address-0", budget._clients)
