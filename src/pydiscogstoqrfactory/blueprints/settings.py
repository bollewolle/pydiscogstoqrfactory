from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from ..extensions import db
from ..models import UserSettings

settings_bp = Blueprint("settings", __name__, url_prefix="/settings")

DEFAULT_BOTTOM_TEXT = "{artist} \u2013 {title} [{year}]\n{discogs_folder}"


@settings_bp.route("/")
def index():
    """Show settings page."""
    username = session.get("username")
    if not username:
        flash("Please log in first.", "warning")
        return redirect(url_for("auth.login"))

    settings = UserSettings.query.filter_by(username=username).first()
    bottom_text = settings.bottom_text_template if settings else DEFAULT_BOTTOM_TEXT

    return render_template(
        "settings/index.html",
        bottom_text=bottom_text,
        default_bottom_text=DEFAULT_BOTTOM_TEXT,
    )


@settings_bp.route("/save", methods=["POST"])
def save():
    """Save settings."""
    username = session.get("username")
    if not username:
        flash("Please log in first.", "warning")
        return redirect(url_for("auth.login"))

    bottom_text = request.form.get("bottom_text_template", DEFAULT_BOTTOM_TEXT)

    settings = UserSettings.query.filter_by(username=username).first()
    if settings:
        settings.bottom_text_template = bottom_text
    else:
        settings = UserSettings(
            username=username,
            bottom_text_template=bottom_text,
        )
        db.session.add(settings)

    db.session.commit()
    flash("Settings saved.", "success")
    return redirect(url_for("settings.index"))
