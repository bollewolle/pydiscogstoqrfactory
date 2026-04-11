import logging
import os
import traceback

from cachelib import FileSystemCache
from dotenv import load_dotenv
from flask import Flask, Request, jsonify, session

from .config import get_config
from .extensions import db, sess

# Load .env at import time so FLASK_APP is available for Flask CLI discovery
load_dotenv()

logger = logging.getLogger(__name__)


class LargeFormRequest(Request):
    """Custom request class that allows larger URL-encoded form data."""

    max_form_memory_size = 16 * 1024 * 1024  # 16 MB


def create_app(config_class=None):
    # Configure logging
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    # Set instance_path to cwd/instance so it aligns with the Docker volume mount
    # (Flask defaults to package_parent/instance which would be src/instance)
    instance_path = os.path.join(os.getcwd(), "instance")
    app = Flask(__name__, instance_path=instance_path, instance_relative_config=True)
    app.request_class = LargeFormRequest

    # Ensure instance folder exists
    os.makedirs(app.instance_path, exist_ok=True)

    # Load config
    if config_class is None:
        config_class = get_config()
    app.config.from_object(config_class)

    # Default database to instance folder so it persists with Docker volumes
    if not app.config.get("SQLALCHEMY_DATABASE_URI"):
        db_path = os.path.join(app.instance_path, "app.db")
        app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"

    # Configure session cachelib backend
    session_dir = os.path.join(app.instance_path, "flask_session")
    app.config.setdefault("SESSION_CACHELIB", FileSystemCache(session_dir))

    # Initialize extensions
    db.init_app(app)
    sess.init_app(app)

    # Register blueprints
    from .blueprints.auth import auth_bp
    from .blueprints.collection import collection_bp
    from .blueprints.export import export_bp
    from .blueprints.settings import settings_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(collection_bp)
    app.register_blueprint(export_bp)
    app.register_blueprint(settings_bp)

    # Refresh session expiry on each request so active users stay logged in
    @app.before_request
    def refresh_session():
        session.permanent = True

    # Register error handlers
    @app.errorhandler(500)
    def internal_error(error):
        logger.error("Internal Server Error: %s", error, exc_info=True)
        tb = traceback.format_exc()
        if app.debug:
            return f"<pre>Internal Server Error:\n{tb}</pre>", 500
        return "<h1>Internal Server Error</h1><p>Something went wrong. Check the server logs.</p>", 500

    @app.errorhandler(Exception)
    def handle_exception(error):
        logger.error("Unhandled exception: %s", error, exc_info=True)
        tb = traceback.format_exc()
        if app.debug:
            return f"<pre>Unhandled Exception:\n{error}\n\n{tb}</pre>", 500
        return "<h1>Internal Server Error</h1><p>Something went wrong. Check the server logs.</p>", 500

    # Create database tables and migrate schema
    with app.app_context():
        db.create_all()
        _migrate_schema(db)

    # Start background scheduler for periodic Discogs collection scans
    try:
        from .scheduler import init_scheduler
        init_scheduler(app)
    except Exception:
        logger.exception("Failed to initialize background scheduler")

    return app


def _migrate_schema(database):
    """Add columns that were introduced after initial release."""
    import sqlalchemy

    migrations = [
        ("user_settings", "printer_offset_top", "FLOAT NOT NULL DEFAULT 0.0"),
        ("user_settings", "printer_offset_left", "FLOAT NOT NULL DEFAULT 0.0"),
        ("processed_release", "format_name", "VARCHAR(255)"),
        ("processed_release", "format_size", "VARCHAR(255)"),
        ("processed_release", "format_descriptions", "VARCHAR(512)"),
        ("user_settings", "scan_schedule_enabled", "BOOLEAN NOT NULL DEFAULT 0"),
        ("user_settings", "scan_frequency", "VARCHAR(16)"),
        ("user_settings", "scan_hour", "INTEGER"),
        ("user_settings", "scan_minute", "INTEGER"),
        ("user_settings", "scan_day_of_week", "INTEGER"),
        ("user_settings", "scan_day_of_month", "INTEGER"),
        ("user_settings", "scan_month_of_year", "INTEGER"),
        ("user_settings", "last_scan_at", "DATETIME"),
        ("user_settings", "last_scan_status", "VARCHAR(255)"),
        ("user_settings", "display_timezone", "VARCHAR(64) NOT NULL DEFAULT 'UTC'"),
    ]
    for table, column, col_type in migrations:
        try:
            database.session.execute(
                sqlalchemy.text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
            )
            database.session.commit()
            logger.info("Added column %s.%s", table, column)
        except sqlalchemy.exc.OperationalError:
            database.session.rollback()
