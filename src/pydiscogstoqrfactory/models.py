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


class StickerLayout(db.Model):
    __tablename__ = "sticker_layout"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    page_width = db.Column(db.Float, nullable=False, default=210.0)  # mm (A4)
    page_height = db.Column(db.Float, nullable=False, default=297.0)  # mm (A4)
    sticker_width = db.Column(db.Float, nullable=False, default=50.0)  # mm
    sticker_height = db.Column(db.Float, nullable=False, default=50.0)  # mm
    margin_top = db.Column(db.Float, nullable=False, default=7.8)  # mm
    margin_left = db.Column(db.Float, nullable=False, default=15.0)  # mm
    spacing_x = db.Column(db.Float, nullable=False, default=15.0)  # mm
    spacing_y = db.Column(db.Float, nullable=False, default=7.8)  # mm
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    def __repr__(self):
        return f"<StickerLayout {self.name}>"

    @property
    def cols(self) -> int:
        """Calculate number of columns that fit on a page."""
        usable = self.page_width - 2 * self.margin_left
        if usable < self.sticker_width:
            return 0
        return int((usable + self.spacing_x) / (self.sticker_width + self.spacing_x))

    @property
    def rows(self) -> int:
        """Calculate number of rows that fit on a page."""
        usable = self.page_height - 2 * self.margin_top
        if usable < self.sticker_height:
            return 0
        return int((usable + self.spacing_y) / (self.sticker_height + self.spacing_y))

    @property
    def stickers_per_page(self) -> int:
        return self.cols * self.rows

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "page_width": self.page_width,
            "page_height": self.page_height,
            "sticker_width": self.sticker_width,
            "sticker_height": self.sticker_height,
            "margin_top": self.margin_top,
            "margin_left": self.margin_left,
            "spacing_x": self.spacing_x,
            "spacing_y": self.spacing_y,
            "cols": self.cols,
            "rows": self.rows,
            "stickers_per_page": self.stickers_per_page,
        }


class UserSettings(db.Model):
    __tablename__ = "user_settings"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(255), unique=True, nullable=False)
    bottom_text_template = db.Column(
        db.Text,
        nullable=False,
        default="{artist} \u2013 {title} [{year}]\n{discogs_folder}",
    )
    active_layout_id = db.Column(
        db.Integer, db.ForeignKey("sticker_layout.id"), nullable=True
    )
    active_layout = db.relationship("StickerLayout", foreign_keys=[active_layout_id])
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self):
        return f"<UserSettings {self.username}>"
