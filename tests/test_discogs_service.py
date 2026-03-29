import pytest
from unittest.mock import MagicMock, patch

from pydiscogsqrcodegenerator.discogs_service import DiscogsService, _collection_cache


class TestNormalizeRelease:
    def setup_method(self):
        self.service = DiscogsService("key", "secret", "agent/1.0")

    def _make_item(self, release_id=1, title="Test", artists=None, year=2020, date_added=""):
        """Create a mock collection item."""
        item = MagicMock()
        release = MagicMock()
        release.id = release_id
        release.title = title
        release.year = year

        if artists is None:
            artist = MagicMock()
            artist.name = "Test Artist"
            release.artists = [artist]
        else:
            release.artists = artists

        item.release = release
        item.date_added = date_added
        return item

    def test_basic_normalization(self):
        item = self._make_item(release_id=123, title="Album", year=2023)
        result = self.service._normalize_release(item, "My Folder")

        assert result["id"] == 123
        assert result["title"] == "Album"
        assert result["year"] == 2023
        assert result["artist"] == "Test Artist"
        assert result["discogs_folder"] == "My Folder"
        assert result["url"] == "https://www.discogs.com/release/123"

    def test_multiple_artists(self):
        a1 = MagicMock()
        a1.name = "Artist One"
        a2 = MagicMock()
        a2.name = "Artist Two"
        item = self._make_item(artists=[a1, a2])
        result = self.service._normalize_release(item, "Folder")
        assert result["artist"] == "Artist One, Artist Two"

    def test_no_artists(self):
        item = self._make_item(artists=[])
        result = self.service._normalize_release(item, "Folder")
        assert result["artist"] == "Unknown Artist"

    def test_missing_year(self):
        item = self._make_item(year=None)
        result = self.service._normalize_release(item, "Folder")
        assert result["year"] == 0

    def test_date_added_preserved(self):
        item = self._make_item(date_added="2025-01-15T10:00:00-08:00")
        result = self.service._normalize_release(item, "Folder")
        assert result["date_added"] == "2025-01-15T10:00:00-08:00"


class TestIsSize:
    def test_twelve_inch(self):
        assert DiscogsService._is_size('12"') is True

    def test_seven_inch(self):
        assert DiscogsService._is_size('7"') is True

    def test_ten_inch(self):
        assert DiscogsService._is_size('10"') is True

    def test_not_size_lp(self):
        assert DiscogsService._is_size("LP") is False

    def test_not_size_album(self):
        assert DiscogsService._is_size("Album") is False

    def test_not_size_empty(self):
        assert DiscogsService._is_size("") is False


class TestInferSize:
    def test_explicit_size(self):
        assert DiscogsService._infer_size(['12"', "LP", "Album"]) == '12"'

    def test_infer_from_lp(self):
        assert DiscogsService._infer_size(["LP", "Album"]) == '12"'

    def test_no_size_no_inference(self):
        assert DiscogsService._infer_size(["Album"]) == ""

    def test_explicit_takes_precedence(self):
        assert DiscogsService._infer_size(['7"', "LP"]) == '7"'

    def test_empty_descriptions(self):
        assert DiscogsService._infer_size([]) == ""


class TestGetCollectionFormats:
    def setup_method(self):
        _collection_cache.clear()
        self.service = DiscogsService("key", "secret", "agent/1.0")

    def _make_item(self, formats):
        item = MagicMock()
        release = MagicMock()
        release.id = id(item)
        release.title = "Test"
        release.year = 2020
        release.formats = formats
        artist = MagicMock()
        artist.name = "Artist"
        release.artists = [artist]
        item.release = release
        item.date_added = ""
        item.folder = None
        return item

    def test_groups_by_format_name(self):
        items = [
            self._make_item([{"name": "Vinyl", "descriptions": ["LP", "Album", '12"'], "text": ""}]),
            self._make_item([{"name": "Vinyl", "descriptions": ['7"', "Single"], "text": ""}]),
            self._make_item([{"name": "CD", "descriptions": ["Album"], "text": ""}]),
        ]
        user = MagicMock()
        folder = MagicMock()
        folder.id = 0
        folder.releases = items
        user.collection_folders = [folder]

        with patch.object(self.service, "client") as mock_client:
            mock_client.user.return_value = user
            result = self.service.get_collection_formats("testuser")

        assert len(result) == 2
        assert result[0]["name"] == "Vinyl"
        assert result[0]["count"] == 2
        assert result[0]["has_sizes"] is True
        assert result[1]["name"] == "CD"
        assert result[1]["count"] == 1
        assert result[1]["has_sizes"] is False

    def test_handles_no_formats(self):
        items = [self._make_item(None)]
        user = MagicMock()
        folder = MagicMock()
        folder.id = 0
        folder.releases = items
        user.collection_folders = [folder]

        with patch.object(self.service, "client") as mock_client:
            mock_client.user.return_value = user
            result = self.service.get_collection_formats("testuser")

        assert result == []


