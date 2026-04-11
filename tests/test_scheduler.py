"""Tests for the scheduled collection scan feature.

Covers trigger building, form parsing, scan execution (success + error paths),
ScanLog persistence, log trimming, and job registration against a fake
scheduler so we don't start a real BackgroundScheduler in the test process.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from apscheduler.triggers.cron import CronTrigger

from pydiscogsqrcodegenerator import scheduler as scheduler_module
from pydiscogsqrcodegenerator.models import OAuthToken, ScanLog, UserSettings


class _FakeJob:
    def __init__(self, trigger, args, max_instances, coalesce, next_run_time=None):
        self.trigger = trigger
        self.args = args
        self.max_instances = max_instances
        self.coalesce = coalesce
        self.next_run_time = next_run_time


class FakeScheduler:
    """Minimal stand-in for APScheduler's BackgroundScheduler.

    Records add_job / remove_job calls so tests can assert what got registered
    without spinning up a real background thread. Returns a fake job object
    so production code that inspects ``next_run_time`` still works.
    """

    def __init__(self):
        self.jobs: dict[str, _FakeJob] = {}

    def add_job(self, func, trigger, args, id, replace_existing, max_instances, coalesce):
        next_run = None
        try:
            next_run = trigger.get_next_fire_time(None, datetime.now(timezone.utc))
        except Exception:
            pass
        job = _FakeJob(
            trigger=trigger,
            args=args,
            max_instances=max_instances,
            coalesce=coalesce,
            next_run_time=next_run,
        )
        self.jobs[id] = job
        return job

    def get_job(self, job_id):
        return self.jobs.get(job_id)

    def remove_job(self, job_id):
        if job_id not in self.jobs:
            raise KeyError(job_id)
        del self.jobs[job_id]


@pytest.fixture
def fake_scheduler(app):
    """Install a FakeScheduler into the scheduler module for the duration of a test."""
    fake = FakeScheduler()
    scheduler_module._reset_for_tests(app=app, scheduler=fake)
    yield fake
    scheduler_module._reset_for_tests(app=None, scheduler=None)


def _make_settings(username="testuser", **overrides):
    """Build a UserSettings row with schedule fields."""
    defaults = dict(
        username=username,
        scan_schedule_enabled=True,
        scan_frequency="daily",
        scan_hour=3,
        scan_minute=30,
        scan_day_of_week=0,
        scan_day_of_month=1,
        scan_month_of_year=1,
        display_timezone="UTC",
    )
    defaults.update(overrides)
    return UserSettings(**defaults)


# ---------------------------------------------------------------------------
# _build_trigger
# ---------------------------------------------------------------------------
class TestBuildTrigger:
    def test_daily_uses_hour_and_minute(self, app):
        with app.app_context():
            settings = _make_settings(scan_frequency="daily", scan_hour=9, scan_minute=15)
            trigger = scheduler_module._build_trigger(settings)
            assert isinstance(trigger, CronTrigger)
            fields = {f.name: str(f) for f in trigger.fields}
            assert fields["hour"] == "9"
            assert fields["minute"] == "15"

    def test_weekly_sets_day_of_week(self, app):
        with app.app_context():
            settings = _make_settings(
                scan_frequency="weekly", scan_day_of_week=3, scan_hour=8, scan_minute=0
            )
            trigger = scheduler_module._build_trigger(settings)
            fields = {f.name: str(f) for f in trigger.fields}
            assert fields["day_of_week"] == "3"
            assert fields["hour"] == "8"

    def test_monthly_sets_day(self, app):
        with app.app_context():
            settings = _make_settings(
                scan_frequency="monthly", scan_day_of_month=15, scan_hour=12, scan_minute=0
            )
            trigger = scheduler_module._build_trigger(settings)
            fields = {f.name: str(f) for f in trigger.fields}
            assert fields["day"] == "15"
            assert fields["hour"] == "12"

    def test_yearly_sets_month_and_day(self, app):
        with app.app_context():
            settings = _make_settings(
                scan_frequency="yearly",
                scan_month_of_year=6,
                scan_day_of_month=21,
                scan_hour=0,
                scan_minute=0,
            )
            trigger = scheduler_module._build_trigger(settings)
            fields = {f.name: str(f) for f in trigger.fields}
            assert fields["month"] == "6"
            assert fields["day"] == "21"

    def test_unknown_frequency_returns_none(self, app):
        with app.app_context():
            settings = _make_settings(scan_frequency="hourly")
            assert scheduler_module._build_trigger(settings) is None

    @pytest.mark.parametrize("freq", ["daily", "weekly", "monthly", "yearly"])
    def test_trigger_defaults_to_utc(self, app, freq):
        """Regression: CronTrigger defaults to the local timezone when no
        ``timezone=`` is passed. With an unset/default display_timezone the
        trigger must fall back to UTC."""
        with app.app_context():
            settings = _make_settings(scan_frequency=freq, display_timezone="UTC")
            trigger = scheduler_module._build_trigger(settings)
            assert trigger is not None
            assert str(trigger.timezone) == "UTC"

    @pytest.mark.parametrize("freq", ["daily", "weekly", "monthly", "yearly"])
    def test_trigger_uses_user_timezone(self, app, freq):
        """When the user picks a non-UTC zone, every frequency's trigger
        must honor it so the cron fires at the wall-clock time the user
        entered in their own locale."""
        with app.app_context():
            settings = _make_settings(
                scan_frequency=freq, display_timezone="Europe/Brussels"
            )
            trigger = scheduler_module._build_trigger(settings)
            assert trigger is not None
            assert str(trigger.timezone) == "Europe/Brussels"

    def test_trigger_falls_back_to_utc_on_invalid_timezone(self, app):
        with app.app_context():
            settings = _make_settings(display_timezone="Not/AZone")
            trigger = scheduler_module._build_trigger(settings)
            assert str(trigger.timezone) == "UTC"


# ---------------------------------------------------------------------------
# sync_user_schedule / _sync_job_for_settings / job registration
# ---------------------------------------------------------------------------
class TestJobRegistration:
    def test_enabled_schedule_registers_job(self, app, db, fake_scheduler):
        db.session.add(_make_settings(scan_schedule_enabled=True))
        db.session.commit()

        scheduler_module.sync_user_schedule("testuser")

        assert "scan::testuser" in fake_scheduler.jobs
        job = fake_scheduler.jobs["scan::testuser"]
        assert isinstance(job.trigger, CronTrigger)
        assert job.args == ["testuser"]
        assert job.coalesce is True
        assert job.max_instances == 1
        # The trigger must be UTC — otherwise scheduled times are interpreted
        # in the host's local timezone and won't fire when the user expects.
        assert str(job.trigger.timezone) == "UTC"

    def test_disabled_schedule_removes_job(self, app, db, fake_scheduler):
        # Pre-register a job by enabling first
        db.session.add(_make_settings(scan_schedule_enabled=True))
        db.session.commit()
        scheduler_module.sync_user_schedule("testuser")
        assert "scan::testuser" in fake_scheduler.jobs

        # Flip to disabled and re-sync
        settings = UserSettings.query.filter_by(username="testuser").first()
        settings.scan_schedule_enabled = False
        db.session.commit()
        scheduler_module.sync_user_schedule("testuser")

        assert "scan::testuser" not in fake_scheduler.jobs

    def test_sync_without_settings_is_noop(self, app, db, fake_scheduler):
        scheduler_module.sync_user_schedule("ghost")
        assert fake_scheduler.jobs == {}

    def test_sync_noop_when_scheduler_not_initialised(self, app, db):
        scheduler_module._reset_for_tests(app=None, scheduler=None)
        db.session.add(_make_settings())
        db.session.commit()
        # Should not raise even though there is no scheduler installed
        scheduler_module.sync_user_schedule("testuser")

    def test_get_next_run_time_returns_registered_job_time(self, app, db, fake_scheduler):
        db.session.add(_make_settings(scan_schedule_enabled=True))
        db.session.commit()
        scheduler_module.sync_user_schedule("testuser")

        next_run = scheduler_module.get_next_run_time("testuser")
        assert next_run is not None
        assert next_run.tzinfo is not None  # must be timezone-aware

    def test_get_next_run_time_none_when_no_job(self, app, db, fake_scheduler):
        assert scheduler_module.get_next_run_time("testuser") is None

    def test_get_next_run_time_none_when_scheduler_not_initialised(self, app, db):
        scheduler_module._reset_for_tests(app=None, scheduler=None)
        assert scheduler_module.get_next_run_time("testuser") is None


# ---------------------------------------------------------------------------
# run_scan — writes a ScanLog and updates UserSettings
# ---------------------------------------------------------------------------
class TestRunScan:
    def _seed_token_and_settings(self, db):
        db.session.add(OAuthToken(
            username="testuser",
            access_token="tok",
            access_token_secret="sec",
        ))
        db.session.add(_make_settings())
        db.session.commit()

    def test_missing_token_writes_error_log(self, app, db):
        db.session.add(_make_settings())
        db.session.commit()

        with app.app_context():
            ok, msg = scheduler_module.run_scan("testuser", trigger="manual")

        assert ok is False
        assert "No stored OAuth token" in msg

        logs = ScanLog.query.filter_by(username="testuser").all()
        assert len(logs) == 1
        assert logs[0].status == "error"
        assert logs[0].trigger == "manual"
        assert logs[0].finished_at is not None

    def test_successful_scan_writes_success_log(self, app, db):
        self._seed_token_and_settings(db)

        with patch(
            "pydiscogsqrcodegenerator.scheduler.DiscogsService"
        ) as service_cls, patch(
            "pydiscogsqrcodegenerator.scheduler._count_changed",
            return_value=3,
        ):
            service_instance = MagicMock()
            service_instance.warm_cache.return_value = 42
            service_cls.return_value = service_instance

            with app.app_context():
                ok, msg = scheduler_module.run_scan("testuser", trigger="scheduled")

        assert ok is True
        assert "42" in msg and "3" in msg
        service_instance.authenticate.assert_called_once_with("tok", "sec")
        service_instance.warm_cache.assert_called_once_with("testuser", folder_id=0)

        log = ScanLog.query.filter_by(username="testuser").order_by(ScanLog.id.desc()).first()
        assert log.status == "success"
        assert log.trigger == "scheduled"
        assert log.items_scanned == 42
        assert log.changed_count == 3
        assert log.finished_at is not None

        # last_scan_at/status summary on UserSettings should have been updated
        settings = UserSettings.query.filter_by(username="testuser").first()
        assert settings.last_scan_at is not None
        assert "42" in (settings.last_scan_status or "")

    def test_api_failure_is_captured_in_error_log(self, app, db):
        self._seed_token_and_settings(db)

        with patch("pydiscogsqrcodegenerator.scheduler.DiscogsService") as service_cls:
            service_instance = MagicMock()
            service_instance.warm_cache.side_effect = RuntimeError("boom")
            service_cls.return_value = service_instance

            with app.app_context():
                ok, msg = scheduler_module.run_scan("testuser")

        assert ok is False
        assert "boom" in msg

        log = ScanLog.query.filter_by(username="testuser").order_by(ScanLog.id.desc()).first()
        assert log.status == "error"
        assert "boom" in (log.message or "")


# ---------------------------------------------------------------------------
# _trim_logs — retention
# ---------------------------------------------------------------------------
class TestTrimLogs:
    def test_trim_keeps_latest_n(self, app, db, monkeypatch):
        monkeypatch.setattr(scheduler_module, "LOG_RETENTION", 3)

        base = datetime.now(timezone.utc)
        for i in range(6):
            db.session.add(ScanLog(
                username="testuser",
                started_at=base + timedelta(minutes=i),
                trigger="manual",
                status="success",
                message=f"run {i}",
            ))
        db.session.commit()

        scheduler_module._trim_logs("testuser")

        rows = (
            ScanLog.query
            .filter_by(username="testuser")
            .order_by(ScanLog.started_at.desc())
            .all()
        )
        assert len(rows) == 3
        # The three most recent runs (indices 5, 4, 3) must survive
        assert [r.message for r in rows] == ["run 5", "run 4", "run 3"]

    def test_trim_other_users_untouched(self, app, db, monkeypatch):
        monkeypatch.setattr(scheduler_module, "LOG_RETENTION", 1)

        base = datetime.now(timezone.utc)
        for i in range(3):
            db.session.add(ScanLog(
                username="alice",
                started_at=base + timedelta(minutes=i),
                status="success",
            ))
        db.session.add(ScanLog(
            username="bob",
            started_at=base,
            status="success",
        ))
        db.session.commit()

        scheduler_module._trim_logs("alice")

        assert ScanLog.query.filter_by(username="alice").count() == 1
        assert ScanLog.query.filter_by(username="bob").count() == 1
