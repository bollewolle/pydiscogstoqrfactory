from datetime import date

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

from ..extensions import db
from ..models import ProcessedRelease
from .auth import get_authenticated_service

collection_bp = Blueprint("collection", __name__)


@collection_bp.route("/")
def landing():
    """Landing page with authentication status and navigation options."""
    authenticated = bool(session.get("username"))
    username = session.get("username", "")
    return render_template(
        "landing.html", authenticated=authenticated, username=username
    )


@collection_bp.route("/collection/folders")
def folders():
    """List all collection folders."""
    service = get_authenticated_service()
    if not service:
        flash("Please log in first.", "warning")
        return redirect(url_for("auth.login"))

    username = session["username"]
    try:
        folder_list = service.get_folders(username)
    except Exception as e:
        flash(f"Failed to retrieve folders: {e}", "error")
        return redirect(url_for("collection.landing"))

    # Determine which folders are fully processed
    processed_ids = _get_processed_ids()
    all_others_processed = True
    for folder in folder_list:
        if folder["name"] == "All":
            continue
        folder["fully_processed"] = _is_folder_fully_processed(
            service, username, folder, processed_ids,
        )
        if not folder["fully_processed"]:
            all_others_processed = False

    # "All" folder is fully processed when every other folder is
    for folder in folder_list:
        if folder["name"] == "All":
            folder["fully_processed"] = folder["count"] > 0 and all_others_processed

    return render_template("collection/folders.html", folders=folder_list)


@collection_bp.route("/collection/folders/<int:folder_id>")
def folder_releases(folder_id: int):
    """Browse releases in a specific folder."""
    service = get_authenticated_service()
    if not service:
        flash("Please log in first.", "warning")
        return redirect(url_for("auth.login"))

    username = session["username"]
    sort = request.args.get("sort", "artist")
    order = request.args.get("order", "asc")
    letter = request.args.get("letter", "")
    hide_processed = request.args.get("hide_processed", "") == "1"

    try:
        releases = service.get_folder_releases(username, folder_id, sort, order)
        folder_list = service.get_folders(username)
        folder_name = next(
            (f["name"] for f in folder_list if f["id"] == folder_id), "Folder"
        )
    except Exception as e:
        flash(f"Failed to retrieve releases: {e}", "error")
        return redirect(url_for("collection.folders"))

    # Filter by starting letter if specified
    if letter:
        releases = [
            r for r in releases if r["artist"].upper().startswith(letter.upper())
        ]

    # Get processed release IDs
    processed_ids = _get_processed_ids()

    # Filter out processed releases if requested
    if hide_processed:
        releases = [r for r in releases if r["id"] not in processed_ids]

    # Get unique starting letters for the letter bar
    letters = sorted({r["artist"][0].upper() for r in releases if r["artist"]})

    return render_template(
        "collection/releases.html",
        releases=releases,
        folder_id=folder_id,
        folder_name=folder_name,
        sort=sort,
        order=order,
        letter=letter,
        letters=letters,
        processed_ids=processed_ids,
        hide_processed=hide_processed,
    )


@collection_bp.route("/collection/latest", methods=["GET", "POST"])
def latest():
    """Show releases added since a specific date."""
    if request.method == "GET":
        return render_template("collection/latest.html", releases=None)

    service = get_authenticated_service()
    if not service:
        flash("Please log in first.", "warning")
        return redirect(url_for("auth.login"))

    username = session["username"]
    since_str = request.form.get("since_date", "")
    if not since_str:
        flash("Please select a date.", "warning")
        return render_template("collection/latest.html", releases=None)

    try:
        since_date = date.fromisoformat(since_str)
    except ValueError:
        flash("Invalid date format.", "error")
        return render_template("collection/latest.html", releases=None)

    try:
        releases = service.get_releases_since(username, since_date)
    except Exception as e:
        flash(f"Failed to retrieve releases: {e}", "error")
        return render_template("collection/latest.html", releases=None)

    sort = request.form.get("sort", "date_added")
    order = request.form.get("order", "desc")
    hide_processed = request.form.get("hide_processed", "") == "1"
    releases = _sort_releases(releases, sort, order)

    processed_ids = _get_processed_ids()

    # Filter out processed releases if requested
    if hide_processed:
        releases = [r for r in releases if r["id"] not in processed_ids]

    letters = sorted({r["artist"][0].upper() for r in releases if r["artist"]})

    return render_template(
        "collection/latest.html",
        releases=releases,
        since_date=since_str,
        sort=sort,
        order=order,
        hide_processed=hide_processed,
        letters=letters,
        processed_ids=processed_ids,
    )


