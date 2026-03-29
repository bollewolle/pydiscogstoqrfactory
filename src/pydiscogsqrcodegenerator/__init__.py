import logging
import os
import traceback

from cachelib import FileSystemCache
from dotenv import load_dotenv
from flask import Flask, Request, jsonify

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

    app = Flask(__name__, instance_relative_config=True)
    app.request_class = LargeFormRequest

    # Ensure instance folder exists
    os.makedirs(app.instance_path, exist_ok=True)

    # Load config
    if config_class is None:
        config_class = get_config()
    app.config.from_object(config_class)

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

    # Create database tables
    with app.app_context():
        db.create_all()

    return app
