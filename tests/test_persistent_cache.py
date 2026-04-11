"""Tests for persisting the Discogs collection cache to SQLite.

The in-memory ``_collection_cache`` is an optimization; on app restart we
rehydrate it from the ``cached_collection`` table so the landing page can
report "Changed Releases" counts immediately — without waiting for the next
scheduled scan.
"""
import json

import pytest

from pydiscogsqrcodegenerator import discogs_service
from pydiscogsqrcodegenerator.discogs_service import (
    _collection_cache,
    _delete_persistent_entries,
    _save_persistent_entry,
    load_persistent_entries,
)
from pydiscogsqrcodegenerator.models import CachedCollection


@pytest.fixture(autouse=True)
def _clear_memory_cache():
    """Module-level dict survives between tests — reset it each time."""
    _collection_cache.clear()
    yield
    _collection_cache.clear()


def _sample_items():
    return [
        {
            "release": {
                "id": 1,
                "artist": "SOHN",
                "title": "Albadas",
                "year": 2025,
                "discogs_folder": "All",
                "url": "https://www.discogs.com/release/1",
                "date_added": "2025-01-01",
                "format_name": "Vinyl",
                "format_size": '12"',
                "format_descriptions": "LP",
            },
            "formats": [{"name": "Vinyl", "qty": "1", "descriptions": ["LP", '12"']}],
        },
        {
            "release": {
                "id": 2,
                "artist": "Kamasi Washington",
                "title": "Lazarus",
                "year": 2025,
                "discogs_folder": "All",
                "url": "https://www.discogs.com/release/2",
                "date_added": "2025-02-01",
                "format_name": "Vinyl",
                "format_size": '12"',
                "format_descriptions": "LP, Album",
            },
            "formats": [{"name": "Vinyl", "qty": "1", "descriptions": ["LP", '12"']}],
        },
    ]


class TestSavePersistentEntry:
    def test_creates_new_row(self, app, db):
        items = _sample_items()
        _save_persistent_entry("alice", 0, items)

        row = CachedCollection.query.filter_by(username="alice", folder_id=0).first()
        assert row is not None
        parsed = json.loads(row.data)
        assert len(parsed) == 2
        assert parsed[0]["release"]["artist"] == "SOHN"

    def test_updates_existing_row(self, app, db):
        _save_persistent_entry("alice", 0, _sample_items())
        # Save again with a smaller payload — should update, not duplicate
        _save_persistent_entry("alice", 0, _sample_items()[:1])

        rows = CachedCollection.query.filter_by(username="alice", folder_id=0).all()
        assert len(rows) == 1
        parsed = json.loads(rows[0].data)
        assert len(parsed) == 1

    def test_separate_folders_get_separate_rows(self, app, db):
        _save_persistent_entry("alice", 0, _sample_items())
        _save_persistent_entry("alice", 123, _sample_items()[:1])

        assert CachedCollection.query.filter_by(username="alice").count() == 2


class TestDeletePersistentEntries:
    def test_delete_all_for_user(self, app, db):
        _save_persistent_entry("alice", 0, _sample_items())
        _save_persistent_entry("alice", 42, _sample_items())
        _save_persistent_entry("bob", 0, _sample_items())

        _delete_persistent_entries("alice")

        assert CachedCollection.query.filter_by(username="alice").count() == 0
        assert CachedCollection.query.filter_by(username="bob").count() == 1

    def test_delete_specific_folder(self, app, db):
        _save_persistent_entry("alice", 0, _sample_items())
        _save_persistent_entry("alice", 42, _sample_items())

        _delete_persistent_entries("alice", folder_id=42)

        remaining = CachedCollection.query.filter_by(username="alice").all()
        assert len(remaining) == 1
        assert remaining[0].folder_id == 0


class TestLoadPersistentEntries:
    def test_loads_rows_into_memory_cache(self, app, db):
        _save_persistent_entry("alice", 0, _sample_items())

        _collection_cache.clear()  # simulate fresh process
        loaded = load_persistent_entries()

        assert loaded == 1
        assert ("alice", 0) in _collection_cache
        entry = _collection_cache[("alice", 0)]
        assert entry["persistent"] is True
        assert len(entry["items"]) == 2
        assert entry["items"][0]["release"]["id"] == 1

    def test_loaded_entries_skip_ttl_check(self, app, db):
        """Persistent entries should be treated as fresh regardless of age."""
        _save_persistent_entry("alice", 0, _sample_items())
        _collection_cache.clear()
        load_persistent_entries()

        service = discogs_service.DiscogsService("k", "s", "ua")
        ids = service.get_cached_folder_release_ids("alice", 0)
        assert ids == {1, 2}

    def test_corrupt_row_is_skipped(self, app, db):
        from pydiscogsqrcodegenerator.extensions import db as _db
        _db.session.add(CachedCollection(
            username="alice",
            folder_id=0,
            data="not valid json{",
        ))
        _db.session.commit()

        _collection_cache.clear()
        loaded = load_persistent_entries()
        assert loaded == 0
        assert ("alice", 0) not in _collection_cache

    def test_no_rows_returns_zero(self, app, db):
        assert load_persistent_entries() == 0


class TestInvalidateClearsPersisted:
    def test_invalidate_cache_deletes_rows(self, app, db):
        _save_persistent_entry("alice", 0, _sample_items())
        _save_persistent_entry("alice", 5, _sample_items())
        _collection_cache[("alice", 0)] = {
            "timestamp": 0, "items": [], "persistent": True
        }

        service = discogs_service.DiscogsService("k", "s", "ua")
        service.invalidate_cache("alice")

        assert CachedCollection.query.filter_by(username="alice").count() == 0
        assert ("alice", 0) not in _collection_cache

    def test_invalidate_folder_cache_deletes_row_and_all_folder(self, app, db):
        _save_persistent_entry("alice", 7, _sample_items())
        _save_persistent_entry("alice", 0, _sample_items())

        service = discogs_service.DiscogsService("k", "s", "ua")
        service.invalidate_folder_cache("alice", 7)

        assert CachedCollection.query.filter_by(username="alice").count() == 0


class TestWarmCachePersistsSnapshot:
    def test_warm_cache_writes_row(self, app, db):
        """warm_cache should persist the snapshot after a successful fetch."""
        from unittest.mock import MagicMock, patch

        service = discogs_service.DiscogsService("k", "s", "ua")

        fake_folder = MagicMock()
        fake_folder.id = 0
        fake_folder.name = "All"
        # one fake collection item
        item = MagicMock()
        item.release.id = 99
        item.release.title = "Test"
        item.release.year = 2025
        item.release.artists = []
        item.release.formats = [{"name": "Vinyl", "qty": "1", "descriptions": ["LP"]}]
        item.date_added = "2025-01-01"
        item.folder_id = 0
        fake_folder.releases = [item]

        fake_user = MagicMock()
        fake_user.collection_folders = [fake_folder]

        with patch.object(service.client, "user", return_value=fake_user):
            count = service.warm_cache("alice", folder_id=0)

        assert count == 1
        row = CachedCollection.query.filter_by(username="alice", folder_id=0).first()
        assert row is not None
        parsed = json.loads(row.data)
        assert parsed[0]["release"]["id"] == 99
