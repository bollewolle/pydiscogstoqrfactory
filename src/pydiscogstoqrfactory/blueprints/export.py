import json

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from ..csv_service import CSVService
from ..extensions import db
from ..models import ProcessedRelease, UserSettings

export_bp = Blueprint("export", __name__, url_prefix="/export")


def _get_csv_service() -> CSVService:
    return CSVService(current_app.config["CSV_TEMPLATE_PATH"])


@export_bp.route("/preview", methods=["POST"])
def preview():
    """Preview CSV output for selected releases."""
    releases_json = request.form.get("releases_data")
    if not releases_json:
        flash("No releases selected.", "warning")
        return redirect(url_for("collection.landing"))

    try:
        releases = json.loads(releases_json)
    except (json.JSONDecodeError, TypeError):
        flash("Invalid release data.", "error")
        return redirect(url_for("collection.landing"))

    csv_service = _get_csv_service()

    # Use custom BottomText template if the user has one
    username = session.get("username", "")
    bottom_text = None
    if username:
        settings = UserSettings.query.filter_by(username=username).first()
        if settings:
            bottom_text = settings.bottom_text_template

    rows = csv_service.generate_rows(releases, bottom_text_template=bottom_text)

    # Store in session for subsequent edit/download
    session["preview_releases"] = releases
    session["preview_rows"] = rows

    return render_template(
        "export/preview.html",
        rows=rows,
        header=csv_service.header,
        releases=releases,
    )


@export_bp.route("/edit", methods=["POST"])
def edit():
    """Edit CSV data before download."""
    releases = session.get("preview_releases")
    rows = session.get("preview_rows")

    if not rows:
        flash("No preview data found. Please select releases again.", "warning")
        return redirect(url_for("collection.landing"))

    csv_service = _get_csv_service()

    # Editable columns
    editable_cols = ["BottomText", "Content", "FileName"]

    return render_template(
        "export/edit.html",
        rows=rows,
        header=csv_service.header,
        editable_cols=editable_cols,
        releases=session.get("preview_releases", []),
    )


@export_bp.route("/download", methods=["POST"])
def download():
    """Download CSV file."""
    rows_json = request.form.get("rows_data")
    if rows_json:
        try:
            rows = json.loads(rows_json)
        except (json.JSONDecodeError, TypeError):
            flash("Invalid CSV data.", "error")
            return redirect(url_for("collection.landing"))
    else:
        rows = session.get("preview_rows")

    if not rows:
        flash("No data to download. Please select releases first.", "warning")
        return redirect(url_for("collection.landing"))

    csv_service = _get_csv_service()
    return csv_service.to_csv_response(rows)


@export_bp.route("/mark-processed", methods=["POST"])
def mark_processed():
    """Mark selected releases as processed in the database."""
    releases_json = request.form.get("releases_data")
    if not releases_json:
        flash("No releases to mark.", "warning")
        return redirect(url_for("collection.landing"))

    try:
        releases = json.loads(releases_json)
    except (json.JSONDecodeError, TypeError):
        flash("Invalid release data.", "error")
        return redirect(url_for("collection.landing"))

    username = session.get("username", "")
    count = 0
    for release in releases:
        existing = ProcessedRelease.query.filter_by(
            discogs_release_id=release["id"]
        ).first()
        if not existing:
            processed = ProcessedRelease(
                discogs_release_id=release["id"],
                artist=release.get("artist", ""),
                title=release.get("title", ""),
                year=release.get("year"),
                folder_name=release.get("discogs_folder", ""),
                username=username,
            )
            db.session.add(processed)
            count += 1

    db.session.commit()
    flash(f"Marked {count} release(s) as processed.", "success")
    return redirect(url_for("collection.landing"))


@export_bp.route("/unmark-processed", methods=["POST"])
def unmark_processed():
    """Remove the processed status from selected releases."""
    releases_json = request.form.get("releases_data")
    if not releases_json:
        flash("No releases selected.", "warning")
        return redirect(request.referrer or url_for("collection.landing"))

    try:
        releases = json.loads(releases_json)
    except (json.JSONDecodeError, TypeError):
        flash("Invalid release data.", "error")
        return redirect(request.referrer or url_for("collection.landing"))

    release_ids = [r["id"] for r in releases if "id" in r]
    if not release_ids:
        flash("No valid releases to unmark.", "warning")
        return redirect(request.referrer or url_for("collection.landing"))

    count = ProcessedRelease.query.filter(
        ProcessedRelease.discogs_release_id.in_(release_ids)
    ).delete(synchronize_session="fetch")
    db.session.commit()

    flash(f"Removed processed status from {count} release(s).", "success")
    return redirect(request.referrer or url_for("collection.landing"))


@export_bp.route("/clear-session", methods=["POST"])
def clear_session():
    """Clear session data (selection, preview) but keep auth."""
    access_token = session.get("access_token")
    access_secret = session.get("access_secret")
    username = session.get("username")

    session.clear()

    # Restore auth data
    if access_token:
        session["access_token"] = access_token
    if access_secret:
        session["access_secret"] = access_secret
    if username:
        session["username"] = username

    flash("Session data cleared.", "info")
    return redirect(url_for("collection.landing"))
