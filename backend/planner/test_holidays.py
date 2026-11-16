"""Holiday feed + cache + manual entries. The network is mocked throughout:
holiday *dates* come from the mocked feed or the user, never from the test."""
import json
from datetime import date
from unittest import mock

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from accounts.models import Profile
from .holidays import FALLBACK_COUNTRIES, FeedUnavailable, ensure_year, holidays_in_range
from .models import Holiday

User = get_user_model()

# A slice of what date.nager.at returns for US 2026 (shape-accurate).
FEED_US_2026 = [
    {"date": "2026-01-01", "localName": "New Year's Day", "name": "New Year's Day",
     "countryCode": "US", "fixed": True, "global": True, "counties": None, "types": ["public"]},
    {"date": "2026-07-04", "localName": "Independence Day", "name": "Independence Day",
     "countryCode": "US", "fixed": True, "global": True, "counties": None, "types": ["public"]},
    {"date": "2026-11-26", "localName": "Thanksgiving Day", "name": "Thanksgiving Day",
     "countryCode": "US", "fixed": True, "global": False, "counties": None, "types": ["public"]},
    {"date": "2026-04-06", "localName": "State holiday", "name": "Emancipation Day",
     "countryCode": "US", "fixed": False, "global": False, "counties": ["US-DC"], "types": ["public"]},
]


class BaseAPITestCase(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="owner")
        token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        self.profile, _ = Profile.objects.get_or_create(user=self.user)


class FetchAndCacheTests(BaseAPITestCase):
    def _set_country(self, country="US", region=""):
        self.profile.holidays_country = country
        self.profile.holidays_region = region
        self.profile.save()

    def test_fetch_materialises_rows(self):
        self._set_country()
        with mock.patch("planner.holidays._get_json", return_value=FEED_US_2026):
            rows = ensure_year(self.user, "US", "", 2026)
        self.assertEqual(Holiday.objects.filter(owner=self.user).count(), 4)
        self.assertEqual({r["date"] for r in holidays_in_range(self.user, self.profile, date(2026, 1, 1), date(2026, 12, 31))},
                         {date(2026, 1, 1), date(2026, 7, 4), date(2026, 11, 26), date(2026, 4, 6)})

    def test_region_filter_keeps_global_and_matching(self):
        self.profile.holidays_country = "US"
        self.profile.holidays_region = "NY"
        self.profile.save()
        with mock.patch("planner.holidays._get_json", return_value=FEED_US_2026):
            rows = holidays_in_range(self.user, self.profile, date(2026, 1, 1), date(2026, 12, 31))
        names = {r["name"] for r in rows}
        self.assertIn("Independence Day", names)          # global=True
        self.assertNotIn("Emancipation Day", names)       # US-DC only
        # The same feed for region DC keeps the regional holiday.
        self.profile.holidays_region = "DC"
        self.profile.save()
        with mock.patch("planner.holidays._get_json", return_value=FEED_US_2026):
            rows = holidays_in_range(self.user, self.profile, date(2026, 1, 1), date(2026, 12, 31))
        self.assertIn("Emancipation Day", {r["name"] for r in rows})

    def test_second_call_uses_cache_without_network(self):
        self._set_country()
        with mock.patch("planner.holidays._get_json", return_value=FEED_US_2026) as mocked:
            ensure_year(self.user, "US", "", 2026)
            ensure_year(self.user, "US", "", 2026)
        self.assertEqual(mocked.call_count, 1)

    def test_feed_failure_keeps_cached_rows(self):
        self._set_country()
        with mock.patch("planner.holidays._get_json", return_value=FEED_US_2026):
            ensure_year(self.user, "US", "", 2026)
        with mock.patch("planner.holidays._get_json", side_effect=FeedUnavailable("offline")):
            rows = holidays_in_range(self.user, self.profile, date(2026, 7, 1), date(2026, 7, 31))
        self.assertEqual([r["name"] for r in rows], ["Independence Day"])

    def test_manual_rows_survive_refresh(self):
        self._set_country()
        Holiday.objects.create(owner=self.user, date=date(2026, 3, 5), name="Family day",
                               source=Holiday.Source.MANUAL)
        with mock.patch("planner.holidays._get_json", return_value=FEED_US_2026):
            ensure_year(self.user, "US", "", 2026)
        self.assertTrue(Holiday.objects.filter(owner=self.user, name="Family day").exists())

    def test_refresh_when_stale(self):
        self._set_country()
        with mock.patch("planner.holidays._get_json", return_value=FEED_US_2026):
            ensure_year(self.user, "US", "", 2026)
        old = [h for h in Holiday.objects.filter(owner=self.user)]
        for h in old:
            h.created_at = h.created_at.replace(year=2020)
            h.save()
        with mock.patch("planner.holidays._get_json", return_value=FEED_US_2026) as mocked:
            ensure_year(self.user, "US", "", 2026)
        self.assertEqual(mocked.call_count, 1)


class HolidayAPITests(BaseAPITestCase):
    def test_list_reports_unconfigured_when_no_country(self):
        response = self.client.get("/api/holidays/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["configured"])
        self.assertEqual(response.data["holidays"], [])

    def test_manual_create_and_delete(self):
        response = self.client.post("/api/holidays/", {"date": "2026-12-24", "name": "Family dinner"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["source"], "manual")
        # Feed rows can't be deleted through the API.
        feed = Holiday.objects.create(owner=self.user, date=date(2026, 1, 1), name="New Year's Day",
                                      source=Holiday.Source.NAGER)
        response = self.client.delete(f"/api/holidays/{feed.id}/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        # …but manual rows can.
        manual_id = Holiday.objects.get(name="Family dinner").id
        response = self.client.delete(f"/api/holidays/{manual_id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Holiday.objects.filter(pk=manual_id).exists())

    def test_bad_date_rejected(self):
        response = self.client.post("/api/holidays/", {"date": "24-12-2026", "name": "X"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_countries_endpoint(self):
        response = self.client.get("/api/holidays/countries/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(any(c["country_code"] == "US" for c in response.data["countries"]))

    def test_countries_falls_back_when_offline(self):
        from . import holidays as holidays_module
        holidays_module._countries_cache = None  # reset the 24h process cache
        with mock.patch("planner.holidays._get_json", side_effect=FeedUnavailable("offline")):
            response = self.client.get("/api/holidays/countries/")
        holidays_module._countries_cache = None  # don't leak the fallback list
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["countries"], FALLBACK_COUNTRIES)

    def test_dashboard_includes_holidays(self):
        Holiday.objects.create(owner=self.user, date=date.today().replace(year=2020), name="Legacy")
        Holiday.objects.create(owner=self.user, date=date.today(), name="Today feast",
                               source=Holiday.Source.MANUAL)
        response = self.client.get("/api/dashboard/today/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([h["name"] for h in response.data["holidays"]], ["Today feast"])
