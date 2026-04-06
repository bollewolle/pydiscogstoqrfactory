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
    has_changes_count = 0
    if authenticated:
        service = get_authenticated_service()
        if service:
            # Only compute when cache is warm (no extra API calls)
            cached_ids = service.get_cached_folder_release_ids(username, 0)
            if cached_ids is not None:
                items = service._get_cached_items(username, 0)
                releases = [item["release"] for item in items]
                has_changes_count = len(_get_changed_ids(releases))
    return render_template(
        "landing.html", authenticated=authenticated, username=username,
        has_changes_count=has_changes_count,
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

    # Determine which folders are fully processed and have changes
    processed_ids = _get_processed_ids()
    all_others_processed = True
    any_others_changed = False
    for folder in folder_list:
        if folder["name"] == "All":
            continue
        folder["fully_processed"] = _is_folder_fully_processed(
            service, username, folder, processed_ids,
        )
        folder["has_changes"] = _folder_has_changes(
            service, username, folder,
        )
        if not folder["fully_processed"]:
            all_others_processed = False
        if folder["has_changes"]:
            any_others_changed = True

    # "All" folder is fully processed when every other folder is
    for folder in folder_list:
        if folder["name"] == "All":
            folder["fully_processed"] = folder["count"] > 0 and all_others_processed
            folder["has_changes"] = any_others_changed

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

    # Get processed release IDs and change detection
    processed_ids = _get_processed_ids()
    change_details = _get_change_details(releases)
    processed_at_map = _get_processed_at_map()

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
        change_details=change_details,
        processed_at_map=processed_at_map,
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
    change_details = _get_change_details(releases)
    processed_at_map = _get_processed_at_map()

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
        change_details=change_details,
        processed_at_map=processed_at_map,
    )


@collection_bp.route("/collection/changed")
def changed_releases():
    """Show processed releases that have changed since processing."""
    service = get_authenticated_service()
    if not service:
        flash("Please log in first.", "warning")
        return redirect(url_for("auth.login"))

    username = session["username"]
    sort = request.args.get("sort", "artist")
    order = request.args.get("order", "asc")
    letter = request.args.get("letter", "")

    try:
        releases = service.get_folder_releases(username, 0, sort, order)
    except Exception as e:
        flash(f"Failed to retrieve releases: {e}", "error")
        return redirect(url_for("collection.landing"))

    change_details = _get_change_details(releases)
    processed_ids = _get_processed_ids()
    processed_at_map = _get_processed_at_map()

    # Filter to only changed releases
    releases = [r for r in releases if r["id"] in change_details]
    releases = _sort_releases(releases, sort, order)

    # Filter by starting letter if specified
    if letter:
        releases = [
            r for r in releases if r["artist"].upper().startswith(letter.upper())
        ]

    letters = sorted({r["artist"][0].upper() for r in releases if r["artist"]})

    return render_template(
        "collection/changed.html",
        releases=releases,
        sort=sort,
        order=order,
        letter=letter,
        letters=letters,
        processed_ids=processed_ids,
        change_details=change_details,
        processed_at_map=processed_at_map,
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

    # Determine which formats have changed releases
    try:
        items = service._get_cached_items(username, 0)
        all_releases = [item["release"] for item in items]
        all_changed_ids = _get_changed_ids(all_releases)

        # Build format_name -> set of release IDs
        format_release_ids: dict[str, set[int]] = {}
        for item in items:
            for fmt in item["formats"]:
                fname = fmt.get("name", "Unknown")
                format_release_ids.setdefault(fname, set()).add(item["release"]["id"])

        for fmt in format_list:
            rids = format_release_ids.get(fmt["name"], set())
            fmt["has_changes"] = bool(rids & all_changed_ids)
    except Exception:
        for fmt in format_list:
            fmt["has_changes"] = False

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

    # Determine which sizes have changed releases
    try:
        items = service._get_cached_items(username, 0)
        all_releases = [item["release"] for item in items]
        all_changed_ids = _get_changed_ids(all_releases)

        # Build size -> set of release IDs for this format
        size_release_ids: dict[str, set[int]] = {}
        for item in items:
            for fmt in item["formats"]:
                if fmt.get("name") != format_name:
                    continue
                descs = fmt.get("descriptions", [])
                from ..discogs_service import DiscogsService
                inferred = DiscogsService._infer_size(descs)
                size_key = inferred or "Unknown"
                size_release_ids.setdefault(size_key, set()).add(item["release"]["id"])

        for size_item in sizes:
            rids = size_release_ids.get(size_item["size"], set())
            size_item["has_changes"] = bool(rids & all_changed_ids)
    except Exception:
        for size_item in sizes:
            size_item["has_changes"] = False

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
    change_details = _get_change_details(releases)
    processed_at_map = _get_processed_at_map()

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
        change_details=change_details,
        processed_at_map=processed_at_map,
        hide_processed=hide_processed,
    )


