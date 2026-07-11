"""Unittests for pykeg.core.models"""

import datetime
import os

from django.core.files import File
from django.test import TransactionTestCase

from pykeg.core.testutils import get_filename
from pykeg.util import units

from . import kb_common, keg_sizes, models
from .testutils import make_datetime


class CoreModelsTestCase(TransactionTestCase):
    def setUp(self):
        models.KegbotSite.get()  # create the site
        self.producer = models.BeverageProducer.objects.create(
            name="Moonshine Beers",
            country="USA",
            origin_state="Anystate",
            origin_city="Bathtub",
            url="http://example.com/",
            description="Pretty bad beers.",
        )

        self.beverage = models.Beverage.objects.create(
            name="Moonshine Porter",
            producer=self.producer,
            style="Porter",
            calories_per_ml=3.0,
            carbs_per_ml=10.0,
            abv_percent=0.05,
        )

        self.keg = models.Keg.objects.create(
            type=self.beverage,
            keg_type="other",
            start_time=make_datetime(2000, 4, 1),
            end_time=make_datetime(2000, 5, 1),
            description="Our first keg!",
            full_volume_ml=2000,
        )

        self.tap = models.KegTap.objects.create(
            name="Test Tap",
            current_keg=self.keg,
        )

        self.controller = models.Controller.objects.create(name="kegboard")

        self.meter = models.FlowMeter.objects.create(
            controller=self.controller, port_name="flow0", ticks_per_ml=2.2, tap=self.tap
        )

        self.user = models.User.objects.create(
            username="kb_tester",
        )

        self.user2 = models.User.objects.create(
            username="kb_tester2",
        )

    def testKegStuff(self):
        """Test basic keg relations that should always work."""
        self.assertEqual(
            self.keg.full_volume_ml, units.Quantity(2.0, units.UNITS.Liter).InMilliliters()
        )
        self.assertEqual(self.keg.type.producer.name, "Moonshine Beers")

        self.assertEqual(0.0, self.keg.served_volume())
        self.assertEqual(2000, self.keg.remaining_volume_ml())

    def testDrinkAccounting(self):
        d = models.Drink.record_drink(
            self.tap,
            ticks=1200,
            username=self.user.username,
        )
        self.assertEqual(d.keg.served_volume(), d.volume_ml)

    def testDrinkSessions(self):
        """Checks for the DrinkingSession records."""
        u1 = self.user
        u2 = self.user2
        units.Quantity(1200)

        base_time = make_datetime(2009, 1, 1, 1, 0, 0)

        td_10m = datetime.timedelta(minutes=10)
        td_400m = datetime.timedelta(minutes=400)
        td_390m = td_400m - td_10m

        self.assertEqual(models.Drink.objects.all().count(), 0)
        self.assertEqual(models.DrinkingSession.objects.all().count(), 0)

        # u=1 t=0
        models.Drink.record_drink(
            self.tap,
            ticks=1200,
            username=u1.username,
            pour_time=base_time,
        )
        # u=2 t=0
        models.Drink.record_drink(
            self.tap,
            ticks=1200,
            username=u2.username,
            pour_time=base_time,
        )

        # u=1 t=10
        models.Drink.record_drink(
            self.tap,
            ticks=1200,
            username=u1.username,
            pour_time=base_time + td_10m,
        )

        # u=1 t=400
        models.Drink.record_drink(
            self.tap,
            ticks=1200,
            username=u1.username,
            pour_time=base_time + td_400m,
        )

        # u=2 t=490
        models.Drink.record_drink(
            self.tap,
            ticks=1200,
            username=u2.username,
            pour_time=base_time + td_390m,
        )

        # u=2 t=400
        models.Drink.record_drink(
            self.tap,
            ticks=1200,
            username=u2.username,
            pour_time=base_time + td_400m,
        )

        drinks_u1 = u1.drinks.all().order_by("time")

        s1, s2 = models.DrinkingSession.objects.all().order_by("start_time")[:2]

        SESSION_DELTA = datetime.timedelta(minutes=kb_common.DRINK_SESSION_TIME_MINUTES)

        # session 1: should be 10 minutes long as created above
        self.assertEqual(s1.start_time, drinks_u1[0].time)
        self.assertEqual(s1.end_time, drinks_u1[0].time + td_10m + SESSION_DELTA)
        self.assertEqual(s1.drinks.all().filter(user=u1).count(), 2)
        self.assertEqual(s1.drinks.all().filter(user=u2).count(), 1)

        # session 2: at time 200, 1 drink
        self.assertEqual(s2.start_time, base_time + td_390m)
        self.assertEqual(s2.end_time, base_time + td_400m + SESSION_DELTA)
        self.assertEqual(s2.drinks.all().filter(user=u1).count(), 1)
        self.assertEqual(s2.drinks.all().filter(user=u2).count(), 2)

        # Now check DrinkingSessions were created correctly; there should be
        # two groups capturing all 4 sessions.
        all_groups = models.DrinkingSession.objects.all().order_by("start_time")
        self.assertEqual(len(all_groups), 2)

        self.assertEqual(all_groups[0].start_time, base_time)
        self.assertEqual(all_groups[0].end_time, base_time + td_10m + SESSION_DELTA)

        self.assertEqual(all_groups[1].start_time, base_time + td_390m)
        self.assertEqual(all_groups[1].end_time, base_time + td_400m + SESSION_DELTA)

        self.assertEqual("kb_tester2 and kb_tester", s2.summarize_drinkers())

    def test_pic_filename(self):
        basename = "1/2/3-4567 89.jpg"
        now = datetime.datetime(2011, 0o2, 0o3)
        uuid_str = "abcdef"
        uploaded_name = models._pics_file_name(None, basename, now, uuid_str)
        self.assertEqual("pics/20110203000000-abcdef.jpg", uploaded_name)

    def test_site_can_invite(self):
        site = models.KegbotSite.get()
        self.assertFalse(site.can_invite(None))

        site.registration_mode = "public"
        site.save()
        self.assertTrue(site.can_invite(self.user))

        site.registration_mode = "member-invite-only"
        site.save()
        self.assertTrue(site.can_invite(self.user))

        site.registration_mode = "staff-invite-only"
        site.save()
        self.assertFalse(site.can_invite(self.user))

        self.user.is_staff = True
        self.user.save()
        site.registration_mode = "staff-invite-only"
        site.save()
        self.assertTrue(site.can_invite(self.user))

    def test_photos(self):
        with open(get_filename("test_image_800x600.png"), "rb") as fh:
            picture_obj = models.Picture.objects.create(image=File(fh))

        paths = []
        for spec in ("resized", "resized_png", "thumbnail", "thumbnail_png", "image"):
            img = getattr(picture_obj, spec)
            path = img.path
            self.assertTrue(os.path.exists(path))
            paths.append(path)

        picture_obj.erase_and_delete()
        for path in paths:
            self.assertFalse(os.path.exists(path))


