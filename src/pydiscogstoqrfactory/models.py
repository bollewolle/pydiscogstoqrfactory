from datetime import datetime, timezone

from .extensions import db


class OAuthToken(db.Model):
    __tablename__ = "oauth_token"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(255), unique=True, nullable=False)
    access_token = db.Column(db.String(255), nullable=False)
    access_token_secret = db.Column(db.String(255), nullable=False)
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self):
        return f"<OAuthToken {self.username}>"


class ProcessedRelease(db.Model):
    __tablename__ = "processed_release"

    id = db.Column(db.Integer, primary_key=True)
    discogs_release_id = db.Column(db.Integer, unique=True, nullable=False)
    artist = db.Column(db.String(255), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    year = db.Column(db.Integer, nullable=True)
    folder_name = db.Column(db.String(255), nullable=True)
    processed_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    username = db.Column(db.String(255), nullable=True)

    def __repr__(self):
        return f"<ProcessedRelease {self.discogs_release_id}: {self.artist} - {self.title}>"


class UserSettings(db.Model):
    __tablename__ = "user_settings"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(255), unique=True, nullable=False)
    bottom_text_template = db.Column(
        db.Text,
        nullable=False,
        default="{artist} \u2013 {title} [{year}]\n{discogs_folder}",
    )
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self):
        return f"<UserSettings {self.username}>"