def _get_processed_ids() -> set[int]:
    """Get set of already-processed release IDs."""
    processed = ProcessedRelease.query.with_entities(
        ProcessedRelease.discogs_release_id
    ).all()
    return {p.discogs_release_id for p in processed}


def _get_processed_at_map() -> dict[int, str]:
    """Get mapping of release ID to formatted processed_at timestamp."""
    rows = ProcessedRelease.query.with_entities(
        ProcessedRelease.discogs_release_id, ProcessedRelease.processed_at
    ).all()
    return {
        r.discogs_release_id: r.processed_at.strftime("%Y-%m-%d %H:%M")
        if r.processed_at else ""
        for r in rows
    }


def _get_change_details(releases: list[dict]) -> dict[int, list[str]]:
    """Compare current release data against stored processed data.

    Returns dict mapping discogs_release_id to a list of human-readable
    change descriptions (e.g. 'Artist: "Old" → "New"').
    Only includes releases that have actual changes.
    """
    release_ids = [r["id"] for r in releases]
    if not release_ids:
        return {}

    processed_map = {
        p.discogs_release_id: p
        for p in ProcessedRelease.query.filter(
            ProcessedRelease.discogs_release_id.in_(release_ids)
        ).all()
    }

    # Field label, stored attribute, release dict key
    field_checks = [
        ("Artist", "artist", "artist"),
        ("Title", "title", "title"),
        ("Year", "year", "year"),
        ("Folder", "folder_name", "discogs_folder"),
        ("Format", "format_name", "format_name"),
        ("Size", "format_size", "format_size"),
        ("Description", "format_descriptions", "format_descriptions"),
    ]

    result: dict[int, list[str]] = {}
    for release in releases:
        rid = release["id"]
        stored = processed_map.get(rid)
        if not stored:
            continue  # Not processed yet — not "changed"

        diffs = []
        for label, attr, key in field_checks:
            stored_val = getattr(stored, attr)
            if stored_val is None:
                continue  # Never recorded — skip

            current_val = release.get(key, 0 if key == "year" else "")
            if key == "year":
                current_val = current_val or 0
                stored_cmp = stored_val or 0
            else:
                stored_cmp = stored_val

            if stored_cmp != current_val:
                old = str(stored_val) if stored_val else "(empty)"
                new = str(current_val) if current_val else "(empty)"
                diffs.append(f'{label}: "{old}" \u2192 "{new}"')

        if diffs:
            result[rid] = diffs

    return result


def _get_changed_ids(releases: list[dict]) -> set[int]:
    """Compare current release data against stored processed data.

    Returns set of discogs_release_ids where current data differs from stored snapshot.
    """
    return set(_get_change_details(releases).keys())


def _folder_has_changes(service, username, folder) -> bool:
    """Check if any release in a folder has changed since processing.

    Only uses cached data — returns False if cache is cold to avoid API calls.
    """
    if folder["count"] == 0:
        return False
    cached_ids = service.get_cached_folder_release_ids(username, folder["id"])
    if cached_ids is None:
        return False
    items = service._get_cached_items(username, folder["id"])
    releases = [item["release"] for item in items]
    return len(_get_changed_ids(releases)) > 0


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
