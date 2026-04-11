from datetime import datetime, timezone
from unittest.mock import patch

from pydiscogsqrcodegenerator.models import ScanLog, UserSettings


class TestSettingsIndex:
    def test_redirects_when_unauthenticated(self, client):
        response = client.get("/settings/")
        assert response.status_code == 302

    def test_shows_default_template(self, client):
        with client.session_transaction() as sess:
            sess["username"] = "testuser"

        response = client.get("/settings/")
        assert response.status_code == 200
        assert b"Template for Text below QR Code" in response.data
        assert b"{artist}" in response.data

    def test_shows_saved_template(self, client, db):
        settings = UserSettings(
            username="testuser",
            bottom_text_template="{title} by {artist}",
        )
        db.session.add(settings)
        db.session.commit()

        with client.session_transaction() as sess:
            sess["username"] = "testuser"

        response = client.get("/settings/")
        assert response.status_code == 200
        assert b"{title} by {artist}" in response.data


class TestSettingsSave:
    def test_saves_new_settings(self, client, db):
        with client.session_transaction() as sess:
            sess["username"] = "testuser"

        response = client.post(
            "/settings/save",
            data={"bottom_text_template": "{artist} - {title}\n{format_name} {format_size}"},
            follow_redirects=True,
        )
        assert b"Settings saved" in response.data

        settings = UserSettings.query.filter_by(username="testuser").first()
        assert settings is not None
        assert "{format_name}" in settings.bottom_text_template
        assert "{format_size}" in settings.bottom_text_template

    def test_updates_existing_settings(self, client, db):
        settings = UserSettings(
            username="testuser",
            bottom_text_template="old template",
        )
        db.session.add(settings)
        db.session.commit()

        with client.session_transaction() as sess:
            sess["username"] = "testuser"

        client.post(
            "/settings/save",
            data={"bottom_text_template": "new template"},
        )

        settings = UserSettings.query.filter_by(username="testuser").first()
        assert settings.bottom_text_template == "new template"

    def test_redirects_when_unauthenticated(self, client):
        response = client.post(
            "/settings/save",
            data={"bottom_text_template": "test"},
        )
        assert response.status_code == 302


class TestSaveTimezone:
    def test_saves_valid_timezone(self, client, db):
        with client.session_transaction() as sess:
            sess["username"] = "testuser"

        client.post(
            "/settings/save",
            data={
                "bottom_text_template": "x",
                "display_timezone": "Europe/Brussels",
            },
        )

        settings = UserSettings.query.filter_by(username="testuser").first()
        assert settings.display_timezone == "Europe/Brussels"

    def test_invalid_timezone_falls_back_to_utc(self, client, db):
        with client.session_transaction() as sess:
            sess["username"] = "testuser"

        client.post(
            "/settings/save",
            data={
                "bottom_text_template": "x",
                "display_timezone": "Not/AZone",
            },
        )

        settings = UserSettings.query.filter_by(username="testuser").first()
        assert settings.display_timezone == "UTC"

    def test_changing_timezone_resyncs_active_schedule(self, client, db):
        db.session.add(UserSettings(
            username="testuser",
            display_timezone="UTC",
            scan_schedule_enabled=True,
            scan_frequency="daily",
            scan_hour=9,
            scan_minute=0,
        ))
        db.session.commit()

        with client.session_transaction() as sess:
            sess["username"] = "testuser"

        with patch(
            "pydiscogsqrcodegenerator.blueprints.settings.sync_user_schedule"
        ) as sync:
            client.post(
                "/settings/save",
                data={
                    "bottom_text_template": "x",
                    "display_timezone": "America/New_York",
                },
            )

        sync.assert_called_once_with("testuser")

    def test_changing_timezone_without_active_schedule_does_not_resync(self, client, db):
        db.session.add(UserSettings(
            username="testuser",
            display_timezone="UTC",
            scan_schedule_enabled=False,
        ))
        db.session.commit()

        with client.session_transaction() as sess:
            sess["username"] = "testuser"

        with patch(
            "pydiscogsqrcodegenerator.blueprints.settings.sync_user_schedule"
        ) as sync:
            client.post(
                "/settings/save",
                data={
                    "bottom_text_template": "x",
                    "display_timezone": "Asia/Tokyo",
                },
            )

        sync.assert_not_called()


