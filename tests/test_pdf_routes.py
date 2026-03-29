import json

from pydiscogsqrcodegenerator.models import StickerLayout, UserSettings


class TestPreviewPdf:
    def test_preview_pdf_with_valid_data(self, client, db, sample_releases):
        with client.session_transaction() as sess:
            sess["username"] = "testuser"

        response = client.post(
            "/export/preview-pdf",
            data={"releases_data": json.dumps(sample_releases)},
        )
        assert response.status_code == 200
        assert b"Preview QR Code PDF" in response.data
        assert b"SOHN" in response.data

    def test_preview_pdf_without_data_redirects(self, client):
        response = client.post("/export/preview-pdf", data={})
        assert response.status_code == 302

    def test_preview_pdf_with_invalid_json_redirects(self, client):
        response = client.post(
            "/export/preview-pdf",
            data={"releases_data": "not json"},
            follow_redirects=True,
        )
        assert b"Invalid release data" in response.data

    def test_preview_pdf_uses_active_layout(self, client, db, sample_releases):
        layout = StickerLayout(
            username="testuser",
            name="Custom",
            sticker_width=40.0,
            sticker_height=40.0,
        )
        db.session.add(layout)
        db.session.commit()

        settings = UserSettings(
            username="testuser",
            active_layout_id=layout.id,
        )
        db.session.add(settings)
        db.session.commit()

        with client.session_transaction() as sess:
            sess["username"] = "testuser"

        response = client.post(
            "/export/preview-pdf",
            data={"releases_data": json.dumps(sample_releases)},
        )
        assert response.status_code == 200
        assert b"Custom" in response.data


class TestGeneratePdf:
    def test_generate_pdf(self, client, db, sample_releases):
        with client.session_transaction() as sess:
            sess["username"] = "testuser"

        # First preview to populate session
        client.post(
            "/export/preview-pdf",
            data={"releases_data": json.dumps(sample_releases)},
        )

        layout = {
            "page_width": 210.0,
            "page_height": 297.0,
            "sticker_width": 50.0,
            "sticker_height": 50.0,
            "margin_top": 7.8,
            "margin_left": 15.0,
            "spacing_x": 15.0,
            "spacing_y": 7.8,
        }
        response = client.post(
            "/export/generate-pdf",
            data={
                "active_indices": json.dumps([0, 1, 2]),
                "layout_data": json.dumps(layout),
            },
        )
        assert response.status_code == 200
        assert response.content_type == "application/pdf"
        assert response.data[:5] == b"%PDF-"

    def test_generate_pdf_without_session_redirects(self, client):
        response = client.post("/export/generate-pdf")
        assert response.status_code == 302


class TestLayoutSettings:
    def test_add_layout(self, client, db):
        with client.session_transaction() as sess:
            sess["username"] = "testuser"

        response = client.post(
            "/settings/layout/add",
            data={
                "name": "Test Layout",
                "page_width": "210",
                "page_height": "297",
                "sticker_width": "45",
                "sticker_height": "45",
                "margin_top": "15",
                "margin_left": "15",
                "spacing_x": "3",
                "spacing_y": "3",
            },
            follow_redirects=True,
        )
        assert b"Test Layout" in response.data
        assert StickerLayout.query.filter_by(username="testuser", name="Test Layout").first() is not None

    def test_edit_layout(self, client, db):
        layout = StickerLayout(username="testuser", name="Original")
        db.session.add(layout)
        db.session.commit()

        with client.session_transaction() as sess:
            sess["username"] = "testuser"

        response = client.post(
            f"/settings/layout/{layout.id}/edit",
            data={"name": "Updated", "page_width": "210", "page_height": "297",
                  "sticker_width": "50", "sticker_height": "50",
                  "margin_top": "10", "margin_left": "10",
                  "spacing_x": "5", "spacing_y": "5"},
            follow_redirects=True,
        )
        assert b"Updated" in response.data

    def test_delete_layout(self, client, db):
        layout = StickerLayout(username="testuser", name="ToDelete")
        db.session.add(layout)
        db.session.commit()
        layout_id = layout.id

        with client.session_transaction() as sess:
            sess["username"] = "testuser"

        response = client.post(
            f"/settings/layout/{layout_id}/delete",
            follow_redirects=True,
        )
        assert b"deleted" in response.data.lower()
        assert StickerLayout.query.filter_by(name="ToDelete").first() is None

    def test_layout_info_json(self, client, db):
        layout = StickerLayout(username="testuser", name="Info Test")
        db.session.add(layout)
        db.session.commit()

        with client.session_transaction() as sess:
            sess["username"] = "testuser"

        response = client.get(f"/settings/layout/{layout.id}/info")
        assert response.status_code == 200
        data = response.get_json()
        assert data["name"] == "Info Test"
        assert "cols" in data
        assert "rows" in data
        assert "stickers_per_page" in data
