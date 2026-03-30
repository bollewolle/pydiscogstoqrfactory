import logging

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    request,
    session,
    url_for,
)

from ..discogs_service import DiscogsService
from ..extensions import db
from ..models import OAuthToken

logger = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


def _get_discogs_service() -> DiscogsService:
    return DiscogsService(
        consumer_key=current_app.config["DISCOGS_CONSUMER_KEY"],
        consumer_secret=current_app.config["DISCOGS_CONSUMER_SECRET"],
        user_agent=current_app.config["USERAGENT"],
    )


@auth_bp.route("/login")
def login():
    """Initiate OAuth flow with Discogs."""
    service = _get_discogs_service()
    callback_url = current_app.config["FRONTEND_URL"].rstrip("/") + url_for(
        "auth.callback"
    )
    logger.info("Starting OAuth flow with callback URL: %s", callback_url)

    try:
        request_token, request_secret, authorize_url = service.get_authorize_url(
            callback_url
        )
    except Exception as e:
        logger.exception("Failed to get authorize URL")
        flash(f"Failed to start authentication: {e}", "error")
        return redirect(url_for("collection.landing"))

    session["request_token"] = request_token
    session["request_secret"] = request_secret
    logger.info("Redirecting to Discogs authorize URL")
    return redirect(authorize_url)


@auth_bp.route("/callback")
def callback():
    """Handle OAuth callback from Discogs."""
    logger.info(
        "OAuth callback received with args: %s",
        {k: v[:10] + "..." if v else v for k, v in request.args.items()},
    )

    verifier = request.args.get("oauth_verifier")
    if not verifier:
        logger.warning("No oauth_verifier in callback params")
        flash("Authentication was denied or failed.", "error")
        return redirect(url_for("collection.landing"))

    request_token = session.pop("request_token", None)
    request_secret = session.pop("request_secret", None)
    if not request_token or not request_secret:
        logger.warning(
            "Session tokens missing: request_token=%s, request_secret=%s",
            bool(request_token),
            bool(request_secret),
        )
        flash("Session expired. Please try again.", "error")
        return redirect(url_for("collection.landing"))

    service = _get_discogs_service()

    try:
        access_token, access_secret = service.get_access_token(
            request_token, request_secret, verifier
        )
        logger.info("Successfully obtained access token")
    except Exception as e:
        logger.exception("Failed to exchange verifier for access token")
        flash(f"Failed to complete authentication: {e}", "error")
        return redirect(url_for("collection.landing"))

    try:
        service.authenticate(access_token, access_secret)
        identity = service.get_identity()
        logger.info("Authenticated as: %s", identity["username"])
    except Exception as e:
        logger.exception("Failed to verify identity after token exchange")
        flash(f"Failed to verify identity: {e}", "error")
        return redirect(url_for("collection.landing"))

    # Store tokens in session
    session["access_token"] = access_token
    session["access_secret"] = access_secret
    session["username"] = identity["username"]

    # Store tokens in database for future auto-auth
    try:
        _store_token(identity["username"], access_token, access_secret)
        logger.info("Stored OAuth token in database for user: %s", identity["username"])
    except Exception as e:
        logger.exception("Failed to store token in database (auth still works)")
        # Non-fatal: authentication works, just won't persist in DB

    flash(f"Successfully authenticated as {identity['username']}!", "success")
    return redirect(url_for("collection.landing"))


@auth_bp.route("/logout", methods=["POST"])
def logout():
    """Clear session and log out."""
    session.clear()
    flash("Logged out successfully.", "info")
    return redirect(url_for("collection.landing"))


def _store_token(username: str, access_token: str, access_secret: str) -> None:
    """Store or update OAuth token in database."""
    token = OAuthToken.query.filter_by(username=username).first()
    if token:
        token.access_token = access_token
        token.access_token_secret = access_secret
    else:
        token = OAuthToken(
            username=username,
            access_token=access_token,
            access_token_secret=access_secret,
        )
        db.session.add(token)
    db.session.commit()


def try_auto_authenticate() -> DiscogsService | None:
    """Try to authenticate using .env or database tokens. Returns service or None."""
    service = _get_discogs_service()

    # 1. Check session
    if session.get("access_token") and session.get("access_secret"):
        service.authenticate(session["access_token"], session["access_secret"])
        try:
            identity = service.get_identity()
            session["username"] = identity["username"]
            return service
        except Exception:
            logger.debug("Session tokens invalid, clearing")
            session.pop("access_token", None)
            session.pop("access_secret", None)

    # 2. Check .env credentials
    env_token = current_app.config.get("DISCOGS_OAUTH_TOKEN")
    env_secret = current_app.config.get("DISCOGS_OAUTH_TOKEN_SECRET")
    if env_token and env_secret:
        service.authenticate(env_token, env_secret)
        try:
            identity = service.get_identity()
            session["access_token"] = env_token
            session["access_secret"] = env_secret
            session["username"] = identity["username"]
            logger.info("Auto-authenticated via .env credentials as: %s", identity["username"])
            return service
        except Exception:
            logger.debug("Env tokens invalid")

    # 3. Check database for stored tokens
    try:
        tokens = OAuthToken.query.all()
    except Exception:
        logger.debug("Could not query OAuth tokens from database")
        tokens = []

    for token in tokens:
        service = _get_discogs_service()
        service.authenticate(token.access_token, token.access_token_secret)
        try:
            identity = service.get_identity()
            session["access_token"] = token.access_token
            session["access_secret"] = token.access_token_secret
            session["username"] = identity["username"]
            logger.info("Auto-authenticated via database token as: %s", identity["username"])
            return service
        except Exception:
            continue

    return None


def get_authenticated_service() -> DiscogsService | None:
    """Get an authenticated DiscogsService, or None if not authenticated."""
    return try_auto_authenticate()
