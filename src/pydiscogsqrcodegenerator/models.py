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
    format_name = db.Column(db.String(255), nullable=True)
    format_size = db.Column(db.String(255), nullable=True)
    format_descriptions = db.Column(db.String(512), nullable=True)
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


class CachedCollection(db.Model):
    """Persistent snapshot of the in-memory collection cache.

    Lets a scheduled scan survive across app restarts: on startup we reload
    any stored snapshots into ``_collection_cache`` and mark them persistent,
    so the landing page can report "Changed Releases" counts immediately
    without having to wait for the next scheduled run to re-warm the cache.
    """

    __tablename__ = "cached_collection"
    __table_args__ = (
        db.UniqueConstraint("username", "folder_id", name="uq_cached_collection_user_folder"),
    )

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(255), nullable=False, index=True)
    folder_id = db.Column(db.Integer, nullable=False)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    data = db.Column(db.Text, nullable=False)  # JSON-encoded list of items

    def __repr__(self):
        return f"<CachedCollection {self.username} folder={self.folder_id}>"


class ScanLog(db.Model):
    __tablename__ = "scan_log"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(255), nullable=False, index=True)
    started_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    finished_at = db.Column(db.DateTime, nullable=True)
    trigger = db.Column(db.String(16), nullable=False, default="scheduled")  # scheduled|manual
    status = db.Column(db.String(16), nullable=False, default="running")  # running|success|error
    items_scanned = db.Column(db.Integer, nullable=True)
    changed_count = db.Column(db.Integer, nullable=True)
    message = db.Column(db.Text, nullable=True)

    def __repr__(self):
        return f"<ScanLog {self.username} {self.started_at} {self.status}>"

    @property
    def duration_seconds(self) -> float | None:
        if not self.finished_at:
            return None
        start = self.started_at
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        end = self.finished_at
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        return (end - start).total_seconds()


class UserSettings(db.Model):
    __tablename__ = "user_settings"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(255), unique=True, nullable=False)
    bottom_text_template = db.Column(
        db.Text,
        nullable=False,
        default="{artist} \u2013 {title} [{year}]\n{discogs_folder}",
    )
    # IANA timezone name, e.g. "Europe/Brussels". Applied to the schedule
    # interpretation and to all timestamps displayed in the UI.
    display_timezone = db.Column(db.String(64), nullable=False, default="UTC")
    printer_offset_top = db.Column(db.Float, nullable=False, default=0.0)  # mm
    printer_offset_left = db.Column(db.Float, nullable=False, default=0.0)  # mm
    active_layout_id = db.Column(
        db.Integer, db.ForeignKey("sticker_layout.id"), nullable=True
    )
    active_layout = db.relationship("StickerLayout", foreign_keys=[active_layout_id])
    # Scheduled collection scan configuration
    scan_schedule_enabled = db.Column(db.Boolean, nullable=False, default=False)
    scan_frequency = db.Column(db.String(16), nullable=True)  # daily|weekly|monthly|yearly
    scan_hour = db.Column(db.Integer, nullable=True)  # 0-23
    scan_minute = db.Column(db.Integer, nullable=True)  # 0-59
    scan_day_of_week = db.Column(db.Integer, nullable=True)  # 0=Mon..6=Sun (weekly)
    scan_day_of_month = db.Column(db.Integer, nullable=True)  # 1-31 (monthly)
    scan_month_of_year = db.Column(db.Integer, nullable=True)  # 1-12 (yearly)
    last_scan_at = db.Column(db.DateTime, nullable=True)
    last_scan_status = db.Column(db.String(255), nullable=True)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self):
        return f"<UserSettings {self.username}>"
