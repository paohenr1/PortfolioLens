from django.contrib.auth import authenticate, get_user_model
from django.test import TestCase


class UserModelTests(TestCase):
    def test_custom_user_persists_a_hashed_password_and_authenticates(self):
        user_model = get_user_model()
        password = "test-only-user-password-42"
        user = user_model.objects.create_user(username="researcher", password=password)
        user.refresh_from_db()
        self.assertEqual(user._meta.label, "accounts.User")
        self.assertNotEqual(user.password, password)
        self.assertTrue(user.check_password(password))
        self.assertEqual(authenticate(username="researcher", password=password), user)
        self.assertIsNone(authenticate(username="researcher", password="incorrect-test-password"))
