"""Recurrence expansion + calendar range endpoint tests."""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from .models import Event, RecurrenceOverride, TimeBlock, Task
from .recurrence import expand_event, validate_rrule

NY = ZoneInfo("America/New_York")


class ExpandTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="u")

    def ev(self, start, rule="", hours=1):
        return Event.objects.create(owner=self.user, title="E", start=start, end=start + timedelta(hours=hours),
                                    recurrence_rule=rule)

    def test_single_event_in_and_out_of_range(self):
        e = self.ev(datetime(2030, 1, 7, 9, tzinfo=NY))
        self.assertEqual(len(expand_event(e, datetime(2030, 1, 7, tzinfo=NY), datetime(2030, 1, 8, tzinfo=NY), NY)), 1)
        self.assertEqual(expand_event(e, datetime(2030, 1, 8, tzinfo=NY), datetime(2030, 1, 9, tzinfo=NY), NY), [])

    def test_weekly_rule(self):
        e = self.ev(datetime(2030, 1, 7, 9, tzinfo=NY), "FREQ=WEEKLY;BYDAY=MO,WE")
        occ = expand_event(e, datetime(2030, 1, 7, tzinfo=NY), datetime(2030, 1, 21, tzinfo=NY), NY)
        self.assertEqual([o["start"].strftime("%a %d") for o in occ], ["Mon 07", "Wed 09", "Mon 14", "Wed 16"])

    def test_wall_clock_time_survives_dst(self):
        # US DST starts 2030-03-10; a 09:00 weekly meeting must stay at 09:00 local.
        e = self.ev(datetime(2030, 3, 4, 9, tzinfo=NY), "FREQ=WEEKLY")
        occ = expand_event(e, datetime(2030, 3, 4, tzinfo=NY), datetime(2030, 3, 20, tzinfo=NY), NY)
        self.assertTrue(all(o["start"].astimezone(NY).hour == 9 for o in occ))
        self.assertEqual(len(occ), 3)

    def test_cancel_and_patch_overrides(self):
        e = self.ev(datetime(2030, 1, 7, 9, tzinfo=NY), "FREQ=DAILY;COUNT=3")
        RecurrenceOverride.objects.create(owner=self.user, event=e, original_date=date(2030, 1, 8), is_cancelled=True)
        RecurrenceOverride.objects.create(owner=self.user, event=e, original_date=date(2030, 1, 9),
                                          patch={"start": "2030-01-09T15:00:00-05:00", "title": "Moved"})
        occ = expand_event(e, datetime(2030, 1, 7, tzinfo=NY), datetime(2030, 1, 12, tzinfo=NY), NY,
                           overrides=e.overrides.all())
        self.assertEqual(len(occ), 2)
        moved = occ[1]
        self.assertEqual(moved["title"], "Moved")
        self.assertEqual(moved["start"].hour, 15)
        self.assertEqual(moved["end"] - moved["start"], timedelta(hours=1))   # duration preserved

    def test_validate_rrule(self):
        validate_rrule("FREQ=DAILY;COUNT=2")
        validate_rrule("")
        with self.assertRaises(ValueError):
            validate_rrule("NOT A RULE")


class CalendarAPITests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="owner")
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=self.user).key}")

    def test_range_returns_expanded_events_and_blocks(self):
        s = datetime(2030, 1, 7, 9, tzinfo=ZoneInfo("UTC"))
        Event.objects.create(owner=self.user, title="Gym", start=s, end=s + timedelta(hours=1),
                             recurrence_rule="FREQ=DAILY;COUNT=3")
        t = Task.objects.create(owner=self.user, title="Work")
        TimeBlock.objects.create(owner=self.user, task=t, start=s + timedelta(hours=2), end=s + timedelta(hours=3))
        r = self.client.get("/api/calendar/", {"start": "2030-01-07T00:00:00Z", "end": "2030-01-10T00:00:00Z"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.data["events"]), 3)
        self.assertTrue(r.data["events"][0]["is_recurring"])
        self.assertEqual(r.data["blocks"][0]["title"], "Work")

    def test_validation_and_auth(self):
        self.assertEqual(self.client.get("/api/calendar/").status_code, 400)
        self.assertEqual(self.client.get("/api/calendar/", {"start": "2030-01-01T00:00:00Z",
                                                            "end": "2031-01-01T00:00:00Z"}).status_code, 400)
        self.client.credentials()
        self.assertEqual(self.client.get("/api/calendar/").status_code, 401)

    def test_bad_rrule_rejected_on_create(self):
        r = self.client.post("/api/events/", {"title": "x", "start": "2030-01-07T09:00:00Z",
                                              "end": "2030-01-07T10:00:00Z", "recurrence_rule": "garbage"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("recurrence_rule", r.data)