class TestSettingsIndexRendersTimezone:
    def test_shows_saved_timezone_selected(self, client, db):
        db.session.add(UserSettings(
            username="testuser",
            display_timezone="Europe/Brussels",
        ))
        db.session.commit()

        with client.session_transaction() as sess:
            sess["username"] = "testuser"

        response = client.get("/settings/")
        # The dropdown should mark Europe/Brussels as selected
        assert b'value="Europe/Brussels" selected' in response.data
        # Schedule help text should name the selected tz
        assert b"interpreted in <strong>Europe/Brussels</strong>" in response.data


class TestSaveSchedule:
    def test_saves_new_schedule_and_syncs(self, client, db):
        with client.session_transaction() as sess:
            sess["username"] = "testuser"

        with patch(
            "pydiscogsqrcodegenerator.blueprints.settings.sync_user_schedule"
        ) as sync:
            response = client.post(
                "/settings/schedule/save",
                data={
                    "scan_schedule_enabled": "1",
                    "scan_frequency": "weekly",
                    "scan_hour": "14",
                    "scan_minute": "30",
                    "scan_day_of_week": "2",
                    "scan_day_of_month": "1",
                    "scan_month_of_year": "1",
                },
                follow_redirects=True,
            )

        assert b"Scan schedule saved" in response.data
        sync.assert_called_once_with("testuser")

        settings = UserSettings.query.filter_by(username="testuser").first()
        assert settings.scan_schedule_enabled is True
        assert settings.scan_frequency == "weekly"
        assert settings.scan_hour == 14
        assert settings.scan_minute == 30
        assert settings.scan_day_of_week == 2

    def test_clamps_out_of_range_values(self, client, db):
        with client.session_transaction() as sess:
            sess["username"] = "testuser"

        with patch("pydiscogsqrcodegenerator.blueprints.settings.sync_user_schedule"):
            client.post(
                "/settings/schedule/save",
                data={
                    "scan_schedule_enabled": "1",
                    "scan_frequency": "daily",
                    "scan_hour": "99",
                    "scan_minute": "-5",
                    "scan_day_of_week": "0",
                    "scan_day_of_month": "1",
                    "scan_month_of_year": "1",
                },
            )

        settings = UserSettings.query.filter_by(username="testuser").first()
        assert settings.scan_hour == 23  # clamped down
        assert settings.scan_minute == 0  # clamped up

    def test_invalid_frequency_falls_back_to_daily(self, client, db):
        with client.session_transaction() as sess:
            sess["username"] = "testuser"

        with patch("pydiscogsqrcodegenerator.blueprints.settings.sync_user_schedule"):
            client.post(
                "/settings/schedule/save",
                data={
                    "scan_schedule_enabled": "1",
                    "scan_frequency": "hourly",  # not in FREQUENCIES
                    "scan_hour": "9",
                    "scan_minute": "0",
                },
            )

        settings = UserSettings.query.filter_by(username="testuser").first()
        assert settings.scan_frequency == "daily"

    def test_disable_leaves_row_but_flags_disabled(self, client, db):
        db.session.add(UserSettings(
            username="testuser",
            scan_schedule_enabled=True,
            scan_frequency="daily",
            scan_hour=5,
            scan_minute=0,
        ))
        db.session.commit()

        with client.session_transaction() as sess:
            sess["username"] = "testuser"

        with patch("pydiscogsqrcodegenerator.blueprints.settings.sync_user_schedule"):
            # Note: unchecked checkbox is not sent in the form
            client.post(
                "/settings/schedule/save",
                data={
                    "scan_frequency": "daily",
                    "scan_hour": "5",
                    "scan_minute": "0",
                },
            )

        settings = UserSettings.query.filter_by(username="testuser").first()
        assert settings.scan_schedule_enabled is False

    def test_redirects_when_unauthenticated(self, client):
        response = client.post("/settings/schedule/save", data={})
        assert response.status_code == 302


