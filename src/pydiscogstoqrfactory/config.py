import os
from pathlib import Path


class BaseConfig:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")

    # Database
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "sqlite:///app.db"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Server-side sessions
    SESSION_TYPE = "cachelib"
    SESSION_PERMANENT = False

    # Max form/request size (large collections can produce big form payloads)
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB
    MAX_FORM_MEMORY_SIZE = 16 * 1024 * 1024  # 16 MB (Werkzeug url-encoded form limit)

    # Discogs API
    DISCOGS_CONSUMER_KEY = os.environ.get("DISCOGS_CONSUMER_KEY", "")
    DISCOGS_CONSUMER_SECRET = os.environ.get("DISCOGS_CONSUMER_SECRET", "")
    DISCOGS_OAUTH_TOKEN = os.environ.get("DISCOGS_OAUTH_TOKEN", "")
    DISCOGS_OAUTH_TOKEN_SECRET = os.environ.get("DISCOGS_OAUTH_TOKEN_SECRET", "")
    USERAGENT = os.environ.get("USERAGENT", "pyqrfactorydiscogs/1.0")
    FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:5001")

    # CSV template
    CSV_TEMPLATE_PATH = Path(__file__).parent.parent.parent / "templates" / "qrfactory_discogs_collection_template.csv"

    # QR PDF logo
    LOGO_PATH = Path(__file__).parent / "static" / "discogs_logo.png"


class DevelopmentConfig(BaseConfig):
    DEBUG = True


class TestConfig(BaseConfig):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SECRET_KEY = "test-secret-key"
    WTF_CSRF_ENABLED = False
    SESSION_TYPE = "cachelib"


class ProductionConfig(BaseConfig):
    DEBUG = False


config_by_name = {
    "development": DevelopmentConfig,
    "testing": TestConfig,
    "production": ProductionConfig,
}


def get_config():
    env = os.environ.get("FLASK_ENV", "development")
    return config_by_name.get(env, DevelopmentConfig)