class TestGetFormatSizes:
    def setup_method(self):
        _collection_cache.clear()
        self.service = DiscogsService("key", "secret", "agent/1.0")

    def _make_item(self, formats):
        item = MagicMock()
        release = MagicMock()
        release.id = id(item)
        release.title = "Test"
        release.year = 2020
        release.formats = formats
        artist = MagicMock()
        artist.name = "Artist"
        release.artists = [artist]
        item.release = release
        item.date_added = ""
        item.folder = None
        return item

    def test_extracts_sizes(self):
        items = [
            self._make_item([{"name": "Vinyl", "descriptions": ['12"', "LP", "Album"]}]),
            self._make_item([{"name": "Vinyl", "descriptions": ['12"', "LP"]}]),
            self._make_item([{"name": "Vinyl", "descriptions": ['7"', "Single"]}]),
        ]
        user = MagicMock()
        folder = MagicMock()
        folder.id = 0
        folder.releases = items
        user.collection_folders = [folder]

        with patch.object(self.service, "client") as mock_client:
            mock_client.user.return_value = user
            result = self.service.get_format_sizes("testuser", "Vinyl")

        assert len(result) == 2
        assert result[0]["size"] == '12"'
        assert result[0]["count"] == 2
        assert result[1]["size"] == '7"'
        assert result[1]["count"] == 1

    def test_inferred_size_from_lp(self):
        items = [
            self._make_item([{"name": "Vinyl", "descriptions": ['12"', "LP"]}]),
            self._make_item([{"name": "Vinyl", "descriptions": ["LP", "Album"]}]),
        ]
        user = MagicMock()
        folder = MagicMock()
        folder.id = 0
        folder.releases = items
        user.collection_folders = [folder]

        with patch.object(self.service, "client") as mock_client:
            mock_client.user.return_value = user
            result = self.service.get_format_sizes("testuser", "Vinyl")

        # Both should count as 12" (one explicit, one inferred from LP)
        assert len(result) == 1
        assert result[0]["size"] == '12"'
        assert result[0]["count"] == 2

    def test_includes_unknown_size(self):
        items = [
            self._make_item([{"name": "Vinyl", "descriptions": ['12"', "LP"]}]),
            self._make_item([{"name": "Vinyl", "descriptions": ["Single"]}]),
        ]
        user = MagicMock()
        folder = MagicMock()
        folder.id = 0
        folder.releases = items
        user.collection_folders = [folder]

        with patch.object(self.service, "client") as mock_client:
            mock_client.user.return_value = user
            result = self.service.get_format_sizes("testuser", "Vinyl")

        assert len(result) == 2
        assert result[0]["size"] == '12"'
        assert result[0]["count"] == 1
        assert result[1]["size"] == "Unknown"
        assert result[1]["count"] == 1

    def test_no_sizes_for_cd(self):
        items = [
            self._make_item([{"name": "CD", "descriptions": ["Album"]}]),
        ]
        user = MagicMock()
        folder = MagicMock()
        folder.id = 0
        folder.releases = items
        user.collection_folders = [folder]

        with patch.object(self.service, "client") as mock_client:
            mock_client.user.return_value = user
            result = self.service.get_format_sizes("testuser", "CD")

        assert result == []


