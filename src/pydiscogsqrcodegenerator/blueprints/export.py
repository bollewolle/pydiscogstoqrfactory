import json

from flask import (
    Blueprint,
    Response,
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
from ..models import ProcessedRelease, StickerLayout, UserSettings
from ..pdf_service import PDFService

export_bp = Blueprint("export", __name__, url_prefix="/export")


def _get_csv_service() -> CSVService:
    return CSVService(current_app.config["CSV_TEMPLATE_PATH"])


def _get_pdf_service() -> PDFService:
    return PDFService(
        current_app.config["LOGO_PATH"],
        current_app.config["CSV_TEMPLATE_PATH"],
    )


def _parse_breadcrumbs(form_data):
    """Parse breadcrumbs JSON from form data."""
    breadcrumbs_json = form_data.get("breadcrumbs", "[]")
    try:
        return json.loads(breadcrumbs_json)
    except (json.JSONDecodeError, TypeError):
        return []


@export_bp.route("/preview", methods=["POST"])
def preview():
    """Preview QR Factory 3 CSV output for selected releases."""
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

    # Parse source breadcrumbs and store in session for edit page
    source_breadcrumbs = _parse_breadcrumbs(request.form)
    session["source_breadcrumbs"] = source_breadcrumbs

    breadcrumbs = source_breadcrumbs + [{"label": "QR Factory 3 CSV Preview"}]

    # Store in session for subsequent edit/download
    session["preview_releases"] = releases
    session["preview_rows"] = rows

    return render_template(
        "export/preview.html",
        rows=rows,
        header=csv_service.header,
        releases=releases,
        breadcrumbs=breadcrumbs,
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

    source_breadcrumbs = session.get("source_breadcrumbs", [])
    breadcrumbs = source_breadcrumbs + [
        {"label": "QR Factory 3 CSV Preview", "url": "javascript:history.back()"},
        {"label": "Edit CSV"},
    ]

    return render_template(
        "export/edit.html",
        rows=rows,
        header=csv_service.header,
        editable_cols=editable_cols,
        releases=session.get("preview_releases", []),
        breadcrumbs=breadcrumbs,
    )


@export_bp.route("/download", methods=["POST"])
def download():
    """Download QR Factory 3 CSV file."""
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
        folder_name = release.get("discogs_folder", "")
        existing = ProcessedRelease.query.filter_by(
            discogs_release_id=release["id"]
        ).first()
        if not existing:
            processed = ProcessedRelease(
                discogs_release_id=release["id"],
                artist=release.get("artist", ""),
                title=release.get("title", ""),
                year=release.get("year"),
                folder_name=folder_name,
                username=username,
            )
            db.session.add(processed)
            count += 1
        elif folder_name and existing.folder_name != folder_name:
            # Fix folder name if it was previously stored incorrectly
            existing.folder_name = folder_name

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


@export_bp.route("/preview-pdf", methods=["POST"])
def preview_pdf():
    """Preview QR PDF sticker sheet — shows a grid of stickers that can be toggled."""
    releases_json = request.form.get("releases_data")
    if not releases_json:
        flash("No releases selected.", "warning")
        return redirect(url_for("collection.landing"))

    try:
        releases = json.loads(releases_json)
    except (json.JSONDecodeError, TypeError):
        flash("Invalid release data.", "error")
        return redirect(url_for("collection.landing"))

    username = session.get("username", "")
    settings = UserSettings.query.filter_by(username=username).first() if username else None
    bottom_text_template = settings.bottom_text_template if settings else None

    # Get active layout
    layout = None
    if settings and settings.active_layout_id:
        layout_model = db.session.get(StickerLayout, settings.active_layout_id)
        if layout_model:
            layout = layout_model.to_dict()

    if not layout:
        # Fallback default layout values
        layout = {
            "id": None, "name": "Default",
            "page_width": 210.0, "page_height": 297.0,
            "sticker_width": 50.0, "sticker_height": 50.0,
            "margin_top": 7.8, "margin_left": 15.0,
            "spacing_x": 15.0, "spacing_y": 7.8,
            "cols": 3, "rows": 5, "stickers_per_page": 15,
        }

    # Get all user layouts for the dropdown
    layouts = []
    if username:
        layouts = [l.to_dict() for l in StickerLayout.query.filter_by(username=username).all()]

    # Generate BottomText for each release using CSVService
    csv_service = _get_csv_service()
    rows = csv_service.generate_rows(releases, bottom_text_template=bottom_text_template)
    bottom_texts = [row.get("BottomText", "") for row in rows]

    # Store in session for subsequent download
    session["pdf_releases"] = releases
    session["pdf_bottom_texts"] = bottom_texts

    pdf_service = _get_pdf_service()
    layout_info = pdf_service.compute_layout_info(layout, len(releases))

    source_breadcrumbs = _parse_breadcrumbs(request.form)
    breadcrumbs = source_breadcrumbs + [{"label": "Preview QR Code PDF"}]

    return render_template(
        "export/preview_pdf.html",
        releases=releases,
        bottom_texts=bottom_texts,
        layout=layout,
        layouts=layouts,
        layout_info=layout_info,
        breadcrumbs=breadcrumbs,
    )


@export_bp.route("/generate-pdf", methods=["POST"])
def generate_pdf():
    """Generate and return the PDF file."""
    releases = session.get("pdf_releases")
    bottom_texts = session.get("pdf_bottom_texts")

    if not releases:
        flash("No release data found. Please select releases again.", "warning")
        return redirect(url_for("collection.landing"))

    # Get active slot indices from form
    active_json = request.form.get("active_indices", "[]")
    try:
        active_indices = json.loads(active_json)
    except (json.JSONDecodeError, TypeError):
        active_indices = list(range(len(releases)))

    # Get total slots from form
    total_slots = request.form.get("total_slots", type=int)

    # Get layout from form or session
    layout_json = request.form.get("layout_data")
    if layout_json:
        try:
            layout = json.loads(layout_json)
        except (json.JSONDecodeError, TypeError):
            layout = {
            "page_width": 210.0, "page_height": 297.0,
            "sticker_width": 50.0, "sticker_height": 50.0,
            "margin_top": 7.8, "margin_left": 15.0,
            "spacing_x": 15.0, "spacing_y": 7.8,
        }
    else:
        layout = {
            "page_width": 210.0, "page_height": 297.0,
            "sticker_width": 50.0, "sticker_height": 50.0,
            "margin_top": 7.8, "margin_left": 15.0,
            "spacing_x": 15.0, "spacing_y": 7.8,
        }

    username = session.get("username", "")
    settings = UserSettings.query.filter_by(username=username).first() if username else None
    bottom_text_template = settings.bottom_text_template if settings else None
    printer_offset_top = settings.printer_offset_top if settings else 0.0
    printer_offset_left = settings.printer_offset_left if settings else 0.0

    pdf_service = _get_pdf_service()
    pdf_bytes = pdf_service.generate_pdf(
        releases, active_indices, layout, bottom_text_template,
        total_slots=total_slots,
        printer_offset_top=printer_offset_top,
        printer_offset_left=printer_offset_left,
    )

    return Response(
        bytes(pdf_bytes),
        mimetype="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="qr_stickers.pdf"'},
    )


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
