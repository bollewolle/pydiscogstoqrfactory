from flask import (
    Blueprint,
    Response,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from ..extensions import db
from ..models import ScanLog, StickerLayout, UserSettings
from ..pdf_service import PDFService
from ..scheduler import (
    FREQUENCIES,
    WEEKDAY_LABELS,
    get_next_run_time,
    run_scan,
    sync_user_schedule,
)
from ..util_tz import (
    DEFAULT_TIMEZONE,
    is_valid_timezone,
    list_timezones,
    to_display,
)

settings_bp = Blueprint("settings", __name__, url_prefix="/settings")

DEFAULT_BOTTOM_TEXT = "{artist} \u2013 {title} [{year}]\n{discogs_folder}"

STANDARD_LAYOUTS = {
    "Default A4": {
        "page_width": 210.0, "page_height": 297.0,
        "sticker_width": 50.0, "sticker_height": 50.0,
        "margin_top": 7.8, "margin_left": 15.0,
        "spacing_x": 15.0, "spacing_y": 7.8,
    },
    "Avery L7120-25": {
        "page_width": 210.0, "page_height": 297.0,
        "sticker_width": 35.0, "sticker_height": 35.0,
        "margin_top": 17.6, "margin_left": 11.6,
        "spacing_x": 2.5, "spacing_y": 2.5,
    },
    "Avery L7121-25": {
        "page_width": 210.0, "page_height": 297.0,
        "sticker_width": 45.0, "sticker_height": 45.0,
        "margin_top": 26.0, "margin_left": 7.5,
        "spacing_x": 5.0, "spacing_y": 5.0,
    },
}


def _ensure_default_layouts(username: str) -> None:
    """Create standard sticker layouts if the user has none."""
    existing = StickerLayout.query.filter_by(username=username).first()
    if not existing:
        first_layout = None
        for name, dims in STANDARD_LAYOUTS.items():
            layout = StickerLayout(username=username, name=name, **dims)
            db.session.add(layout)
            if first_layout is None:
                first_layout = layout
        db.session.commit()
        # Set first layout as active
        if first_layout:
            settings = UserSettings.query.filter_by(username=username).first()
            if settings and not settings.active_layout_id:
                settings.active_layout_id = first_layout.id
                db.session.commit()


@settings_bp.route("/")
def index():
    """Show settings page."""
    username = session.get("username")
    if not username:
        flash("Please log in first.", "warning")
        return redirect(url_for("auth.login"))

    _ensure_default_layouts(username)

    settings = UserSettings.query.filter_by(username=username).first()
    bottom_text = settings.bottom_text_template if settings else DEFAULT_BOTTOM_TEXT
    printer_offset_top = settings.printer_offset_top if settings else 0.0
    printer_offset_left = settings.printer_offset_left if settings else 0.0

    layouts = StickerLayout.query.filter_by(username=username).all()
    active_layout_id = settings.active_layout_id if settings else None

    display_tz = (settings.display_timezone if settings else None) or DEFAULT_TIMEZONE

    scan_schedule = {
        "enabled": bool(settings and settings.scan_schedule_enabled),
        "frequency": (settings.scan_frequency if settings else None) or "daily",
        "hour": settings.scan_hour if settings and settings.scan_hour is not None else 3,
        "minute": settings.scan_minute if settings and settings.scan_minute is not None else 0,
        "day_of_week": settings.scan_day_of_week if settings and settings.scan_day_of_week is not None else 0,
        "day_of_month": settings.scan_day_of_month if settings and settings.scan_day_of_month is not None else 1,
        "month_of_year": settings.scan_month_of_year if settings and settings.scan_month_of_year is not None else 1,
        "last_scan_at": to_display(settings.last_scan_at if settings else None, display_tz),
        "last_scan_status": settings.last_scan_status if settings else None,
        "next_run_time": to_display(get_next_run_time(username), display_tz),
    }

    scan_log_rows = (
        ScanLog.query
        .filter_by(username=username)
        .order_by(ScanLog.started_at.desc())
        .limit(20)
        .all()
    )
    # Pre-convert timestamps to the user's tz so the template can render plain strftime.
    scan_logs = [
        {
            "started_at": to_display(log.started_at, display_tz),
            "trigger": log.trigger,
            "status": log.status,
            "duration_seconds": log.duration_seconds,
            "items_scanned": log.items_scanned,
            "changed_count": log.changed_count,
            "message": log.message,
        }
        for log in scan_log_rows
    ]

    return render_template(
        "settings/index.html",
        bottom_text=bottom_text,
        default_bottom_text=DEFAULT_BOTTOM_TEXT,
        layouts=layouts,
        active_layout_id=active_layout_id,
        standard_layouts=STANDARD_LAYOUTS,
        printer_offset_top=printer_offset_top,
        printer_offset_left=printer_offset_left,
        display_tz=display_tz,
        available_timezones=list_timezones(),
        scan_schedule=scan_schedule,
        scan_frequencies=FREQUENCIES,
        weekday_labels=WEEKDAY_LABELS,
        scan_logs=scan_logs,
    )


@settings_bp.route("/save", methods=["POST"])
def save():
    """Save settings."""
    username = session.get("username")
    if not username:
        flash("Please log in first.", "warning")
        return redirect(url_for("auth.login"))

    bottom_text = request.form.get("bottom_text_template", DEFAULT_BOTTOM_TEXT)
    active_layout_id = request.form.get("active_layout_id", type=int)
    printer_offset_top = request.form.get("printer_offset_top", 0.0, type=float)
    printer_offset_left = request.form.get("printer_offset_left", 0.0, type=float)
    display_timezone = request.form.get("display_timezone", DEFAULT_TIMEZONE)
    if not is_valid_timezone(display_timezone):
        display_timezone = DEFAULT_TIMEZONE

    settings = UserSettings.query.filter_by(username=username).first()
    tz_changed = False
    if settings:
        tz_changed = settings.display_timezone != display_timezone
        settings.bottom_text_template = bottom_text
        settings.printer_offset_top = printer_offset_top
        settings.printer_offset_left = printer_offset_left
        settings.display_timezone = display_timezone
        if active_layout_id:
            settings.active_layout_id = active_layout_id
    else:
        settings = UserSettings(
            username=username,
            bottom_text_template=bottom_text,
            active_layout_id=active_layout_id,
            printer_offset_top=printer_offset_top,
            printer_offset_left=printer_offset_left,
            display_timezone=display_timezone,
        )
        db.session.add(settings)
        tz_changed = display_timezone != DEFAULT_TIMEZONE

    db.session.commit()
    # If the timezone changed, an existing scheduled job still has the old
    # CronTrigger. Re-sync so it is rebuilt with the new tz.
    if tz_changed and settings.scan_schedule_enabled:
        try:
            sync_user_schedule(username)
        except Exception:
            current_app.logger.exception(
                "Failed to re-sync scan schedule after timezone change for %s", username
            )
    flash("Settings saved.", "success")
    return redirect(url_for("settings.index"))


@settings_bp.route("/schedule/save", methods=["POST"])
def save_schedule():
    """Save scheduled collection scan preferences."""
    username = session.get("username")
    if not username:
        flash("Please log in first.", "warning")
        return redirect(url_for("auth.login"))

    schedule_fields = _parse_schedule_form(request.form)

    settings = UserSettings.query.filter_by(username=username).first()
    if settings:
        for field, value in schedule_fields.items():
            setattr(settings, field, value)
    else:
        settings = UserSettings(username=username, **schedule_fields)
        db.session.add(settings)

    db.session.commit()
    try:
        sync_user_schedule(username)
    except Exception:
        current_app.logger.exception("Failed to sync scan schedule for %s", username)
    flash("Scan schedule saved.", "success")
    return redirect(url_for("settings.index"))


def _parse_schedule_form(form) -> dict:
    """Extract scheduled-scan fields from the settings form."""
    enabled = form.get("scan_schedule_enabled") == "1"
    frequency = form.get("scan_frequency", "daily")
    if frequency not in FREQUENCIES:
        frequency = "daily"

    def _int_or_none(name: str, default: int, lo: int, hi: int) -> int:
        val = form.get(name, type=int)
        if val is None:
            val = default
        return max(lo, min(hi, val))

    return {
        "scan_schedule_enabled": enabled,
        "scan_frequency": frequency,
        "scan_hour": _int_or_none("scan_hour", 3, 0, 23),
        "scan_minute": _int_or_none("scan_minute", 0, 0, 59),
        "scan_day_of_week": _int_or_none("scan_day_of_week", 0, 0, 6),
        "scan_day_of_month": _int_or_none("scan_day_of_month", 1, 1, 31),
        "scan_month_of_year": _int_or_none("scan_month_of_year", 1, 1, 12),
    }


@settings_bp.route("/scan-now", methods=["POST"])
def scan_now():
    """Trigger an on-demand collection scan for the logged-in user."""
    username = session.get("username")
    if not username:
        flash("Please log in first.", "warning")
        return redirect(url_for("auth.login"))

    ok, msg = run_scan(username, trigger="manual")
    flash(msg, "success" if ok else "error")
    return redirect(url_for("settings.index"))


@settings_bp.route("/scan-logs/clear", methods=["POST"])
def clear_scan_logs():
    """Delete all scan log entries for the logged-in user."""
    username = session.get("username")
    if not username:
        flash("Please log in first.", "warning")
        return redirect(url_for("auth.login"))

    deleted = ScanLog.query.filter_by(username=username).delete()
    db.session.commit()
    flash(f"Cleared {deleted} scan log entries.", "success")
    return redirect(url_for("settings.index"))


@settings_bp.route("/layout/add", methods=["POST"])
def add_layout():
    """Add a new sticker layout."""
    username = session.get("username")
    if not username:
        flash("Please log in first.", "warning")
        return redirect(url_for("auth.login"))

    layout = StickerLayout(
        username=username,
        name=request.form.get("name", "New Layout"),
        page_width=request.form.get("page_width", 210.0, type=float),
        page_height=request.form.get("page_height", 297.0, type=float),
        sticker_width=request.form.get("sticker_width", 50.0, type=float),
        sticker_height=request.form.get("sticker_height", 50.0, type=float),
        margin_top=request.form.get("margin_top", 10.0, type=float),
        margin_left=request.form.get("margin_left", 10.0, type=float),
        spacing_x=request.form.get("spacing_x", 5.0, type=float),
        spacing_y=request.form.get("spacing_y", 5.0, type=float),
    )
    db.session.add(layout)
    db.session.commit()
    flash(f'Layout "{layout.name}" created.', "success")
    return redirect(url_for("settings.index"))


@settings_bp.route("/layout/<int:layout_id>/edit", methods=["POST"])
def edit_layout(layout_id):
    """Update a sticker layout."""
    username = session.get("username")
    if not username:
        flash("Please log in first.", "warning")
        return redirect(url_for("auth.login"))

    layout = StickerLayout.query.filter_by(id=layout_id, username=username).first()
    if not layout:
        flash("Layout not found.", "error")
        return redirect(url_for("settings.index"))

    layout.name = request.form.get("name", layout.name)
    layout.page_width = request.form.get("page_width", layout.page_width, type=float)
    layout.page_height = request.form.get("page_height", layout.page_height, type=float)
    layout.sticker_width = request.form.get("sticker_width", layout.sticker_width, type=float)
    layout.sticker_height = request.form.get("sticker_height", layout.sticker_height, type=float)
    layout.margin_top = request.form.get("margin_top", layout.margin_top, type=float)
    layout.margin_left = request.form.get("margin_left", layout.margin_left, type=float)
    layout.spacing_x = request.form.get("spacing_x", layout.spacing_x, type=float)
    layout.spacing_y = request.form.get("spacing_y", layout.spacing_y, type=float)
    db.session.commit()
    flash(f'Layout "{layout.name}" updated.', "success")
    return redirect(url_for("settings.index"))


@settings_bp.route("/layout/<int:layout_id>/delete", methods=["POST"])
def delete_layout(layout_id):
    """Delete a sticker layout."""
    username = session.get("username")
    if not username:
        flash("Please log in first.", "warning")
        return redirect(url_for("auth.login"))

    layout = StickerLayout.query.filter_by(id=layout_id, username=username).first()
    if not layout:
        flash("Layout not found.", "error")
        return redirect(url_for("settings.index"))

    # Clear active_layout_id if this was the active one
    settings = UserSettings.query.filter_by(username=username).first()
    if settings and settings.active_layout_id == layout_id:
        settings.active_layout_id = None

    db.session.delete(layout)
    db.session.commit()
    flash(f'Layout "{layout.name}" deleted.', "success")
    return redirect(url_for("settings.index"))


@settings_bp.route("/layout/<int:layout_id>/info")
def layout_info(layout_id):
    """Return layout info as JSON (for AJAX)."""
    username = session.get("username")
    if not username:
        return jsonify({"error": "Not logged in"}), 401

    layout = StickerLayout.query.filter_by(id=layout_id, username=username).first()
    if not layout:
        return jsonify({"error": "Not found"}), 404

    return jsonify(layout.to_dict())


@settings_bp.route("/test-page", methods=["POST"])
def test_page():
    """Generate a test page PDF for the active sticker layout."""
    username = session.get("username")
    if not username:
        flash("Please log in first.", "warning")
        return redirect(url_for("auth.login"))

    settings = UserSettings.query.filter_by(username=username).first()
    if not settings or not settings.active_layout_id:
        flash("No active layout selected. Please select one first.", "warning")
        return redirect(url_for("settings.index"))

    layout_model = db.session.get(StickerLayout, settings.active_layout_id)
    if not layout_model:
        flash("Active layout not found.", "error")
        return redirect(url_for("settings.index"))

    layout = layout_model.to_dict()
    pdf_service = PDFService(
        current_app.config["LOGO_PATH"],
        current_app.config["CSV_TEMPLATE_PATH"],
    )
    pdf_bytes = pdf_service.generate_test_page(
        layout,
        printer_offset_top=settings.printer_offset_top,
        printer_offset_left=settings.printer_offset_left,
    )

    return Response(
        bytes(pdf_bytes),
        mimetype="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="test_page_{layout_model.name}.pdf"'
        },
    )
