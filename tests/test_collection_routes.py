from unittest.mock import MagicMock, patch


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
            },
            {
                "id": 2,
                "artist": "Beta",
                "title": "Album B",
                "year": 2021,
                "discogs_folder": "Vinyl",
                "url": "https://www.discogs.com/release/2",
                "date_added": "2025-01-02",
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
            },
            {
                "id": 2,
                "artist": "Beta",
                "title": "Album B",
                "year": 2021,
                "discogs_folder": "Vinyl",
                "url": "https://www.discogs.com/release/2",
                "date_added": "2025-01-02",
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
