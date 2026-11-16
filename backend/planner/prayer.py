"""Prayer-time calculation (Phase 5).

Pure Python (stdlib only, no Django imports) so it can be unit-tested and
reused anywhere. Based on the standard solar-position method used by the
widely published PrayTimes.org algorithm: sun declination + equation of
time -> solar noon, then the hour angle for each twilight/horizon angle.

Public API:
    calculate_prayer_times(day, latitude, longitude, tz, method="MWL",
                           asr_madhab="standard", elevation=0, offsets=None)
returns an ordered list of {"name", "start", "end"} dicts (aware datetimes),
which is the shape the dashboard and frontend already consume. Prayers whose
time cannot be computed (polar regions) are omitted rather than faked.

Always confirm local times against your mosque/authority; calculation
methods differ and high-latitude conventions vary.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone as dt_timezone
from typing import Optional

# method -> (fajr_angle, isha_angle or None, isha_minutes_after_maghrib or None, maghrib_angle or None)
METHODS = {
    "MWL": (18.0, 17.0, None, None),
    "ISNA": (15.0, 15.0, None, None),
    "Egypt": (19.5, 17.5, None, None),
    "Makkah": (18.5, None, 90, None),
    "Karachi": (18.0, 18.0, None, None),
    "Gulf": (19.5, None, 90, None),
    "Kuwait": (18.0, 17.5, None, None),
    "Qatar": (18.0, None, 90, None),
    "Singapore": (20.0, 18.0, None, None),
    "Turkey": (18.0, 17.0, None, None),
    "Tehran": (17.7, 14.0, None, 4.5),
    "custom": (18.0, 17.0, None, None),  # MWL angles; customise via offsets
}

PRAYER_ORDER = ["Fajr", "Sunrise", "Dhuhr", "Asr", "Maghrib", "Isha"]
# Display name -> key in profile.prayer_offsets
_OFFSET_KEYS = {n: n.lower() for n in PRAYER_ORDER}


def _sin(d): return math.sin(math.radians(d))
def _cos(d): return math.cos(math.radians(d))
def _tan(d): return math.tan(math.radians(d))
def _arcsin(x): return math.degrees(math.asin(x))
def _arccos(x): return math.degrees(math.acos(x))
def _arccot(x): return math.degrees(math.atan(1.0 / x))


def _julian_date(year: int, month: int, day: int) -> float:
    if month <= 2:
        year -= 1
        month += 12
    a = math.floor(year / 100)
    b = 2 - a + math.floor(a / 4)
    return math.floor(365.25 * (year + 4716)) + math.floor(30.6001 * (month + 1)) + day + b - 1524.5


def _sun_position(jd: float):
    """Return (declination degrees, equation of time hours) at julian date jd."""
    d = jd - 2451545.0
    g = (357.529 + 0.98560028 * d) % 360
    q = (280.459 + 0.98564736 * d) % 360
    big_l = (q + 1.915 * _sin(g) + 0.020 * _sin(2 * g)) % 360
    e = 23.439 - 0.00000036 * d
    ra = math.degrees(math.atan2(_cos(e) * _sin(big_l), _cos(big_l))) / 15.0
    ra %= 24
    eqt = q / 15.0 - ra
    # keep equation of time in (-12, 12] hours
    eqt = (eqt + 12) % 24 - 12
    decl = _arcsin(_sin(e) * _sin(big_l))
    return decl, eqt


def _hour_angle_time(angle: float, lat: float, decl: float) -> Optional[float]:
    """Hours before/after solar noon when the sun is `angle` degrees BELOW
    the horizon (negative angle = above). None if it never gets there."""
    denom = _cos(lat) * _cos(decl)
    if abs(denom) < 1e-12:
        return None
    x = (-_sin(angle) - _sin(lat) * _sin(decl)) / denom
    if x < -1 or x > 1:
        return None
    return _arccos(x) / 15.0


def _asr_time(factor: int, lat: float, decl: float) -> Optional[float]:
    angle = -_arccot(factor + _tan(abs(lat - decl)))
    return _hour_angle_time(angle, lat, decl)


def calculate_prayer_times(
    day: date,
    latitude: float,
    longitude: float,
    tz,
    method: str = "MWL",
    asr_madhab: str = "standard",
    elevation: float = 0.0,
    offsets: Optional[dict] = None,
):
    if method not in METHODS:
        raise ValueError(f"Unknown prayer method '{method}'.")
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise ValueError("Latitude/longitude out of range.")
    fajr_angle, isha_angle, isha_minutes, maghrib_angle = METHODS[method]
    offsets = offsets or {}

    # Sun position at local-solar-noon of `day` (noon UTC shifted by longitude).
    jd = _julian_date(day.year, day.month, day.day) + 0.5 - longitude / 360.0
    decl, eqt = _sun_position(jd)

    noon_utc_hours = 12 - longitude / 15.0 - eqt  # may be outside [0, 24)
    horizon = 0.833 + 0.0347 * math.sqrt(max(elevation, 0.0))

    def to_dt(hours_utc: float) -> datetime:
        base = datetime(day.year, day.month, day.day, tzinfo=dt_timezone.utc)
        return base + timedelta(hours=hours_utc)

    # Align so solar noon falls on the requested LOCAL calendar date.
    shift = 0
    for _ in range(2):
        local_noon = to_dt(noon_utc_hours + shift).astimezone(tz)
        if local_noon.date() > day:
            shift -= 24
        elif local_noon.date() < day:
            shift += 24
        else:
            break
    noon = noon_utc_hours + shift

    sunrise_ha = _hour_angle_time(horizon, latitude, decl)
    sunset_ha = sunrise_ha  # symmetric about solar noon
    raw: dict[str, Optional[float]] = {n: None for n in PRAYER_ORDER}
    raw["Dhuhr"] = noon
    if sunrise_ha is not None:
        raw["Sunrise"] = noon - sunrise_ha
        raw["Maghrib"] = noon + sunset_ha
        if maghrib_angle is not None:
            ha = _hour_angle_time(maghrib_angle, latitude, decl)
            raw["Maghrib"] = noon + ha if ha is not None else raw["Maghrib"]

    asr_ha = _asr_time(2 if asr_madhab == "hanafi" else 1, latitude, decl)
    if asr_ha is not None:
        raw["Asr"] = noon + asr_ha

    fajr_ha = _hour_angle_time(fajr_angle, latitude, decl)
    if fajr_ha is not None:
        raw["Fajr"] = noon - fajr_ha
    if isha_minutes is not None:
        if raw["Maghrib"] is not None:
            raw["Isha"] = raw["Maghrib"] + isha_minutes / 60.0
    else:
        isha_ha = _hour_angle_time(isha_angle, latitude, decl)
        if isha_ha is not None:
            raw["Isha"] = noon + isha_ha

    # High-latitude fallback: one-seventh of the night when twilight never ends.
    if raw["Sunrise"] is not None and raw["Maghrib"] is not None:
        night = (raw["Sunrise"] + 24) - raw["Maghrib"]
        portion = night / 7.0
        if raw["Fajr"] is None or (raw["Sunrise"] - raw["Fajr"]) > portion:
            raw["Fajr"] = raw["Sunrise"] - portion
        if isha_minutes is None and (raw["Isha"] is None or (raw["Isha"] - raw["Maghrib"]) > portion):
            raw["Isha"] = raw["Maghrib"] + portion

    # Apply user minute offsets, then convert to local aware datetimes.
    times: dict[str, datetime] = {}
    for name in PRAYER_ORDER:
        hours = raw[name]
        if hours is None:
            continue
        hours += float(offsets.get(_OFFSET_KEYS[name], 0)) / 60.0
        # Round to the nearest minute (prayer times are published to the minute).
        dt = to_dt(hours)
        dt = (dt + timedelta(seconds=30)).replace(second=0, microsecond=0)
        times[name] = dt.astimezone(tz)

    # Each prayer "ends" when the next begins (Fajr ends at sunrise, Isha at
    # the next Fajr approximated as end of local day).
    names = [n for n in PRAYER_ORDER if n in times]
    result = []
    for i, name in enumerate(names):
        start = times[name]
        if name == "Fajr" and "Sunrise" in times:
            end = times["Sunrise"]
        elif name == "Sunrise":
            end = start  # an instant marker, not a prayer window
        elif i + 1 < len(names):
            end = times[names[i + 1]]
        else:
            end = datetime.combine(day + timedelta(days=1), datetime.min.time(), tzinfo=tz)
        result.append({"name": name, "start": start, "end": end})

    # Zawaal marker: a line 15 minutes before Maghrib. Inserted after the
    # windows are built so every other prayer window (e.g. Asr ending at
    # Maghrib) stays exactly as it was.
    maghrib = next((r for r in result if r["name"] == "Maghrib"), None)
    if maghrib:
        result.insert(
            result.index(maghrib),
            {"name": "Zawaal", "start": maghrib["start"] - timedelta(minutes=15), "end": maghrib["start"]},
        )
    return result
