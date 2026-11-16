"""Prayer-time calculator + API tests.

PrayerCalculatorTests are plain unittest (no database) and are checked
against published sunrise/sunset values; the API tests follow the project's
usual DRF style.
"""
import unittest
from datetime import date
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from accounts.models import Profile

from .prayer import PRAYER_ORDER, calculate_prayer_times

NY = ZoneInfo("America/New_York")


def _by_name(times):
    return {t["name"]: t["start"] for t in times}


def _minutes(dt):
    return dt.hour * 60 + dt.minute


class PrayerCalculatorTests(unittest.TestCase):
    def test_new_york_midsummer_matches_published_sun_times(self):
        t = _by_name(calculate_prayer_times(date(2026, 6, 21), 40.7128, -74.0060, NY, method="ISNA"))
        # Published: sunrise 05:25, sunset 20:31 EDT (allow 2 minutes).
        self.assertAlmostEqual(_minutes(t["Sunrise"]), 5 * 60 + 25, delta=2)
        self.assertAlmostEqual(_minutes(t["Maghrib"]), 20 * 60 + 31, delta=2)

    def test_order_is_chronological(self):
        times = calculate_prayer_times(date(2026, 11, 15), 42.6526, -73.7562, NY, method="ISNA")
        # Zawaal sits directly before Maghrib; everything else keeps its order.
        expected = PRAYER_ORDER.copy()
        expected.insert(expected.index("Maghrib"), "Zawaal")
        self.assertEqual([x["name"] for x in times], expected)
        starts = [x["start"] for x in times]
        self.assertEqual(starts, sorted(starts))

    def test_zawaal_is_15_minutes_before_maghrib(self):
        for method in ("MWL", "ISNA", "Makkah"):
            times = calculate_prayer_times(date(2026, 11, 15), 21.42, 39.83, NY, method=method)
            mag = next(t for t in times if t["name"] == "Maghrib")
            zaw = next(t for t in times if t["name"] == "Zawaal")
            self.assertEqual((mag["start"] - zaw["start"]).total_seconds(), 15 * 60)
            self.assertEqual(zaw["end"], mag["start"])
            self.assertEqual(times.index(zaw) + 1, times.index(mag))

    def test_zawaal_omitted_when_maghrib_missing(self):
        # Polar midnight sun: no Sunrise/Maghrib -> no Zawaal either.
        times = calculate_prayer_times(date(2026, 6, 21), 69.65, 18.96, ZoneInfo("Europe/Oslo"))
        self.assertNotIn("Zawaal", [t["name"] for t in times])

    def test_hanafi_asr_is_later_than_standard(self):
        std = _by_name(calculate_prayer_times(date(2026, 11, 15), 42.65, -73.75, NY))
        han = _by_name(calculate_prayer_times(date(2026, 11, 15), 42.65, -73.75, NY, asr_madhab="hanafi"))
        self.assertGreater(han["Asr"], std["Asr"])

    def test_makkah_isha_is_90_minutes_after_maghrib(self):
        t = _by_name(calculate_prayer_times(date(2026, 3, 20), 21.4225, 39.8262, ZoneInfo("Asia/Riyadh"), method="Makkah"))
        self.assertEqual((t["Isha"] - t["Maghrib"]).total_seconds(), 90 * 60)

    def test_offsets_shift_minutes(self):
        base = _by_name(calculate_prayer_times(date(2026, 11, 15), 42.65, -73.75, NY))
        moved = _by_name(calculate_prayer_times(date(2026, 11, 15), 42.65, -73.75, NY, offsets={"fajr": -5, "isha": 10}))
        self.assertEqual((base["Fajr"] - moved["Fajr"]).total_seconds(), 300)
        self.assertEqual((moved["Isha"] - base["Isha"]).total_seconds(), 600)

    def test_local_date_is_correct_far_east_and_west(self):
        # Large positive/negative longitudes used to push UTC hours across midnight.
        for lat, lng, tz in [(-36.85, 174.76, "Pacific/Auckland"), (21.3, -157.86, "Pacific/Honolulu")]:
            for p in calculate_prayer_times(date(2026, 11, 15), lat, lng, ZoneInfo(tz)):
                self.assertEqual(p["start"].date(), date(2026, 11, 15), (tz, p["name"]))

    def test_midnight_sun_omits_instead_of_inventing(self):
        names = [t["name"] for t in calculate_prayer_times(date(2026, 6, 21), 69.65, 18.96, ZoneInfo("Europe/Oslo"))]
        self.assertNotIn("Sunrise", names)
        self.assertIn("Dhuhr", names)

    def test_dst_day_uses_local_offsets(self):
        # 2026-03-08 is the US spring-forward day; Dhuhr must be after 12:00 local, not 11:00.
        t = _by_name(calculate_prayer_times(date(2026, 3, 8), 40.7128, -74.0060, NY))
        self.assertGreaterEqual(t["Dhuhr"].hour, 12)

    def test_bad_input_rejected(self):
        with self.assertRaises(ValueError):
            calculate_prayer_times(date(2026, 1, 1), 0, 0, NY, method="Nope")
        with self.assertRaises(ValueError):
            calculate_prayer_times(date(2026, 1, 1), 95, 0, NY)


class PrayerAPITests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="owner")
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=self.user).key}")
        self.profile = Profile.objects.create(user=self.user, timezone="America/New_York")

    def test_requires_auth(self):
        self.client.credentials()
        self.assertEqual(self.client.get("/api/prayer-times/").status_code, 401)

    def test_not_configured_without_location(self):
        r = self.client.get("/api/prayer-times/?start=2026-11-15")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data["configured"])
        self.assertEqual(r.data["days"], {})

    def test_range_returns_each_day(self):
        self.profile.latitude, self.profile.longitude, self.profile.prayer_method = 42.65, -73.75, "ISNA"
        self.profile.save()
        r = self.client.get("/api/prayer-times/?start=2026-11-15&end=2026-11-17")
        self.assertTrue(r.data["configured"])
        self.assertEqual(sorted(r.data["days"]), ["2026-11-15", "2026-11-16", "2026-11-17"])
        self.assertEqual(len(r.data["days"]["2026-11-15"]), 7)

    def test_range_limits(self):
        self.assertEqual(self.client.get("/api/prayer-times/?start=2026-11-15&end=2026-11-01").status_code, 400)
        self.assertEqual(self.client.get("/api/prayer-times/?start=2026-01-01&end=2026-12-31").status_code, 400)

    def test_dashboard_includes_prayer_times_when_configured(self):
        self.profile.latitude, self.profile.longitude = 42.65, -73.75
        self.profile.save()
        r = self.client.get("/api/dashboard/today/")
        self.assertEqual(len(r.data["prayer_times"]), 7)
        self.assertEqual(r.data["prayer_times"][0]["name"], "Fajr")
