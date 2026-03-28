import pytest

from pydiscogstoqrfactory import create_app
from pydiscogstoqrfactory.config import TestConfig
from pydiscogstoqrfactory.extensions import db as _db


@pytest.fixture()
def app():
    app = create_app(config_class=TestConfig)
    with app.app_context():
        _db.create_all()
        yield app
        _db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def db(app):
    with app.app_context():
        yield _db


@pytest.fixture()
def sample_releases():
    return [
        {
            "id": 35410036,
            "title": "Albadas",
            "artist": "SOHN",
            "year": 2025,
            "discogs_folder": 'Vinyl - 12" - Albums',
            "url": "https://www.discogs.com/release/35410036",
            "date_added": "2025-01-15T10:00:00-08:00",
            "format_name": "Vinyl",
            "format_size": '12"',
            "format_descriptions": "LP, Album",
        },
        {
            "id": 35642734,
            "title": "Lazarus",
            "artist": "Kamasi Washington",
            "year": 2025,
            "discogs_folder": 'Vinyl - 12" - Albums',
            "url": "https://www.discogs.com/release/35642734",
            "date_added": "2025-02-10T10:00:00-08:00",
            "format_name": "Vinyl",
            "format_size": '12"',
            "format_descriptions": "LP, Album",
        },
        {
            "id": 6399871,
            "title": "Nordmann",
            "artist": "Nordmann",
            "year": 2014,
            "discogs_folder": 'Vinyl - 10" - EPs',
            "url": "https://www.discogs.com/release/6399871",
            "date_added": "2024-12-01T10:00:00-08:00",
            "format_name": "Vinyl",
            "format_size": '10"',
            "format_descriptions": "EP",
        },
    ]
