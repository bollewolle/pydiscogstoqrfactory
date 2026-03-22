import csv
import io
from pathlib import Path

from pydiscogstoqrfactory.csv_service import CSVService


TEMPLATE_PATH = Path(__file__).parent.parent / "templates" / "qrfactory_discogs_collection_template.csv"


class TestCSVService:
    def setup_method(self):
        self.service = CSVService(TEMPLATE_PATH)

    def test_template_loading(self):
        assert len(self.service.header) == 30
        assert self.service.header[0] == "Type"
        assert self.service.header[-1] == "FileName"

    def test_generate_rows_single_release(self, sample_releases):
        rows = self.service.generate_rows([sample_releases[0]])
        assert len(rows) == 1
        row = rows[0]
        assert row["Type"] == "URL"
        assert row["OutputSize"] == "1024"
        assert row["Content"] == "https://www.discogs.com/release/35410036"
        assert row["FileName"] == "35410036"
        assert "SOHN" in row["BottomText"]
        assert "Albadas" in row["BottomText"]
        assert "2025" in row["BottomText"]

    def test_generate_rows_multiple_releases(self, sample_releases):
        rows = self.service.generate_rows(sample_releases)
        assert len(rows) == 3

    def test_generate_rows_preserves_fixed_fields(self, sample_releases):
        rows = self.service.generate_rows(sample_releases)
        for row in rows:
            assert row["FileType"] == "PNG"
            assert row["ColorSpace"] == "RGB"
            assert row["ReliabilityLevel"] == "High"
            assert row["PixelRoundness"] == "0.0"
            assert row["BackgroundColor"] == "#FFFFFF"
            assert row["PixelColorStart"] == "#000000"

    def test_bottom_text_format(self, sample_releases):
        rows = self.service.generate_rows(sample_releases)
        row = rows[0]
        # Template has: {artist} – {title} [{year}] – {discogs_folder}
        assert "SOHN" in row["BottomText"]
        assert "Albadas" in row["BottomText"]
        assert "2025" in row["BottomText"]
        assert 'Vinyl - 12" - Albums' in row["BottomText"]

    def test_content_url_format(self, sample_releases):
        rows = self.service.generate_rows(sample_releases)
        assert rows[0]["Content"] == "https://www.discogs.com/release/35410036"
        assert rows[1]["Content"] == "https://www.discogs.com/release/35642734"
        assert rows[2]["Content"] == "https://www.discogs.com/release/6399871"

    def test_filename_is_release_id(self, sample_releases):
        rows = self.service.generate_rows(sample_releases)
        assert rows[0]["FileName"] == "35410036"
        assert rows[1]["FileName"] == "35642734"
        assert rows[2]["FileName"] == "6399871"

    def test_to_csv_string(self, sample_releases):
        rows = self.service.generate_rows(sample_releases)
        csv_string = self.service.to_csv_string(rows)

        reader = csv.reader(io.StringIO(csv_string))
        header = next(reader)
        assert header == self.service.header

        data_rows = list(reader)
        assert len(data_rows) == 3

    def test_to_csv_string_header_present(self, sample_releases):
        rows = self.service.generate_rows([sample_releases[0]])
        csv_string = self.service.to_csv_string(rows)
        assert csv_string.startswith("Type,")

    def test_special_characters_in_artist(self):
        release = {
            "id": 123,
            "artist": 'Artist "Special" & Co.',
            "title": "Some, Title",
            "year": 2020,
            "discogs_folder": "Folder",
        }
        rows = self.service.generate_rows([release])
        csv_string = self.service.to_csv_string(rows)
        # Should produce valid CSV that can be re-parsed
        reader = csv.reader(io.StringIO(csv_string))
        next(reader)  # header
        data = next(reader)
        assert len(data) == 30

    def test_unknown_year_shows_unknown(self):
        release = {
            "id": 456,
            "artist": "Test Artist",
            "title": "Test Album",
            "year": 0,
            "discogs_folder": "Folder",
        }
        rows = self.service.generate_rows([release])
        assert "[unknown]" in rows[0]["BottomText"]
        assert "[0]" not in rows[0]["BottomText"]

    def test_missing_year_shows_unknown(self):
        release = {
            "id": 789,
            "artist": "Test Artist",
            "title": "Test Album",
            "discogs_folder": "Folder",
        }
        rows = self.service.generate_rows([release])
        assert "[unknown]" in rows[0]["BottomText"]

    def test_empty_releases_list(self):
        rows = self.service.generate_rows([])
        assert rows == []
        csv_string = self.service.to_csv_string(rows)
        # Should still have header
        lines = csv_string.strip().split("\n")
        assert len(lines) == 1  # header only
