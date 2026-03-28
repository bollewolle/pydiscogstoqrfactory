from pydiscogstoqrfactory.models import UserSettings


class TestSettingsIndex:
    def test_redirects_when_unauthenticated(self, client):
        response = client.get("/settings/")
        assert response.status_code == 302

    def test_shows_default_template(self, client):
        with client.session_transaction() as sess:
            sess["username"] = "testuser"

        response = client.get("/settings/")
        assert response.status_code == 200
        assert b"BottomText Template" in response.data
        assert b"{artist}" in response.data

    def test_shows_saved_template(self, client, db):
        settings = UserSettings(
            username="testuser",
            bottom_text_template="{title} by {artist}",
        )
        db.session.add(settings)
        db.session.commit()

        with client.session_transaction() as sess:
            sess["username"] = "testuser"

        response = client.get("/settings/")
        assert response.status_code == 200
        assert b"{title} by {artist}" in response.data


class TestSettingsSave:
    def test_saves_new_settings(self, client, db):
        with client.session_transaction() as sess:
            sess["username"] = "testuser"

        response = client.post(
            "/settings/save",
            data={"bottom_text_template": "{artist} - {title}\n{format_name} {format_size}"},
            follow_redirects=True,
        )
        assert b"Settings saved" in response.data

        settings = UserSettings.query.filter_by(username="testuser").first()
        assert settings is not None
        assert "{format_name}" in settings.bottom_text_template
        assert "{format_size}" in settings.bottom_text_template

    def test_updates_existing_settings(self, client, db):
        settings = UserSettings(
            username="testuser",
            bottom_text_template="old template",
        )
        db.session.add(settings)
        db.session.commit()

        with client.session_transaction() as sess:
            sess["username"] = "testuser"

        client.post(
            "/settings/save",
            data={"bottom_text_template": "new template"},
        )

        settings = UserSettings.query.filter_by(username="testuser").first()
        assert settings.bottom_text_template == "new template"

    def test_redirects_when_unauthenticated(self, client):
        response = client.post(
            "/settings/save",
            data={"bottom_text_template": "test"},
        )
        assert response.status_code == 302
