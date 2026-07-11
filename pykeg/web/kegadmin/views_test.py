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


class KegadminGeneralSettingsTestCase(TestCase):
    def setUp(self):
        defaults.set_defaults(set_is_setup=True, create_controller=True)
        user = models.User.objects.create(username="admin", is_staff=True)
        user.set_password("testpass")
        user.save()
        self.client.login(username="admin", password="testpass")

    def _post_settings(self, **overrides):
        data = {
            "title": "My Kegbot",
            "enable_sensing": "on",
            "enable_users": "on",
            "privacy": "public",
            "registration_mode": "public",
            "keg_indicator_low_pints": 12,
            "keg_indicator_low_percent": 20,
            "keg_indicator_critical_pints": 3,
            "keg_indicator_critical_percent": 4,
        }
        data.update(overrides)
        return self.client.post("/kegadmin/settings/general/", data=data, follow=True)

    def test_saves_keg_indicator_thresholds(self):
        response = self._post_settings()
        self.assertEqual(200, response.status_code)
        self.assertContains(response, "Settings were updated.")

        site = models.KegbotSite.get()
        self.assertEqual(12, site.keg_indicator_low_pints)
        self.assertEqual(20, site.keg_indicator_low_percent)
        self.assertEqual(3, site.keg_indicator_critical_pints)
        self.assertEqual(4, site.keg_indicator_critical_percent)

    def test_rejects_critical_above_low(self):
        response = self._post_settings(keg_indicator_critical_pints=15)
        self.assertContains(
            response, "Critical pints threshold must not exceed the low pints threshold."
        )
        self.assertEqual(10, models.KegbotSite.get().keg_indicator_low_pints)

        response = self._post_settings(keg_indicator_critical_percent=25)
        self.assertContains(
            response,
            "Critical percent threshold must not exceed the low percent threshold.",
        )
        self.assertEqual(15, models.KegbotSite.get().keg_indicator_low_percent)

    def test_rejects_percent_above_100(self):
        response = self._post_settings(keg_indicator_low_percent=101)
        self.assertEqual(200, response.status_code)
        self.assertEqual(15, models.KegbotSite.get().keg_indicator_low_percent)
