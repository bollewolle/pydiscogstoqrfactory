"""Background scheduler for periodic Discogs collection scans.

Uses APScheduler's BackgroundScheduler to run per-user scan jobs according
to each user's saved preferences. Each scan authenticates with the stored
OAuth token and warms the in-memory collection cache (marked persistent),
so the landing page can show an accurate "Changed Releases" count without
triggering an API call on page load.

Note: this scheduler runs in-process. If the app is deployed with multiple
workers, each worker will schedule its own jobs. For a single-container
deploy (the default docker compose setup), this is fine.
"""
import logging
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

# CronTrigger must always be handed an explicit timezone. Without one, it
# falls back to the local system timezone, so schedules fire at the wrong
# wall-clock time on any host whose local zone is not UTC. Each user can
# pick their own display timezone in Settings; we read it from UserSettings
# at trigger build time and default to UTC when absent.
DEFAULT_SCHEDULE_TZ = "UTC"

from .discogs_service import DiscogsService
from .extensions import db
from .models import OAuthToken, ScanLog, UserSettings

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None
_flask_app = None

FREQUENCIES = ("daily", "weekly", "monthly", "yearly")
WEEKDAY_LABELS = [
    (0, "Monday"),
    (1, "Tuesday"),
    (2, "Wednesday"),
    (3, "Thursday"),
    (4, "Friday"),
    (5, "Saturday"),
    (6, "Sunday"),
]


def init_scheduler(app) -> None:
    """Start the background scheduler and register jobs for existing users."""
    global _scheduler, _flask_app

    # Skip during unit tests — tests that need the scheduler call init explicitly
    if app.config.get("TESTING"):
        logger.debug("Skipping scheduler start under TESTING config")
        return

    # Avoid double-start under Flask's reloader (debug mode spawns a child)
    import os
    if app.debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        logger.debug("Skipping scheduler start in reloader parent process")
        return

    if _scheduler is not None:
        return

    _flask_app = app
    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.start()

    # Register jobs for any users that already have scheduling enabled
    with app.app_context():
        try:
            rows = UserSettings.query.filter_by(scan_schedule_enabled=True).all()
        except Exception:
            logger.exception("Could not load UserSettings for scheduler init")
            rows = []
        for settings in rows:
            try:
                _sync_job_for_settings(settings)
            except Exception:
                logger.exception(
                    "Failed to register scan job for user %s", settings.username
                )

    import atexit
    atexit.register(lambda: _scheduler.shutdown(wait=False) if _scheduler else None)
    logger.info("Background scheduler started")


def _job_id(username: str) -> str:
    return f"scan::{username}"


def _build_trigger(settings: UserSettings) -> CronTrigger | None:
    """Translate the user's schedule fields into an APScheduler CronTrigger."""
    from .util_tz import is_valid_timezone

    hour = settings.scan_hour if settings.scan_hour is not None else 3
    minute = settings.scan_minute if settings.scan_minute is not None else 0
    freq = settings.scan_frequency or "daily"
    tz = settings.display_timezone or DEFAULT_SCHEDULE_TZ
    if not is_valid_timezone(tz):
        tz = DEFAULT_SCHEDULE_TZ

    if freq == "daily":
        return CronTrigger(hour=hour, minute=minute, timezone=tz)
    if freq == "weekly":
        # APScheduler accepts 0-6 where 0 is Monday
        dow = settings.scan_day_of_week if settings.scan_day_of_week is not None else 0
        return CronTrigger(
            day_of_week=dow, hour=hour, minute=minute, timezone=tz
        )
    if freq == "monthly":
        day = settings.scan_day_of_month if settings.scan_day_of_month is not None else 1
        return CronTrigger(
            day=day, hour=hour, minute=minute, timezone=tz
        )
    if freq == "yearly":
        month = settings.scan_month_of_year if settings.scan_month_of_year is not None else 1
        day = settings.scan_day_of_month if settings.scan_day_of_month is not None else 1
        return CronTrigger(
            month=month, day=day, hour=hour, minute=minute, timezone=tz
        )
    return None


def sync_user_schedule(username: str) -> None:
    """Register, update, or remove the scan job for a user based on their settings."""
    if _scheduler is None:
        return
    if _flask_app is None:
        return
    with _flask_app.app_context():
        settings = UserSettings.query.filter_by(username=username).first()
        if not settings:
            _remove_job(username)
            return
        _sync_job_for_settings(settings)


