from pathlib import Path

import pytest

from pydiscogsqrcodegenerator.config import TestConfig
from pydiscogsqrcodegenerator.pdf_service import PDFService

LOGO_PATH = Path(__file__).parent.parent / "src" / "pydiscogsqrcodegenerator" / "static" / "discogs_logo.png"


@pytest.fixture()
def pdf_service():
    return PDFService(LOGO_PATH, TestConfig.CSV_TEMPLATE_PATH)


@pytest.fixture()
def default_layout():
    return {
        "page_width": 210.0,
        "page_height": 297.0,
        "sticker_width": 50.0,
        "sticker_height": 50.0,
        "margin_top": 7.8,
        "margin_left": 15.0,
        "spacing_x": 15.0,
        "spacing_y": 7.8,
    }


class TestQRGeneration:
    def test_generate_qr_with_logo(self, pdf_service):
        img = pdf_service.generate_qr_with_logo("https://www.discogs.com/release/12345")
        assert img.size == (400, 400)
        assert img.mode == "RGB"

    def test_generate_qr_custom_size(self, pdf_service):
        img = pdf_service.generate_qr_with_logo("https://example.com", size_px=200)
        assert img.size == (200, 200)


class TestLayoutInfo:
    def test_compute_layout_info(self, pdf_service, default_layout):
        info = pdf_service.compute_layout_info(default_layout, 10)
        assert info["cols"] == 3
        assert info["rows"] == 5
        assert info["stickers_per_page"] == 15
        assert info["total_pages"] == 1

    def test_multiple_pages(self, pdf_service, default_layout):
        info = pdf_service.compute_layout_info(default_layout, 20)
        assert info["total_pages"] == 2

    def test_zero_releases(self, pdf_service, default_layout):
        info = pdf_service.compute_layout_info(default_layout, 0)
        assert info["total_pages"] == 1


class TestPDFGeneration:
    def test_generate_pdf_with_releases(self, pdf_service, default_layout, sample_releases):
        active = list(range(len(sample_releases)))
        pdf_bytes = pdf_service.generate_pdf(sample_releases, active, default_layout)
        assert pdf_bytes[:5] == b"%PDF-"
        assert len(pdf_bytes) > 100

    def test_generate_pdf_subset(self, pdf_service, default_layout, sample_releases):
        # Only include first release
        pdf_bytes = pdf_service.generate_pdf(sample_releases, [0], default_layout)
        assert pdf_bytes[:5] == b"%PDF-"

    def test_generate_pdf_empty_indices(self, pdf_service, default_layout, sample_releases):
        pdf_bytes = pdf_service.generate_pdf(sample_releases, [], default_layout)
        assert pdf_bytes[:5] == b"%PDF-"

    def test_generate_pdf_with_custom_bottom_text(self, pdf_service, default_layout, sample_releases):
        pdf_bytes = pdf_service.generate_pdf(
            sample_releases, [0, 1], default_layout,
            bottom_text_template="{title}\n{format_name} {format_size}"
        )
        assert pdf_bytes[:5] == b"%PDF-"
