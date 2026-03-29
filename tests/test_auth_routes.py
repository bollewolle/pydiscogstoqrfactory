from unittest.mock import MagicMock, patch

from pydiscogsqrcodegenerator.models import OAuthToken


class TestAuthLogin:
    def test_login_redirects_to_discogs(self, client):
        with patch(
            "pydiscogsqrcodegenerator.blueprints.auth._get_discogs_service"
        ) as mock_svc:
            service = MagicMock()
            service.get_authorize_url.return_value = (
                "req_token",
                "req_secret",
                "https://discogs.com/oauth/authorize?token=req_token",
            )
            mock_svc.return_value = service

            response = client.get("/auth/login")
            assert response.status_code == 302
            assert "discogs.com" in response.headers["Location"]

    def test_login_failure_flashes_error(self, client):
        with patch(
            "pydiscogsqrcodegenerator.blueprints.auth._get_discogs_service"
        ) as mock_svc:
            service = MagicMock()
            service.get_authorize_url.side_effect = Exception("API error")
            mock_svc.return_value = service

            response = client.get("/auth/login", follow_redirects=True)
            assert b"Failed to start authentication" in response.data


class TestAuthCallback:
    def test_callback_without_verifier_redirects(self, client):
        response = client.get("/auth/callback", follow_redirects=True)
        assert b"denied or failed" in response.data

    def test_callback_without_session_tokens(self, client):
        response = client.get(
            "/auth/callback?oauth_verifier=test_verifier",
            follow_redirects=True,
        )
        assert b"Session expired" in response.data

    def test_successful_callback(self, client, db):
        with client.session_transaction() as sess:
            sess["request_token"] = "req_token"
            sess["request_secret"] = "req_secret"

        with patch(
            "pydiscogsqrcodegenerator.blueprints.auth._get_discogs_service"
        ) as mock_svc:
            service = MagicMock()
            service.get_access_token.return_value = ("access_tok", "access_sec")
            service.get_identity.return_value = {"username": "testuser", "id": 1}
            mock_svc.return_value = service

            response = client.get(
                "/auth/callback?oauth_verifier=verifier123",
                follow_redirects=True,
            )
            assert b"Successfully authenticated" in response.data

        # Verify token stored in DB
        token = OAuthToken.query.filter_by(username="testuser").first()
        assert token is not None
        assert token.access_token == "access_tok"


class TestAuthLogout:
    def test_logout_clears_session(self, client):
        with client.session_transaction() as sess:
            sess["username"] = "testuser"
            sess["access_token"] = "token"

        response = client.post("/auth/logout", follow_redirects=True)
        assert b"Logged out" in response.data

        with client.session_transaction() as sess:
            assert "username" not in sess
