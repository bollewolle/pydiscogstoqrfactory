import json

from unittest.mock import MagicMock, patch

from pydiscogsqrcodegenerator.models import ProcessedRelease


class TestLanding:
    def test_landing_page_loads(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert b"Discogs QR Code Generator" in response.data

    def test_landing_shows_login_when_unauthenticated(self, client):
        response = client.get("/")
        assert b"Login with Discogs" in response.data

    def test_landing_shows_options_when_authenticated(self, client):
        with client.session_transaction() as sess:
            sess["username"] = "testuser"

        response = client.get("/")
        assert b"Browse by Folders" in response.data
        assert b"Latest Additions" in response.data


class TestFolders:
    def test_folders_redirects_when_unauthenticated(self, client):
        with patch(
            "pydiscogsqrcodegenerator.blueprints.collection.get_authenticated_service"
        ) as mock_auth:
            mock_auth.return_value = None
            response = client.get("/collection/folders")
            assert response.status_code == 302

    def test_folders_lists_folders(self, client):
        with client.session_transaction() as sess:
            sess["username"] = "testuser"
            sess["access_token"] = "token"
            sess["access_secret"] = "secret"

        with patch(
            "pydiscogsqrcodegenerator.blueprints.collection.get_authenticated_service"
        ) as mock_auth:
            service = MagicMock()
            service.get_folders.return_value = [
                {"id": 0, "name": "All", "count": 100},
                {"id": 1, "name": "Uncategorized", "count": 50},
            ]
            service.get_cached_folder_release_ids.return_value = None
            mock_auth.return_value = service

            response = client.get("/collection/folders")
            assert response.status_code == 200
            assert b"All" in response.data
            assert b"100 releases" in response.data


class TestFolderReleases:
    def _mock_releases(self):
        return [
            {
                "id": 1,
                "artist": "Alpha",
                "title": "Album A",
                "year": 2020,
                "discogs_folder": "Vinyl",
                "url": "https://www.discogs.com/release/1",
                "date_added": "2025-01-01",
                "format_name": "Vinyl",
                "format_size": '12"',
                "format_descriptions": "LP, Album",
            },
            {
                "id": 2,
                "artist": "Beta",
                "title": "Album B",
                "year": 2021,
                "discogs_folder": "Vinyl",
                "url": "https://www.discogs.com/release/2",
                "date_added": "2025-01-02",
                "format_name": "CD",
                "format_size": "",
                "format_descriptions": "Album",
            },
        ]

    def _mock_folders(self):
        return [
            {"id": 0, "name": "All", "count": 100},
            {"id": 1, "name": "Vinyl", "count": 50},
        ]

    def test_folder_releases_lists_releases(self, client):
        with client.session_transaction() as sess:
            sess["username"] = "testuser"
            sess["access_token"] = "token"
            sess["access_secret"] = "secret"

        with patch(
            "pydiscogsqrcodegenerator.blueprints.collection.get_authenticated_service"
        ) as mock_auth:
            service = MagicMock()
            service.get_folder_releases.return_value = self._mock_releases()
            service.get_folders.return_value = self._mock_folders()
            mock_auth.return_value = service

            response = client.get("/collection/folders/1")
            assert response.status_code == 200
            assert b"Alpha" in response.data
            assert b"Beta" in response.data

    def test_letter_filter(self, client):
        with client.session_transaction() as sess:
            sess["username"] = "testuser"
            sess["access_token"] = "token"
            sess["access_secret"] = "secret"

        with patch(
            "pydiscogsqrcodegenerator.blueprints.collection.get_authenticated_service"
        ) as mock_auth:
            service = MagicMock()
            service.get_folder_releases.return_value = self._mock_releases()
            service.get_folders.return_value = self._mock_folders()
            mock_auth.return_value = service

            response = client.get("/collection/folders/1?letter=A")
            assert response.status_code == 200
            assert b"Alpha" in response.data
            assert b"Beta" not in response.data


class TestFormats:
    def test_formats_redirects_when_unauthenticated(self, client):
        with patch(
            "pydiscogsqrcodegenerator.blueprints.collection.get_authenticated_service"
        ) as mock_auth:
            mock_auth.return_value = None
            response = client.get("/collection/formats")
            assert response.status_code == 302

    def test_formats_lists_format_names(self, client):
        with client.session_transaction() as sess:
            sess["username"] = "testuser"
            sess["access_token"] = "token"
            sess["access_secret"] = "secret"

        with patch(
            "pydiscogsqrcodegenerator.blueprints.collection.get_authenticated_service"
        ) as mock_auth:
            service = MagicMock()
            service.get_collection_formats.return_value = [
                {"name": "Vinyl", "count": 70, "has_sizes": True},
                {"name": "CD", "count": 10, "has_sizes": False},
            ]
            # _get_cached_items is called for change detection
            service._get_cached_items.return_value = []
            mock_auth.return_value = service

            response = client.get("/collection/formats")
            assert response.status_code == 200
            assert b"Vinyl" in response.data
            assert b"70 releases" in response.data
            assert b"CD" in response.data


class TestFormatSizes:
    def test_shows_sizes(self, client):
        with client.session_transaction() as sess:
            sess["username"] = "testuser"
            sess["access_token"] = "token"
            sess["access_secret"] = "secret"

        with patch(
            "pydiscogsqrcodegenerator.blueprints.collection.get_authenticated_service"
        ) as mock_auth:
            service = MagicMock()
            service.get_format_sizes.return_value = [
                {"size": '12"', "count": 50},
                {"size": '7"', "count": 20},
            ]
            # _get_cached_items is called for change detection
            service._get_cached_items.return_value = []
            mock_auth.return_value = service

            response = client.get("/collection/formats/sizes?name=Vinyl")
            assert response.status_code == 200
            assert b"12&#34;" in response.data or b'12"' in response.data
            assert b"50 releases" in response.data

    def test_redirects_to_releases_when_no_sizes(self, client):
        with client.session_transaction() as sess:
            sess["username"] = "testuser"
            sess["access_token"] = "token"
            sess["access_secret"] = "secret"

        with patch(
            "pydiscogsqrcodegenerator.blueprints.collection.get_authenticated_service"
        ) as mock_auth:
            service = MagicMock()
            service.get_format_sizes.return_value = []
            mock_auth.return_value = service

            response = client.get("/collection/formats/sizes?name=CD")
            assert response.status_code == 302
            assert "/collection/formats/releases" in response.headers["Location"]

    def test_redirects_without_name(self, client):
        with client.session_transaction() as sess:
            sess["username"] = "testuser"
            sess["access_token"] = "token"
            sess["access_secret"] = "secret"

        with patch(
            "pydiscogsqrcodegenerator.blueprints.collection.get_authenticated_service"
        ) as mock_auth:
            mock_auth.return_value = MagicMock()
            response = client.get("/collection/formats/sizes")
            assert response.status_code == 302


class TestFormatReleases:
    def _mock_releases_and_descs(self):
        releases = [
            {
                "id": 1,
                "artist": "Alpha",
                "title": "Album A",
                "year": 2020,
                "discogs_folder": "Vinyl",
                "url": "https://www.discogs.com/release/1",
                "date_added": "2025-01-01",
                "format_name": "Vinyl",
                "format_size": '12"',
                "format_descriptions": "LP, Album",
            },
            {
                "id": 2,
                "artist": "Beta",
                "title": "Album B",
                "year": 2021,
                "discogs_folder": "Vinyl",
                "url": "https://www.discogs.com/release/2",
                "date_added": "2025-01-02",
                "format_name": "Vinyl",
                "format_size": '12"',
                "format_descriptions": "LP",
            },
        ]
        descriptions = ["Album", "LP"]
        return releases, descriptions

    def test_format_releases_lists_releases(self, client):
        with client.session_transaction() as sess:
            sess["username"] = "testuser"
            sess["access_token"] = "token"
            sess["access_secret"] = "secret"

        with patch(
            "pydiscogsqrcodegenerator.blueprints.collection.get_authenticated_service"
        ) as mock_auth:
            service = MagicMock()
            service.get_releases_by_format.return_value = self._mock_releases_and_descs()
            mock_auth.return_value = service

            response = client.get(
                "/collection/formats/releases?name=Vinyl&size=12%22"
            )
            assert response.status_code == 200
            assert b"Alpha" in response.data
            assert b"Beta" in response.data
            assert b"Album" in response.data
            assert b"LP" in response.data

    def test_format_releases_redirects_without_name(self, client):
        with client.session_transaction() as sess:
            sess["username"] = "testuser"
            sess["access_token"] = "token"
            sess["access_secret"] = "secret"

        with patch(
            "pydiscogsqrcodegenerator.blueprints.collection.get_authenticated_service"
        ) as mock_auth:
            mock_auth.return_value = MagicMock()
            response = client.get("/collection/formats/releases")
            assert response.status_code == 302


class TestLatest:
    def test_latest_get_shows_form(self, client):
        response = client.get("/collection/latest")
        assert response.status_code == 200
        assert b"since" in response.data.lower()


class TestChangedReleases:
    def _mock_releases(self):
        return [
            {
                "id": 1,
                "artist": "Alpha",
                "title": "Album A",
                "year": 2020,
                "discogs_folder": "Vinyl",
                "url": "https://www.discogs.com/release/1",
                "date_added": "2025-01-01",
                "format_name": "Vinyl",
                "format_size": '12"',
                "format_descriptions": "LP, Album",
            },
            {
                "id": 2,
                "artist": "Beta",
                "title": "Album B",
                "year": 2021,
                "discogs_folder": "Vinyl",
                "url": "https://www.discogs.com/release/2",
                "date_added": "2025-01-02",
                "format_name": "CD",
                "format_size": "",
                "format_descriptions": "Album",
            },
        ]

    def test_changed_releases_redirects_when_unauthenticated(self, client):
        with patch(
            "pydiscogsqrcodegenerator.blueprints.collection.get_authenticated_service"
        ) as mock_auth:
            mock_auth.return_value = None
            response = client.get("/collection/changed")
            assert response.status_code == 302

    def test_changed_releases_shows_changed(self, client, db):
        """A release whose artist changed since processing should appear."""
        releases = self._mock_releases()

        # Process release 1 with original data
        processed = ProcessedRelease(
            discogs_release_id=1,
            artist="Alpha Original",  # Different from current "Alpha"
            title="Album A",
            year=2020,
            folder_name="Vinyl",
            format_name="Vinyl",
            format_size='12"',
            format_descriptions="LP, Album",
        )
        db.session.add(processed)
        db.session.commit()

        with client.session_transaction() as sess:
            sess["username"] = "testuser"
            sess["access_token"] = "token"
            sess["access_secret"] = "secret"

        with patch(
            "pydiscogsqrcodegenerator.blueprints.collection.get_authenticated_service"
        ) as mock_auth:
            service = MagicMock()
            service.get_folder_releases.return_value = releases
            mock_auth.return_value = service

            response = client.get("/collection/changed")
            assert response.status_code == 200
            assert b"Alpha" in response.data
            # Release 2 is not processed, so it should not appear
            assert b"Beta" not in response.data

    def test_changed_releases_empty_when_nothing_changed(self, client, db):
        """A release processed with identical data should not appear."""
        releases = self._mock_releases()

        # Process release 1 with same data as current
        processed = ProcessedRelease(
            discogs_release_id=1,
            artist="Alpha",
            title="Album A",
            year=2020,
            folder_name="Vinyl",
            format_name="Vinyl",
            format_size='12"',
            format_descriptions="LP, Album",
        )
        db.session.add(processed)
        db.session.commit()

        with client.session_transaction() as sess:
            sess["username"] = "testuser"
            sess["access_token"] = "token"
            sess["access_secret"] = "secret"

        with patch(
            "pydiscogsqrcodegenerator.blueprints.collection.get_authenticated_service"
        ) as mock_auth:
            service = MagicMock()
            service.get_folder_releases.return_value = releases
            mock_auth.return_value = service

            response = client.get("/collection/changed")
            assert response.status_code == 200
            assert b"No releases have changed" in response.data


class TestChangeDetection:
    """Test the _get_change_details and _get_changed_ids helpers."""

    def test_no_changes_when_data_matches(self, app, db):
        from pydiscogsqrcodegenerator.blueprints.collection import _get_change_details

        processed = ProcessedRelease(
            discogs_release_id=1,
            artist="Alpha",
            title="Album",
            year=2020,
            folder_name="Vinyl",
            format_name="Vinyl",
            format_size='12"',
            format_descriptions="LP",
        )
        db.session.add(processed)
        db.session.commit()

        releases = [{
            "id": 1,
            "artist": "Alpha",
            "title": "Album",
            "year": 2020,
            "discogs_folder": "Vinyl",
            "format_name": "Vinyl",
            "format_size": '12"',
            "format_descriptions": "LP",
        }]
        assert _get_change_details(releases) == {}

    def test_detects_artist_change_with_details(self, app, db):
        from pydiscogsqrcodegenerator.blueprints.collection import _get_change_details

        processed = ProcessedRelease(
            discogs_release_id=1,
            artist="Alpha",
            title="Album",
            year=2020,
            folder_name="Vinyl",
        )
        db.session.add(processed)
        db.session.commit()

        releases = [{
            "id": 1,
            "artist": "Alpha Renamed",
            "title": "Album",
            "year": 2020,
            "discogs_folder": "Vinyl",
            "format_name": "",
            "format_size": "",
            "format_descriptions": "",
        }]
        details = _get_change_details(releases)
        assert 1 in details
        assert len(details[1]) == 1
        assert "Alpha" in details[1][0]
        assert "Alpha Renamed" in details[1][0]
        assert "Artist" in details[1][0]

    def test_detects_multiple_changes(self, app, db):
        from pydiscogsqrcodegenerator.blueprints.collection import _get_change_details

        processed = ProcessedRelease(
            discogs_release_id=1,
            artist="Alpha",
            title="Album",
            year=2020,
            folder_name="Vinyl",
            format_name="Vinyl",
            format_size='12"',
            format_descriptions="LP",
        )
        db.session.add(processed)
        db.session.commit()

        releases = [{
            "id": 1,
            "artist": "Alpha Renamed",
            "title": "Album (Deluxe)",
            "year": 2021,
            "discogs_folder": "Vinyl",
            "format_name": "Vinyl",
            "format_size": '12"',
            "format_descriptions": "LP",
        }]
        details = _get_change_details(releases)
        assert 1 in details
        assert len(details[1]) == 3  # Artist, Title, Year
        labels = [d.split(":")[0] for d in details[1]]
        assert "Artist" in labels
        assert "Title" in labels
        assert "Year" in labels

    def test_detects_title_change(self, app, db):
        from pydiscogsqrcodegenerator.blueprints.collection import _get_changed_ids

        processed = ProcessedRelease(
            discogs_release_id=1,
            artist="Alpha",
            title="Album",
            year=2020,
            folder_name="Vinyl",
        )
        db.session.add(processed)
        db.session.commit()

        releases = [{
            "id": 1,
            "artist": "Alpha",
            "title": "Album (Remastered)",
            "year": 2020,
            "discogs_folder": "Vinyl",
            "format_name": "",
            "format_size": "",
            "format_descriptions": "",
        }]
        assert _get_changed_ids(releases) == {1}

    def test_skips_null_format_fields(self, app, db):
        """Old records with NULL format columns should not flag as changed."""
        from pydiscogsqrcodegenerator.blueprints.collection import _get_changed_ids

        # Simulate old record without format fields (all NULL)
        processed = ProcessedRelease(
            discogs_release_id=1,
            artist="Alpha",
            title="Album",
            year=2020,
            folder_name="Vinyl",
            # format_name, format_size, format_descriptions left as None
        )
        db.session.add(processed)
        db.session.commit()

        releases = [{
            "id": 1,
            "artist": "Alpha",
            "title": "Album",
            "year": 2020,
            "discogs_folder": "Vinyl",
            "format_name": "Vinyl",
            "format_size": '12"',
            "format_descriptions": "LP, Album",
        }]
        # Should NOT be flagged as changed because stored format fields are NULL
        assert _get_changed_ids(releases) == set()

    def test_unprocessed_releases_not_flagged(self, app, db):
        from pydiscogsqrcodegenerator.blueprints.collection import _get_changed_ids

        releases = [{
            "id": 999,
            "artist": "New Artist",
            "title": "New Album",
            "year": 2025,
            "discogs_folder": "Vinyl",
            "format_name": "Vinyl",
            "format_size": "",
            "format_descriptions": "",
        }]
        assert _get_changed_ids(releases) == set()

    def test_detects_folder_change(self, app, db):
        from pydiscogsqrcodegenerator.blueprints.collection import _get_change_details

        processed = ProcessedRelease(
            discogs_release_id=1,
            artist="Alpha",
            title="Album",
            year=2020,
            folder_name="Old Folder",
        )
        db.session.add(processed)
        db.session.commit()

        releases = [{
            "id": 1,
            "artist": "Alpha",
            "title": "Album",
            "year": 2020,
            "discogs_folder": "New Folder",
            "format_name": "",
            "format_size": "",
            "format_descriptions": "",
        }]
        details = _get_change_details(releases)
        assert 1 in details
        assert any("Folder" in d for d in details[1])

    def test_detects_year_change(self, app, db):
        from pydiscogsqrcodegenerator.blueprints.collection import _get_changed_ids

        processed = ProcessedRelease(
            discogs_release_id=1,
            artist="Alpha",
            title="Album",
            year=2020,
            folder_name="Vinyl",
        )
        db.session.add(processed)
        db.session.commit()

        releases = [{
            "id": 1,
            "artist": "Alpha",
            "title": "Album",
            "year": 2021,
            "discogs_folder": "Vinyl",
            "format_name": "",
            "format_size": "",
            "format_descriptions": "",
        }]
        assert _get_changed_ids(releases) == {1}

    def test_empty_releases_list(self, app, db):
        from pydiscogsqrcodegenerator.blueprints.collection import _get_changed_ids

        assert _get_changed_ids([]) == set()


class TestLandingChangedCount:
    def test_landing_shows_changed_releases_card(self, client):
        with client.session_transaction() as sess:
            sess["username"] = "testuser"

        response = client.get("/")
        assert b"Changed Releases" in response.data
