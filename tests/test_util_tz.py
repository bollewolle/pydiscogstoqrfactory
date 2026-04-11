"""Tests for util_tz — display timezone helpers."""
from datetime import datetime, timezone

from pydiscogsqrcodegenerator import util_tz
from pydiscogsqrcodegenerator.models import UserSettings


class TestListTimezones:
    def test_includes_utc_first(self):
        zones = util_tz.list_timezones()
        assert zones[0] == "UTC"

    def test_contains_expected_zones(self):
        zones = util_tz.list_timezones()
        assert "Europe/Brussels" in zones
        assert "America/New_York" in zones
        assert "Asia/Tokyo" in zones

    def test_no_duplicates(self):
        zones = util_tz.list_timezones()
        assert len(zones) == len(set(zones))


class TestIsValidTimezone:
    def test_valid(self):
        assert util_tz.is_valid_timezone("UTC")
        assert util_tz.is_valid_timezone("Europe/Brussels")

    def test_invalid(self):
        assert not util_tz.is_valid_timezone("Not/AZone")
        assert not util_tz.is_valid_timezone("")


class TestGetUserTimezone:
    def test_defaults_to_utc_when_no_settings(self, app, db):
        with app.test_request_context():
            from flask import session
            session["username"] = "testuser"
            assert util_tz.get_user_timezone_name() == "UTC"

    def test_returns_saved_timezone(self, app, db):
        db.session.add(UserSettings(
            username="testuser",
            display_timezone="Europe/Brussels",
        ))
        db.session.commit()

        with app.test_request_context():
            from flask import session
            session["username"] = "testuser"
            assert util_tz.get_user_timezone_name() == "Europe/Brussels"

    def test_falls_back_when_saved_tz_is_invalid(self, app, db):
        # Bypass is_valid_timezone by writing directly
        db.session.add(UserSettings(
            username="testuser",
            display_timezone="Not/AZone",
        ))
        db.session.commit()

        with app.test_request_context():
            from flask import session
            session["username"] = "testuser"
            assert util_tz.get_user_timezone_name() == "UTC"

    def test_returns_utc_when_no_session(self, app, db):
        with app.test_request_context():
            assert util_tz.get_user_timezone_name() == "UTC"


class TestToDisplay:
    def test_none_returns_none(self):
        assert util_tz.to_display(None, "UTC") is None

    def test_naive_is_treated_as_utc(self):
        # 12:00 naive UTC -> 13:00 or 14:00 in Brussels depending on DST.
        naive = datetime(2026, 1, 15, 12, 0, 0)
        converted = util_tz.to_display(naive, "Europe/Brussels")
        assert converted is not None
        # January — CET = UTC+1
        assert converted.hour == 13
        assert str(converted.tzinfo) == "Europe/Brussels"

    def test_aware_datetime_is_converted(self):
        aware = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        converted = util_tz.to_display(aware, "America/New_York")
        # January — EST = UTC-5
        assert converted.hour == 7

    def test_utc_to_utc_is_noop_in_value(self):
        dt = datetime(2026, 6, 1, 9, 0, 0, tzinfo=timezone.utc)
        converted = util_tz.to_display(dt, "UTC")
        assert converted.hour == 9
        assert str(converted.tzinfo) == "UTC"