class TestGetReleasesByFormat:
    def setup_method(self):
        _collection_cache.clear()
        self.service = DiscogsService("key", "secret", "agent/1.0")

    def _make_item(self, release_id, formats, artist_name="Artist"):
        item = MagicMock()
        release = MagicMock()
        release.id = release_id
        release.title = f"Release {release_id}"
        release.year = 2020
        release.formats = formats
        artist = MagicMock()
        artist.name = artist_name
        release.artists = [artist]
        item.release = release
        item.date_added = ""
        folder = MagicMock()
        folder.name = "All"
        item.folder = folder
        return item

    def test_filters_by_format_name(self):
        items = [
            self._make_item(1, [{"name": "Vinyl", "descriptions": ['12"', "LP", "Album"]}]),
            self._make_item(2, [{"name": "CD", "descriptions": ["Album"]}]),
            self._make_item(3, [{"name": "Vinyl", "descriptions": ['7"', "Single"]}]),
        ]
        user = MagicMock()
        folder = MagicMock()
        folder.id = 0
        folder.releases = items
        user.collection_folders = [folder]

        with patch.object(self.service, "client") as mock_client:
            mock_client.user.return_value = user
            releases, descs = self.service.get_releases_by_format("testuser", "Vinyl")

        assert len(releases) == 2
        assert releases[0]["id"] == 1
        assert releases[1]["id"] == 3
        assert "LP" in descs
        assert "Album" in descs
        assert "Single" in descs

    def test_filters_by_size(self):
        items = [
            self._make_item(1, [{"name": "Vinyl", "descriptions": ['12"', "LP"]}]),
            self._make_item(2, [{"name": "Vinyl", "descriptions": ['7"', "Single"]}]),
        ]
        user = MagicMock()
        folder = MagicMock()
        folder.id = 0
        folder.releases = items
        user.collection_folders = [folder]

        with patch.object(self.service, "client") as mock_client:
            mock_client.user.return_value = user
            releases, descs = self.service.get_releases_by_format(
                "testuser", "Vinyl", size='7"'
            )

        assert len(releases) == 1
        assert releases[0]["id"] == 2

    def test_filters_by_unknown_size(self):
        items = [
            self._make_item(1, [{"name": "Vinyl", "descriptions": ['12"', "LP"]}]),
            self._make_item(2, [{"name": "Vinyl", "descriptions": ["LP", "Album"]}]),
            self._make_item(3, [{"name": "Vinyl", "descriptions": ["Single"]}]),
        ]
        user = MagicMock()
        folder = MagicMock()
        folder.id = 0
        folder.releases = items
        user.collection_folders = [folder]

        with patch.object(self.service, "client") as mock_client:
            mock_client.user.return_value = user
            releases, descs = self.service.get_releases_by_format(
                "testuser", "Vinyl", size="Unknown"
            )

        # Only release 3 has no size (LP infers 12" for release 2)
        assert len(releases) == 1
        assert releases[0]["id"] == 3

    def test_inferred_size_matches_filter(self):
        items = [
            self._make_item(1, [{"name": "Vinyl", "descriptions": ['12"', "LP"]}]),
            self._make_item(2, [{"name": "Vinyl", "descriptions": ["LP", "Album"]}]),
            self._make_item(3, [{"name": "Vinyl", "descriptions": ['7"', "Single"]}]),
        ]
        user = MagicMock()
        folder = MagicMock()
        folder.id = 0
        folder.releases = items
        user.collection_folders = [folder]

        with patch.object(self.service, "client") as mock_client:
            mock_client.user.return_value = user
            releases, descs = self.service.get_releases_by_format(
                "testuser", "Vinyl", size='12"'
            )

        # Both release 1 (explicit 12") and release 2 (inferred from LP)
        assert len(releases) == 2
        assert releases[0]["id"] == 1
        assert releases[1]["id"] == 2

    def test_filters_by_description(self):
        items = [
            self._make_item(1, [{"name": "Vinyl", "descriptions": ['12"', "LP", "Album"]}]),
            self._make_item(2, [{"name": "Vinyl", "descriptions": ['12"', "EP"]}]),
            self._make_item(3, [{"name": "Vinyl", "descriptions": ['12"', "LP"]}]),
        ]
        user = MagicMock()
        folder = MagicMock()
        folder.id = 0
        folder.releases = items
        user.collection_folders = [folder]

        with patch.object(self.service, "client") as mock_client:
            mock_client.user.return_value = user
            releases, descs = self.service.get_releases_by_format(
                "testuser", "Vinyl", size='12"', description_filter=["LP"]
            )

        assert len(releases) == 2
        assert releases[0]["id"] == 1
        assert releases[1]["id"] == 3