class TestScanNowRoute:
    def test_invokes_run_scan_and_flashes(self, client, db):
        with client.session_transaction() as sess:
            sess["username"] = "testuser"

        with patch(
            "pydiscogsqrcodegenerator.blueprints.settings.run_scan",
            return_value=(True, "Scanned 10 releases, 2 changed since last processed"),
        ) as run_scan:
            response = client.post("/settings/scan-now", follow_redirects=True)

        run_scan.assert_called_once_with("testuser", trigger="manual")
        assert b"Scanned 10 releases" in response.data

    def test_failure_flashes_error_message(self, client, db):
        with client.session_transaction() as sess:
            sess["username"] = "testuser"

        with patch(
            "pydiscogsqrcodegenerator.blueprints.settings.run_scan",
            return_value=(False, "No stored OAuth token"),
        ):
            response = client.post("/settings/scan-now", follow_redirects=True)

        assert b"No stored OAuth token" in response.data

    def test_redirects_when_unauthenticated(self, client):
        response = client.post("/settings/scan-now")
        assert response.status_code == 302


class TestScanLogsUI:
    def _add_log(self, db, **overrides):
        defaults = dict(
            username="testuser",
            started_at=datetime(2026, 4, 11, 3, 0, 0, tzinfo=timezone.utc),
            finished_at=datetime(2026, 4, 11, 3, 0, 5, tzinfo=timezone.utc),
            trigger="scheduled",
            status="success",
            items_scanned=100,
            changed_count=4,
            message="Scanned 100 releases, 4 changed since last processed",
        )
        defaults.update(overrides)
        db.session.add(ScanLog(**defaults))
        db.session.commit()

    def test_logs_render_in_settings_page(self, client, db):
        self._add_log(db)

        with client.session_transaction() as sess:
            sess["username"] = "testuser"

        response = client.get("/settings/")
        assert response.status_code == 200
        assert b"Scan Logs" in response.data
        assert b"Scanned 100 releases" in response.data
        assert b"scheduled" in response.data

    def test_error_logs_render_with_danger_badge(self, client, db):
        self._add_log(db, status="error", message="boom")

        with client.session_transaction() as sess:
            sess["username"] = "testuser"

        response = client.get("/settings/")
        assert b"badge-danger" in response.data
        assert b"boom" in response.data

    def test_empty_state_when_no_logs(self, client, db):
        with client.session_transaction() as sess:
            sess["username"] = "testuser"

        response = client.get("/settings/")
        assert b"No scans have run yet" in response.data

    def test_clear_logs_removes_rows(self, client, db):
        self._add_log(db)
        self._add_log(db, status="error", message="boom")
        assert ScanLog.query.filter_by(username="testuser").count() == 2

        with client.session_transaction() as sess:
            sess["username"] = "testuser"

        response = client.post("/settings/scan-logs/clear", follow_redirects=True)
        assert b"Cleared 2 scan log entries" in response.data
        assert ScanLog.query.filter_by(username="testuser").count() == 0

    def test_clear_logs_only_affects_current_user(self, client, db):
        self._add_log(db, username="alice")
        self._add_log(db, username="bob")

        with client.session_transaction() as sess:
            sess["username"] = "alice"

        client.post("/settings/scan-logs/clear")

        assert ScanLog.query.filter_by(username="alice").count() == 0
        assert ScanLog.query.filter_by(username="bob").count() == 1

    def test_clear_logs_redirects_when_unauthenticated(self, client):
        response = client.post("/settings/scan-logs/clear")
        assert response.status_code == 302