def _sync_job_for_settings(settings: UserSettings) -> None:
    username = settings.username
    job_id = _job_id(username)
    if not settings.scan_schedule_enabled:
        _remove_job(username)
        return
    trigger = _build_trigger(settings)
    if trigger is None:
        _remove_job(username)
        return
    job = _scheduler.add_job(
        func=_run_scan_for_user,
        trigger=trigger,
        args=[username],
        id=job_id,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    next_run = getattr(job, "next_run_time", None)
    logger.info(
        "Scheduled scan job for %s: trigger=%s next_run_time=%s",
        username, trigger, next_run,
    )


def get_next_run_time(username: str):
    """Return the next scheduled run time for a user's scan job, or None."""
    if _scheduler is None:
        return None
    try:
        job = _scheduler.get_job(_job_id(username))
    except Exception:
        return None
    if job is None:
        return None
    return getattr(job, "next_run_time", None)


def _remove_job(username: str) -> None:
    if _scheduler is None:
        return
    try:
        _scheduler.remove_job(_job_id(username))
        logger.info("Removed scan job for %s", username)
    except Exception:
        pass


LOG_RETENTION = 50  # keep the most recent N entries per user


def _reset_for_tests(app=None, scheduler=None) -> None:
    """Test helper — swap in a fake scheduler/app, or clear global state.

    This is called only from the test suite; production code uses
    ``init_scheduler`` instead.
    """
    global _scheduler, _flask_app
    _scheduler = scheduler
    _flask_app = app


def _run_scan_for_user(username: str) -> None:
    """Scheduled job body: warm the collection cache for a single user."""
    if _flask_app is None:
        logger.warning("Scheduler invoked without a bound Flask app")
        return
    with _flask_app.app_context():
        try:
            run_scan(username, trigger="scheduled")
        except Exception:
            logger.exception("Scheduled scan failed for user %s", username)


def run_scan(username: str, trigger: str = "manual") -> tuple[bool, str]:
    """Perform a scan for a user. Returns (success, message).

    Writes a ScanLog row documenting start/finish, items scanned, changed
    release count, and any error. Must be invoked within an app context.
    """
    log_entry = ScanLog(
        username=username,
        trigger=trigger,
        status="running",
        started_at=datetime.now(timezone.utc),
    )
    db.session.add(log_entry)
    db.session.commit()

    token = OAuthToken.query.filter_by(username=username).first()
    if not token:
        return _finish_log(log_entry, False, "No stored OAuth token")

    from flask import current_app
    service = DiscogsService(
        consumer_key=current_app.config["DISCOGS_CONSUMER_KEY"],
        consumer_secret=current_app.config["DISCOGS_CONSUMER_SECRET"],
        user_agent=current_app.config["USERAGENT"],
    )
    try:
        service.authenticate(token.access_token, token.access_token_secret)
        count = service.warm_cache(username, folder_id=0)
    except Exception as e:
        logger.exception("Scan failed for %s", username)
        return _finish_log(log_entry, False, f"Scan failed: {e}")

    changed_count = _count_changed(service, username)
    log_entry.items_scanned = count
    log_entry.changed_count = changed_count
    msg = f"Scanned {count} releases, {changed_count} changed since last processed"
    logger.info("Scan complete for %s: %s", username, msg)
    return _finish_log(log_entry, True, msg)


def _count_changed(service: DiscogsService, username: str) -> int:
    """Count releases whose current data differs from stored ProcessedRelease."""
    # Import lazily to avoid blueprint <-> scheduler import cycles at load time.
    from .blueprints.collection import _get_change_details

    try:
        items = service._get_cached_items(username, 0)
        releases = [item["release"] for item in items]
        return len(_get_change_details(releases))
    except Exception:
        logger.exception("Failed to compute changed-release count for %s", username)
        return 0


def _finish_log(log_entry: ScanLog, ok: bool, message: str) -> tuple[bool, str]:
    try:
        log_entry.finished_at = datetime.now(timezone.utc)
        log_entry.status = "success" if ok else "error"
        log_entry.message = message
        _update_user_settings_summary(log_entry.username, log_entry)
        db.session.commit()
        _trim_logs(log_entry.username)
    except Exception:
        db.session.rollback()
        logger.exception("Could not persist scan log for %s", log_entry.username)
    return ok, message


def _update_user_settings_summary(username: str, log_entry: ScanLog) -> None:
    settings = UserSettings.query.filter_by(username=username).first()
    if not settings:
        return
    settings.last_scan_at = log_entry.finished_at
    settings.last_scan_status = log_entry.message


def _trim_logs(username: str) -> None:
    """Keep only the most recent LOG_RETENTION entries per user."""
    try:
        old_ids = (
            ScanLog.query
            .filter_by(username=username)
            .order_by(ScanLog.started_at.desc())
            .with_entities(ScanLog.id)
            .offset(LOG_RETENTION)
            .all()
        )
        if old_ids:
            ScanLog.query.filter(
                ScanLog.id.in_([i[0] for i in old_ids])
            ).delete(synchronize_session=False)
            db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception("Could not trim scan logs for %s", username)
