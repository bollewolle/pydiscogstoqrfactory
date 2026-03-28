import csv
import io
from pathlib import Path

from flask import Response


class CSVService:
    """Generate QR Factory 3 compatible CSV files from release data."""

    def __init__(self, template_path: str | Path):
        self.template_path = Path(template_path)
        self._header: list[str] = []
        self._template_row: list[str] = []
        self._load_template()

    def _load_template(self) -> None:
        """Read the CSV template and extract header + template row."""
        with open(self.template_path, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            self._header = next(reader)
            self._template_row = next(reader)

    @property
    def header(self) -> list[str]:
        return list(self._header)

    def generate_rows(
        self, releases: list[dict], bottom_text_template: str | None = None
    ) -> list[dict]:
        """Generate CSV row dicts for each release by substituting template placeholders.

        If bottom_text_template is provided, it replaces the BottomText column's
        template value (the content between quotes in the CSV template).
        """
        rows = []
        for release in releases:
            row = {}
            for col_name, template_value in zip(self._header, self._template_row):
                if col_name == "BottomText" and bottom_text_template is not None:
                    row[col_name] = self._substitute(bottom_text_template, release)
                else:
                    row[col_name] = self._substitute(template_value, release)
            rows.append(row)
        return rows

    def to_csv_string(self, rows: list[dict]) -> str:
        """Render rows to a CSV string."""
        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=self._header,
            quoting=csv.QUOTE_MINIMAL,
        )
        writer.writeheader()
        writer.writerows(rows)
        return output.getvalue()

    def to_csv_response(
        self, rows: list[dict], filename: str = "qrfactory_export.csv"
    ) -> Response:
        """Return a Flask Response for CSV download."""
        csv_string = self.to_csv_string(rows)
        return Response(
            csv_string,
            mimetype="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @staticmethod
    def _substitute(template_value: str, release: dict) -> str:
        """Replace placeholders in a template value with release data."""
        result = template_value
        result = result.replace("{artist}", str(release.get("artist", "")))
        result = result.replace("{title}", str(release.get("title", "")))
        year = release.get("year", "")
        result = result.replace("{year}", str(year) if year and year != 0 else "unknown")
        result = result.replace("{discogs_folder}", str(release.get("discogs_folder", "")))
        result = result.replace("{url}", f"https://www.discogs.com/release/{release.get('id', '')}")
        result = result.replace("{filename}", str(release.get("id", "")))
        result = result.replace("{format_name}", str(release.get("format_name", "")))
        result = result.replace("{format_size}", str(release.get("format_size", "")))
        result = result.replace("{format_descriptions}", str(release.get("format_descriptions", "")))
        return result