@collection_bp.route("/collection/formats")
def formats():
    """List unique format names in the user's collection."""
    service = get_authenticated_service()
    if not service:
        flash("Please log in first.", "warning")
        return redirect(url_for("auth.login"))

    username = session["username"]
    try:
        format_list = service.get_collection_formats(username)
    except Exception as e:
        flash(f"Failed to retrieve formats: {e}", "error")
        return redirect(url_for("collection.landing"))

    return render_template("collection/formats.html", formats=format_list)


@collection_bp.route("/collection/formats/sizes")
def format_sizes():
    """List sizes for a specific format, or redirect to releases if no sizes."""
    service = get_authenticated_service()
    if not service:
        flash("Please log in first.", "warning")
        return redirect(url_for("auth.login"))

    format_name = request.args.get("name", "")
    if not format_name:
        flash("No format specified.", "warning")
        return redirect(url_for("collection.formats"))

    username = session["username"]
    try:
        sizes = service.get_format_sizes(username, format_name)
    except Exception as e:
        flash(f"Failed to retrieve sizes: {e}", "error")
        return redirect(url_for("collection.formats"))

    if not sizes:
        return redirect(url_for("collection.format_releases", name=format_name))

    return render_template(
        "collection/format_sizes.html",
        format_name=format_name,
        sizes=sizes,
    )


@collection_bp.route("/collection/formats/releases")
def format_releases():
    """Browse releases matching a specific format, optional size, and description filters."""
    service = get_authenticated_service()
    if not service:
        flash("Please log in first.", "warning")
        return redirect(url_for("auth.login"))

    username = session["username"]
    format_name = request.args.get("name", "")
    size = request.args.get("size", "")
    active_filters = request.args.getlist("desc")
    sort = request.args.get("sort", "artist")
    order = request.args.get("order", "asc")
    hide_processed = request.args.get("hide_processed", "") == "1"

    if not format_name:
        flash("No format specified.", "warning")
        return redirect(url_for("collection.formats"))

    try:
        releases, available_descriptions = service.get_releases_by_format(
            username, format_name, size, active_filters or None
        )
    except Exception as e:
        flash(f"Failed to retrieve releases: {e}", "error")
        return redirect(url_for("collection.formats"))

    releases = _sort_releases(releases, sort, order)

    processed_ids = _get_processed_ids()

    if hide_processed:
        releases = [r for r in releases if r["id"] not in processed_ids]

    letters = sorted({r["artist"][0].upper() for r in releases if r["artist"]})

    # Build a display label
    label_parts = [format_name]
    if size:
        label_parts.append(size)
    format_label = " - ".join(label_parts)

    return render_template(
        "collection/format_releases.html",
        releases=releases,
        format_name=format_name,
        format_label=format_label,
        size=size,
        available_descriptions=available_descriptions,
        active_filters=active_filters,
        sort=sort,
        order=order,
        letters=letters,
        processed_ids=processed_ids,
        hide_processed=hide_processed,
    )


def _get_processed_ids() -> set[int]:
    """Get set of already-processed release IDs."""
    processed = ProcessedRelease.query.with_entities(
        ProcessedRelease.discogs_release_id
    ).all()
    return {p.discogs_release_id for p in processed}


def _is_folder_fully_processed(service, username, folder, processed_ids) -> bool:
    """Check if all releases in a folder are processed.

    Uses cached release data when available (compares actual release IDs).
    Falls back to comparing the folder's release count against the number
    of processed releases with a matching folder name in the database.
    """
    if folder["count"] == 0:
        return False

    # Try cached data first (no API call)
    cached_ids = service.get_cached_folder_release_ids(username, folder["id"])
    if cached_ids is not None:
        return cached_ids.issubset(processed_ids)

    # Fallback: count processed releases by folder name in DB
    count = ProcessedRelease.query.filter_by(
        folder_name=folder["name"]
    ).count()
    return count >= folder["count"]


def _sort_releases(releases: list[dict], sort: str, order: str) -> list[dict]:
    """Sort releases by the given criteria."""
    reverse = order == "desc"
    key_map = {
        "artist": lambda r: r.get("artist", "").lower(),
        "year": lambda r: r.get("year", 0),
        "date_added": lambda r: r.get("date_added", ""),
    }
    key_func = key_map.get(sort, key_map["artist"])
    return sorted(releases, key=key_func, reverse=reverse)
