"""Helpers for user-configurable display timezones.

Times are always *stored* in UTC (naive or aware). These helpers convert to
the display timezone chosen by the logged-in user in Settings.
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, available_timezones

from flask import session

from .models import UserSettings

DEFAULT_TIMEZONE = "UTC"


def list_timezones() -> list[str]:
    """Return sorted list of all IANA timezone names. Used to populate the
    Settings dropdown. Guarantees 'UTC' is always first so the default is
    easy to pick."""
    zones = sorted(available_timezones())
    if "UTC" in zones:
        zones.remove("UTC")
    return ["UTC"] + zones


def is_valid_timezone(name: str) -> bool:
    return name in available_timezones()


def get_user_timezone_name(username: str | None = None) -> str:
    """Look up the saved display timezone for a user, defaulting to UTC.

    If ``username`` is not given, the logged-in username from the session
    is used. Returns a string (not a ZoneInfo) so callers can pass it to
    APScheduler's CronTrigger as well as use it for display.
    """
    if username is None:
        username = session.get("username") if session else None
    if not username:
        return DEFAULT_TIMEZONE
    try:
        settings = UserSettings.query.filter_by(username=username).first()
    except Exception:
        return DEFAULT_TIMEZONE
    if settings and settings.display_timezone and is_valid_timezone(settings.display_timezone):
        return settings.display_timezone
    return DEFAULT_TIMEZONE


def get_user_zoneinfo(username: str | None = None) -> ZoneInfo:
    return ZoneInfo(get_user_timezone_name(username))


def to_display(dt: datetime | None, tz_name: str | None = None) -> datetime | None:
    """Convert a UTC datetime (naive or aware) to the user's display tz.

    Naive datetimes are assumed to be UTC — which is how we store them via
    ``datetime.now(timezone.utc)``, since SQLite drops tzinfo on read.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if tz_name is None:
        tz_name = get_user_timezone_name()
    return dt.astimezone(ZoneInfo(tz_name))
