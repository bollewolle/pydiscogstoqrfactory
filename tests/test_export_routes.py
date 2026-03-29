import json

from pydiscogsqrcodegenerator.models import ProcessedRelease, UserSettings


class TestPreview:
    def test_preview_with_valid_data(self, client, sample_releases):
        response = client.post(
            "/export/preview",
            data={"releases_data": json.dumps(sample_releases)},
        )
        assert response.status_code == 200
        assert b"QR Factory 3 CSV Preview" in response.data
        assert b"SOHN" in response.data

    def test_preview_uses_custom_bottom_text(self, client, db, sample_releases):
        settings = UserSettings(
            username="testuser",
            bottom_text_template="{title} [{format_name} {format_size}]",
        )
        db.session.add(settings)
        db.session.commit()

        with client.session_transaction() as sess:
            sess["username"] = "testuser"

        response = client.post(
            "/export/preview",
            data={"releases_data": json.dumps(sample_releases)},
        )
        assert response.status_code == 200
        assert b'Albadas [Vinyl 12"' in response.data or b"Albadas [Vinyl 12&#34;" in response.data

    def test_preview_without_data_redirects(self, client):
        response = client.post("/export/preview", data={})
        assert response.status_code == 302

    def test_preview_with_invalid_json_redirects(self, client):
        response = client.post(
            "/export/preview",
            data={"releases_data": "not json"},
            follow_redirects=True,
        )
        assert b"Invalid release data" in response.data


class TestDownload:
    def test_download_from_session(self, client, sample_releases):
        # First preview to populate session
        client.post(
            "/export/preview",
            data={"releases_data": json.dumps(sample_releases)},
        )
        # Then download
        response = client.post("/export/download")
        assert response.status_code == 200
        assert response.content_type == "text/csv; charset=utf-8"
        assert "attachment" in response.headers.get("Content-Disposition", "")

    def test_download_with_rows_data(self, client, sample_releases):
        from pydiscogsqrcodegenerator.csv_service import CSVService
        from pydiscogsqrcodegenerator.config import TestConfig

        service = CSVService(TestConfig.CSV_TEMPLATE_PATH)
        rows = service.generate_rows(sample_releases)

        response = client.post(
            "/export/download",
            data={"rows_data": json.dumps(rows)},
        )
        assert response.status_code == 200
        assert response.content_type == "text/csv; charset=utf-8"

    def test_download_without_data_redirects(self, client):
        response = client.post("/export/download")
        assert response.status_code == 302


class TestMarkProcessed:
    def test_mark_processed(self, client, db, sample_releases):
        response = client.post(
            "/export/mark-processed",
            data={"releases_data": json.dumps(sample_releases)},
            follow_redirects=True,
        )
        assert b"Marked 3 release(s) as processed" in response.data

        # Verify in database
        count = ProcessedRelease.query.count()
        assert count == 3

    def test_mark_processed_skips_duplicates(self, client, db, sample_releases):
        # First mark
        client.post(
            "/export/mark-processed",
            data={"releases_data": json.dumps(sample_releases)},
        )
        # Second mark (same releases)
        response = client.post(
            "/export/mark-processed",
            data={"releases_data": json.dumps(sample_releases)},
            follow_redirects=True,
        )
        assert b"Marked 0 release(s) as processed" in response.data


class TestUnmarkProcessed:
    def test_unmark_processed(self, client, db, sample_releases):
        # First mark them as processed
        client.post(
            "/export/mark-processed",
            data={"releases_data": json.dumps(sample_releases)},
        )
        assert ProcessedRelease.query.count() == 3

        # Unmark two of them
        to_unmark = sample_releases[:2]
        response = client.post(
            "/export/unmark-processed",
            data={"releases_data": json.dumps(to_unmark)},
            follow_redirects=True,
        )
        assert b"Removed processed status from 2 release(s)" in response.data
        assert ProcessedRelease.query.count() == 1

    def test_unmark_processed_none_found(self, client, db, sample_releases):
        # Try to unmark releases that are not processed
        response = client.post(
            "/export/unmark-processed",
            data={"releases_data": json.dumps(sample_releases)},
            follow_redirects=True,
        )
        assert b"Removed processed status from 0 release(s)" in response.data

    def test_unmark_processed_no_data(self, client):
        response = client.post(
            "/export/unmark-processed",
            data={},
            follow_redirects=True,
        )
        assert b"No releases selected" in response.data


class TestClearSession:
    def test_clear_session_preserves_auth(self, client):
        with client.session_transaction() as sess:
            sess["username"] = "testuser"
            sess["access_token"] = "token"
            sess["access_secret"] = "secret"
            sess["preview_rows"] = [{"some": "data"}]

        client.post("/export/clear-session")

        with client.session_transaction() as sess:
            assert sess.get("username") == "testuser"
            assert sess.get("access_token") == "token"
            assert "preview_rows" not in sess