class KegLevelStatusTestCase(TransactionTestCase):
    """Tests for Keg.level_status() tier thresholds (pints OR percent)."""

    HALF_BARREL_ML = keg_sizes.VOLUMES_ML[keg_sizes.HALF_BARREL]
    SIXTH_BARREL_ML = keg_sizes.VOLUMES_ML[keg_sizes.SIXTH_BARREL]
    PINT_ML = units.UNITS.Pint.value

    def keg_with_remaining(self, full_volume_ml, remaining_ml):
        return models.Keg(
            full_volume_ml=full_volume_ml,
            served_volume_ml=full_volume_ml - remaining_ml,
        )

    def test_fresh_keg_is_none(self):
        keg = self.keg_with_remaining(self.HALF_BARREL_ML, self.HALF_BARREL_ML)
        self.assertIsNone(keg.level_status())

    def test_half_full_keg_is_none(self):
        keg = self.keg_with_remaining(self.HALF_BARREL_ML, self.HALF_BARREL_ML / 2)
        self.assertIsNone(keg.level_status())

    def test_low_via_percent_before_pints_on_large_keg(self):
        # 12 pints left in a half barrel is ~9.7% full: over the 10-pint
        # floor but under the 15% floor.
        keg = self.keg_with_remaining(self.HALF_BARREL_ML, 12 * self.PINT_ML)
        self.assertEqual("low", keg.level_status())

    def test_low_via_pints_before_percent_on_small_keg(self):
        # 8 pints left in a sixth barrel is ~19% full: over the 15% floor
        # but under the 10-pint floor.
        keg = self.keg_with_remaining(self.SIXTH_BARREL_ML, 8 * self.PINT_ML)
        self.assertEqual("low", keg.level_status())

    def test_critical_via_percent_on_large_keg(self):
        # 5 pints left in a half barrel is ~4% full: over the 4-pint floor
        # but under the 5% floor.
        keg = self.keg_with_remaining(self.HALF_BARREL_ML, 5 * self.PINT_ML)
        self.assertEqual("critical", keg.level_status())

    def test_critical_via_pints_on_small_keg(self):
        # 3 pints left in a sixth barrel is ~7% full: over the 5% floor but
        # under the 4-pint floor.
        keg = self.keg_with_remaining(self.SIXTH_BARREL_ML, 3 * self.PINT_ML)
        self.assertEqual("critical", keg.level_status())

    def test_tiers_trigger_just_below_pint_floors(self):
        keg = self.keg_with_remaining(self.SIXTH_BARREL_ML, 9.99 * self.PINT_ML)
        self.assertEqual("low", keg.level_status())
        keg = self.keg_with_remaining(self.SIXTH_BARREL_ML, 3.99 * self.PINT_ML)
        self.assertEqual("critical", keg.level_status())

    def test_empty_keg_is_critical(self):
        keg = self.keg_with_remaining(self.HALF_BARREL_ML, 0)
        self.assertEqual("critical", keg.level_status())

    def test_zero_full_volume_uses_pints_only(self):
        # percent_full() returns 0 for a zero-size keg; only the pints
        # floors should apply (here: nothing left → critical, no crash).
        keg = self.keg_with_remaining(0, 0)
        self.assertEqual("critical", keg.level_status())

    def test_thresholds_are_site_configurable(self):
        # 15 pints in a sixth barrel (~36% full) is fine at the defaults.
        keg = self.keg_with_remaining(self.SIXTH_BARREL_ML, 15 * self.PINT_ML)
        self.assertIsNone(keg.level_status())

        site = models.KegbotSite.get()
        site.keg_indicator_low_pints = 20
        site.save()
        self.assertEqual("low", keg.level_status())

        site.keg_indicator_critical_pints = 18
        site.save()
        self.assertEqual("critical", keg.level_status())

    def test_explicit_site_overrides_db_settings(self):
        keg = self.keg_with_remaining(self.SIXTH_BARREL_ML, 15 * self.PINT_ML)
        site = models.KegbotSite.get()
        site.keg_indicator_low_pints = 20  # not saved
        self.assertEqual("low", keg.level_status(site=site))
        self.assertIsNone(keg.level_status())
