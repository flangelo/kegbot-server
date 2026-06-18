"""Tests for the kegadmin (staff) web views.

Covers the staff-only access gate (anonymous/non-staff are redirected to login,
staff get a 200) and a representative form round-trip.
"""

from django.test import TestCase

from pykeg.core import defaults, models

# Representative staff-gated GET pages.
ADMIN_PAGES = [
    "/kegadmin/",
    "/kegadmin/settings/general/",
    "/kegadmin/beers/",
    "/kegadmin/kegs/",
    "/kegadmin/taps/",
    "/kegadmin/users/",
    "/kegadmin/controllers/",
    "/kegadmin/drinks/",
    "/kegadmin/brewers/add/",
]


class KegadminAccessTestCase(TestCase):
    def setUp(self):
        defaults.set_defaults(set_is_setup=True, create_controller=True)

    def _make_staff(self):
        user = models.User.objects.create(username="admin", is_staff=True)
        user.set_password("testpass")
        user.save()
        return user

    def test_anonymous_is_redirected_to_login(self):
        self.client.logout()
        for path in ADMIN_PAGES:
            response = self.client.get(path)
            self.assertIn(
                response.status_code,
                (301, 302),
                msg="anonymous GET %s returned %s (expected redirect)"
                % (path, response.status_code),
            )

    def test_non_staff_is_redirected_to_login(self):
        models.User.create_new_user("regular", "regular@example.com", password="1234")
        self.client.login(username="regular", password="1234")
        response = self.client.get("/kegadmin/")
        self.assertIn(response.status_code, (301, 302))

    def test_staff_can_load_admin_pages(self):
        self._make_staff()
        self.assertTrue(self.client.login(username="admin", password="testpass"))
        for path in ADMIN_PAGES:
            response = self.client.get(path)
            self.assertEqual(
                200,
                response.status_code,
                msg="staff GET %s returned %s" % (path, response.status_code),
            )


class KegadminBeverageTestCase(TestCase):
    def setUp(self):
        defaults.set_defaults(set_is_setup=True, create_controller=True)
        user = models.User.objects.create(username="admin", is_staff=True)
        user.set_password("testpass")
        user.save()
        self.client.login(username="admin", password="testpass")

    def test_add_beverage_producer(self):
        response = self.client.post(
            "/kegadmin/brewers/add/",
            data={"name": "Test Brewery", "country": "USA"},
            follow=True,
        )
        self.assertEqual(200, response.status_code)
        self.assertTrue(
            models.BeverageProducer.objects.filter(name="Test Brewery").exists()
        )
