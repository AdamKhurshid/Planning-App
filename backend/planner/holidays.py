"""Public holidays: fetched from the date.nager.at feed, cached in the
Holiday table (source="nager"), plus user-added manual holidays.

Nothing is hardcoded: dates come from the feed or the user. The feed is
re-fetched when the cached year is older than REFRESH_AFTER_DAYS (nager
occasionally publishes/corrects upcoming years). If the network is down the
cached rows are kept — a stale calendar beats an empty one.
"""
from datetime import date, datetime, timedelta, timezone as dt_timezone
import json
import urllib.request

from django.utils import timezone

from .models import Holiday

API_BASE = "https://date.nager.at/api/v3"
REFRESH_AFTER_DAYS = 14
HTTP_TIMEOUT = 8

# Bundled only as a fallback for the country picker when the network is
# unavailable — holiday *dates* are always fetched, never hardcoded.
FALLBACK_COUNTRIES = [
    {"country_code": "US", "name": "United States"},
    {"country_code": "GB", "name": "United Kingdom"},
    {"country_code": "CA", "name": "Canada"},
    {"country_code": "AU", "name": "Australia"},
    {"country_code": "DE", "name": "Germany"},
    {"country_code": "FR", "name": "France"},
    {"country_code": "NL", "name": "Netherlands"},
    {"country_code": "ES", "name": "Spain"},
    {"country_code": "IT", "name": "Italy"},
    {"country_code": "SE", "name": "Sweden"},
    {"country_code": "NO", "name": "Norway"},
    {"country_code": "DK", "name": "Denmark"},
    {"country_code": "FI", "name": "Finland"},
    {"country_code": "PL", "name": "Poland"},
    {"country_code": "PT", "name": "Portugal"},
    {"country_code": "IE", "name": "Ireland"},
    {"country_code": "AT", "name": "Austria"},
    {"country_code": "CH", "name": "Switzerland"},
    {"country_code": "BE", "name": "Belgium"},
    {"country_code": "TR", "name": "Türkiye"},
    {"country_code": "BR", "name": "Brazil"},
    {"country_code": "MX", "name": "Mexico"},
    {"country_code": "AR", "name": "Argentina"},
    {"country_code": "IN", "name": "India"},
    {"country_code": "CN", "name": "China"},
    {"country_code": "JP", "name": "Japan"},
    {"country_code": "KR", "name": "South Korea"},
    {"country_code": "SG", "name": "Singapore"},
    {"country_code": "MY", "name": "Malaysia"},
    {"country_code": "ID", "name": "Indonesia"},
    {"country_code": "ZA", "name": "South Africa"},
    {"country_code": "AE", "name": "United Arab Emirates"},
    {"country_code": "SA", "name": "Saudi Arabia"},
    {"country_code": "EG", "name": "Egypt"},
    {"country_code": "MA", "name": "Morocco"},
    {"country_code": "NZ", "name": "New Zealand"},
]


class FeedUnavailable(Exception):
    """The holiday feed could not be reached or returned bad data."""


def _get_json(url):
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "Tempo/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as res:
            if res.status != 200:
                raise FeedUnavailable(f"HTTP {res.status} from {url}")
            return json.loads(res.read().decode("utf-8"))
    except FeedUnavailable:
        raise
    except Exception as exc:  # urllib errors, JSON errors, DNS, timeouts
        raise FeedUnavailable(str(exc)) from exc


_countries_cache = None
_countries_cache_at = None


def available_countries():
    """Country list for the picker: live feed with a 24h process cache,
    falling back to a bundled short list when offline."""
    global _countries_cache, _countries_cache_at
    now = timezone.now()
    if _countries_cache and _countries_cache_at and now - _countries_cache_at < timedelta(hours=24):
        return _countries_cache
    try:
        data = _get_json(f"{API_BASE}/AvailableCountries")
        countries = [{"country_code": d["countryCode"], "name": d["name"]} for d in data]
        if not countries:
            raise FeedUnavailable("empty country list")
        _countries_cache, _countries_cache_at = countries, now
        return countries
    except FeedUnavailable:
        return FALLBACK_COUNTRIES


def _region_matches(entry, country, region):
    """Nager marks nationwide holidays global=True; regional ones list
    subdivisions like "US-NY"."""
    if not region:
        return True
    if entry.get("global"):
        return True
    counties = entry.get("counties") or []
    return not counties or f"{country}-{region}" in counties


def _fetch_year(country, region, year):
    """Fetch one year from the feed as parsed Holiday kwargs (no DB writes)."""
    data = _get_json(f"{API_BASE}/PublicHolidays/{year}/{country}")
    if not isinstance(data, list):
        raise FeedUnavailable("unexpected feed payload")
    rows = []
    for entry in data:
        try:
            day = date.fromisoformat(entry["date"])
        except (KeyError, ValueError, TypeError):
            continue
        if not _region_matches(entry, country, region):
            continue
        rows.append({
            "date": day,
            "name": str(entry.get("name") or "")[:200],
            "local_name": str(entry.get("localName") or "")[:200],
            "country": country,
            "region": region,
            "source": Holiday.Source.NAGER,
        })
    return rows


def ensure_year(user, country, region, year):
    """Materialise (and refresh when stale) the cached holidays for a year.
    Returns the cached rows; on feed failure returns whatever is cached."""
    qs = Holiday.all_objects.filter(owner=user, source=Holiday.Source.NAGER, country=country,
                                    region=region, date__year=year)
    existing = list(qs)
    if existing:
        newest = max(h.created_at for h in existing)
        if timezone.now() - newest < timedelta(days=REFRESH_AFTER_DAYS):
            return [h for h in existing if h.deleted_at is None]
    try:
        rows = _fetch_year(country, region, year)
    except FeedUnavailable:
        # Keep serving the cached rows; nothing new to delete.
        return [h for h in existing if h.deleted_at is None]
    # Refresh: drop old feed rows (manual rows are never touched) and write
    # the fresh ones.
    qs.delete()
    for row in rows:
        Holiday.all_objects.update_or_create(
            owner=user, date=row["date"], name=row["name"], country=country, region=region,
            source=Holiday.Source.NAGER,
            defaults={"local_name": row["local_name"], "deleted_at": None},
        )
    return [h for h in qs if h.deleted_at is None]


def holidays_in_range(user, profile, start, end):
    """Holidays (feed + manual) between start and end inclusive, as dicts."""
    country = (profile.holidays_country or "").strip()
    region = (profile.holidays_region or "").strip()
    items = []
    if country:
        for year in sorted({start.year, end.year}):
            for h in ensure_year(user, country, region, year):
                if start <= h.date <= end:
                    items.append(h)
    for h in Holiday.objects.filter(owner=user, source=Holiday.Source.MANUAL, date__gte=start, date__lte=end):
        items.append(h)
    items.sort(key=lambda h: (h.date, h.name))
    return [{"date": h.date, "name": h.name, "local_name": h.local_name,
             "country": h.country, "region": h.region, "source": h.source} for h in items]
