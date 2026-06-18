"""Tests for the account web views (login-required gating + profile edit)."""

from django.test import TestCase

from pykeg.core import defaults, models

LOGIN_REQUIRED_PAGES = [
    "/account/",
    "/account/profile/",
    "/account/notifications/",
]


class AccountAccessTestCase(TestCase):
    def setUp(self):
        defaults.set_defaults(set_is_setup=True, create_controller=True)

    def test_anonymous_is_redirected_to_login(self):
        self.client.logout()
        for path in LOGIN_REQUIRED_PAGES:
            response = self.client.get(path)
            self.assertIn(
                response.status_code,
                (302, 301),
                msg="expected redirect for anonymous GET %s, got %s"
                % (path, response.status_code),
            )

    def test_logged_in_user_can_load_account_pages(self):
        models.User.create_new_user("alice", "alice@example.com", password="1234")
        self.assertTrue(self.client.login(username="alice", password="1234"))
        for path in LOGIN_REQUIRED_PAGES:
            response = self.client.get(path)
            self.assertEqual(
                200,
                response.status_code,
                msg="GET %s returned %s" % (path, response.status_code),
            )

    def test_edit_profile_updates_display_name(self):
        models.User.create_new_user("bob", "bob@example.com", password="1234")
        self.client.login(username="bob", password="1234")

        response = self.client.post(
            "/account/profile/", data={"display_name": "Bobby"}
        )
        self.assertEqual(200, response.status_code)
        user = models.User.objects.get(username="bob")
        self.assertEqual("Bobby", user.display_name)