class TestFormatArtists:
    def test_single_artist(self):
        artist = MagicMock()
        artist.name = "SOHN"
        assert DiscogsService._format_artists([artist]) == "SOHN"

    def test_multiple_artists(self):
        a1, a2 = MagicMock(), MagicMock()
        a1.name = "A"
        a2.name = "B"
        assert DiscogsService._format_artists([a1, a2]) == "A, B"

    def test_empty_list(self):
        assert DiscogsService._format_artists([]) == "Unknown Artist"

    def test_none(self):
        assert DiscogsService._format_artists(None) == "Unknown Artist"

    def test_strips_disambiguation_number(self):
        artist = MagicMock()
        artist.name = "Adja (3)"
        assert DiscogsService._format_artists([artist]) == "Adja"

    def test_strips_disambiguation_multiple_artists(self):
        a1, a2 = MagicMock(), MagicMock()
        a1.name = "Nordmann (2)"
        a2.name = "Regular Artist"
        assert DiscogsService._format_artists([a1, a2]) == "Nordmann, Regular Artist"

    def test_preserves_non_disambiguation_parentheses(self):
        artist = MagicMock()
        artist.name = "Sunn O)))"
        assert DiscogsService._format_artists([artist]) == "Sunn O)))"

    def test_preserves_parentheses_with_text(self):
        artist = MagicMock()
        artist.name = "The Artist (UK)"
        assert DiscogsService._format_artists([artist]) == "The Artist (UK)"


class TestStripDisambiguation:
    def test_single_digit(self):
        assert DiscogsService._strip_disambiguation("Adja (3)") == "Adja"

    def test_multi_digit(self):
        assert DiscogsService._strip_disambiguation("Nordmann (12)") == "Nordmann"

    def test_no_suffix(self):
        assert DiscogsService._strip_disambiguation("SOHN") == "SOHN"

    def test_text_in_parentheses_preserved(self):
        assert DiscogsService._strip_disambiguation("The Artist (UK)") == "The Artist (UK)"

    def test_parentheses_not_at_end_preserved(self):
        assert DiscogsService._strip_disambiguation("Artist (2) Extra") == "Artist (2) Extra"

    def test_empty_string(self):
        assert DiscogsService._strip_disambiguation("") == ""


class TestFindFolder:
    def test_finds_folder_by_id(self):
        user = MagicMock()
        f0 = MagicMock()
        f0.id = 0
        f0.name = "All"
        f1 = MagicMock()
        f1.id = 1
        f1.name = "Uncategorized"
        f5 = MagicMock()
        f5.id = 5
        f5.name = "Vinyl"
        user.collection_folders = [f0, f1, f5]

        assert DiscogsService._find_folder(user, 0).name == "All"
        assert DiscogsService._find_folder(user, 5).name == "Vinyl"

    def test_raises_for_missing_folder(self):
        user = MagicMock()
        f0 = MagicMock()
        f0.id = 0
        user.collection_folders = [f0]

        with pytest.raises(ValueError, match="Folder with ID 99 not found"):
            DiscogsService._find_folder(user, 99)


class TestMapSortKey:
    def test_artist(self):
        assert DiscogsService._map_sort_key("artist") == "artist"

    def test_year(self):
        assert DiscogsService._map_sort_key("year") == "year"

    def test_date_added(self):
        assert DiscogsService._map_sort_key("date_added") == "added"

    def test_unknown_defaults_to_artist(self):
        assert DiscogsService._map_sort_key("unknown") == "artist"


class TestParseDateAdded:
    def test_valid_date_string(self):
        item = MagicMock()
        item.date_added = "2025-01-15T10:00:00-08:00"
        from datetime import date
        result = DiscogsService._parse_date_added(item)
        assert result == date(2025, 1, 15)

    def test_datetime_object(self):
        from datetime import date, datetime, timezone
        item = MagicMock()
        item.date_added = datetime(2025, 3, 10, 14, 30, 0, tzinfo=timezone.utc)
        result = DiscogsService._parse_date_added(item)
        assert result == date(2025, 3, 10)

    def test_date_object(self):
        from datetime import date
        item = MagicMock()
        item.date_added = date(2025, 6, 1)
        result = DiscogsService._parse_date_added(item)
        assert result == date(2025, 6, 1)

    def test_none_date(self):
        item = MagicMock()
        item.date_added = None
        assert DiscogsService._parse_date_added(item) is None

    def test_invalid_date(self):
        item = MagicMock()
        item.date_added = "not-a-date"
        assert DiscogsService._parse_date_added(item) is None
