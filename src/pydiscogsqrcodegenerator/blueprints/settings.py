from flask import (
    Blueprint,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from ..extensions import db
from ..models import StickerLayout, UserSettings

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

    layouts = StickerLayout.query.filter_by(username=username).all()
    active_layout_id = settings.active_layout_id if settings else None

    return render_template(
        "settings/index.html",
        bottom_text=bottom_text,
        default_bottom_text=DEFAULT_BOTTOM_TEXT,
        layouts=layouts,
        active_layout_id=active_layout_id,
        standard_layouts=STANDARD_LAYOUTS,
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

    settings = UserSettings.query.filter_by(username=username).first()
    if settings:
        settings.bottom_text_template = bottom_text
        if active_layout_id:
            settings.active_layout_id = active_layout_id
    else:
        settings = UserSettings(
            username=username,
            bottom_text_template=bottom_text,
            active_layout_id=active_layout_id,
        )
        db.session.add(settings)

    db.session.commit()
    flash("Settings saved.", "success")
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
