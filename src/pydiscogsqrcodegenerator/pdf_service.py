import io
import math
import tempfile
from pathlib import Path

import segno
from fpdf import FPDF, ViewerPreferences
from PIL import Image

from .csv_service import CSVService


class PDFService:
    """Generate sticker-sheet PDFs with QR codes, logo overlay, and BottomText."""

    # Characters that can't be encoded in latin-1 (used by fpdf core fonts)
    _UNICODE_REPLACEMENTS = {
        "\u2013": "-",  # en-dash
        "\u2014": "-",  # em-dash
        "\u2018": "'",  # left single quote
        "\u2019": "'",  # right single quote
        "\u201c": '"',  # left double quote
        "\u201d": '"',  # right double quote
        "\u2026": "...",  # ellipsis
    }

    def __init__(self, logo_path: str | Path, csv_template_path: str | Path):
        self.logo_path = Path(logo_path)
        self.csv_service = CSVService(csv_template_path)

    def generate_qr_with_logo(self, url: str, size_px: int = 400) -> Image.Image:
        """Generate a QR code PNG with the Discogs logo centered on it."""
        qr = segno.make(url, error="H")  # High error correction for logo overlay
        buf = io.BytesIO()
        qr.save(buf, kind="png", scale=10, border=2)
        buf.seek(0)
        qr_img = Image.open(buf).convert("RGBA")
        qr_img = qr_img.resize((size_px, size_px), Image.LANCZOS)

        # Overlay logo at center (about 20% of QR size)
        logo = Image.open(self.logo_path).convert("RGBA")
        logo_size = size_px // 5
        logo = logo.resize((logo_size, logo_size), Image.LANCZOS)

        # Add white background behind logo for readability
        bg = Image.new("RGBA", (logo_size + 8, logo_size + 8), (255, 255, 255, 255))
        pos_bg = ((size_px - logo_size - 8) // 2, (size_px - logo_size - 8) // 2)
        qr_img.paste(bg, pos_bg)

        pos = ((size_px - logo_size) // 2, (size_px - logo_size) // 2)
        qr_img.paste(logo, pos, logo)

        return qr_img.convert("RGB")

    def generate_pdf(
        self,
        releases: list[dict],
        active_slot_indices: list[int],
        layout: dict,
        bottom_text_template: str | None = None,
        total_slots: int | None = None,
    ) -> bytes:
        """Generate a PDF with QR code stickers arranged in a grid layout.

        Releases are assigned to active slots in order. Inactive slots are
        left empty. This matches the preview grid where deactivating a slot
        shifts releases to the next active slot.

        Args:
            releases: List of release dicts.
            active_slot_indices: Slot positions that are active.
            layout: Dict with layout parameters (page_width, page_height, etc.).
            bottom_text_template: Optional custom BottomText template.
            total_slots: Total number of slots across all pages.

        Returns:
            PDF file bytes.
        """
        rows_data = self.csv_service.generate_rows(
            releases, bottom_text_template=bottom_text_template
        )

        active_set = set(active_slot_indices)

        if not active_set:
            return self._empty_pdf(layout)

        page_w = layout["page_width"]
        page_h = layout["page_height"]
        sticker_w = layout["sticker_width"]
        sticker_h = layout["sticker_height"]
        margin_top = layout["margin_top"]
        margin_left = layout["margin_left"]
        spacing_x = layout["spacing_x"]
        spacing_y = layout["spacing_y"]

        cols = int((page_w - 2 * margin_left + spacing_x) / (sticker_w + spacing_x))
        rows_count = int(
            (page_h - 2 * margin_top + spacing_y) / (sticker_h + spacing_y)
        )
        per_page = cols * rows_count

        if per_page == 0:
            return self._empty_pdf(layout)

        # Assign releases to active slots in order
        slot_to_release: dict[int, int] = {}
        release_idx = 0
        max_slot = max(active_set) if active_set else 0
        if total_slots:
            max_slot = max(max_slot, total_slots - 1)
        for slot in range(max_slot + 1):
            if slot in active_set and release_idx < len(releases):
                slot_to_release[slot] = release_idx
                release_idx += 1

        total_pages = math.ceil((max_slot + 1) / per_page)

        pdf = FPDF(unit="mm", format=(page_w, page_h))
        pdf.set_auto_page_break(auto=False)
        pdf.viewer_preferences = ViewerPreferences(print_scaling="None")

        padding = 1  # mm padding inside sticker
        gap = 0.5  # mm between QR and text
        usable_w = sticker_w - 2 * padding
        usable_h = sticker_h - 2 * padding

        # Pre-compute sticker layouts and QR images for assigned slots
        sticker_layouts = {}
        qr_files = {}
        try:
            for slot, r_idx in slot_to_release.items():
                row = rows_data[r_idx]
                bottom_text = row.get("BottomText", "")
                sticker_layouts[slot] = self._compute_sticker_layout(
                    pdf, bottom_text, usable_w, usable_h, gap
                )
                url = row.get("Content", "")
                qr_img = self.generate_qr_with_logo(url)
                tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
                qr_img.save(tmp, format="PNG")
                tmp.close()
                qr_files[slot] = tmp.name

            for page in range(total_pages):
                pdf.add_page()

                for row_i in range(rows_count):
                    for col_i in range(cols):
                        slot = page * per_page + row_i * cols + col_i

                        if slot > max_slot:
                            break

                        x = margin_left + col_i * (sticker_w + spacing_x)
                        y = margin_top + row_i * (sticker_h + spacing_y)

                        if slot in slot_to_release:
                            # Draw sticker border (light gray)
                            pdf.set_draw_color(200, 200, 200)
                            pdf.rect(x, y, sticker_w, sticker_h)

                            sl = sticker_layouts[slot]
                            qr_size_mm = sl["qr_size"]

                            # Place QR code centered horizontally
                            qr_x = x + (sticker_w - qr_size_mm) / 2
                            qr_y = y + padding
                            pdf.image(
                                qr_files[slot],
                                x=qr_x,
                                y=qr_y,
                                w=qr_size_mm,
                                h=qr_size_mm,
                            )

                            # Draw BottomText below QR code
                            text_y = qr_y + qr_size_mm + gap
                            text_h = y + sticker_h - padding - text_y
                            self._draw_wrapped_lines(
                                pdf, sl["lines"], sl["font_size"],
                                x + padding, text_y, usable_w, max(text_h, 1)
                            )
                        # Inactive slots are left empty

        finally:
            import os

            for f in qr_files.values():
                try:
                    os.unlink(f)
                except OSError:
                    pass

        return pdf.output()

    @classmethod
    def _sanitize_text(cls, text: str) -> str:
        """Replace Unicode characters that aren't supported by fpdf core fonts."""
        for char, replacement in cls._UNICODE_REPLACEMENTS.items():
            text = text.replace(char, replacement)
        # Remove any remaining non-latin-1 characters
        return text.encode("latin-1", errors="replace").decode("latin-1")

    # Font sizes to try, from largest to smallest
    _FONT_SIZES = [10, 9, 8, 7, 6, 5, 4, 3]

    # QR/text split ratios
    _QR_BASELINE = 0.75      # 75% QR when text ≤ 3 lines
    _QR_MIN = 0.62           # 62% QR minimum (text gets up to 38%)
    _TEXT_EXPAND_MAX_LINES = 5  # above this, stop expanding text area

    def _wrap_line(self, pdf: FPDF, line: str, max_w: float) -> list[str]:
        """Word-wrap a single line to fit within max_w. Preserves words where possible."""
        if not line or pdf.get_string_width(line) <= max_w:
            return [line]

        words = line.split(" ")
        wrapped = []
        current = ""
        for word in words:
            test = f"{current} {word}".strip()
            if pdf.get_string_width(test) <= max_w:
                current = test
            else:
                if current:
                    wrapped.append(current)
                current = word
        if current:
            wrapped.append(current)
        return wrapped

    def _wrap_text(self, pdf: FPDF, text: str, max_w: float) -> list[str]:
        """Split text on explicit newlines, then word-wrap each segment."""
        segments = text.split("\n")
        wrapped = []
        for segment in segments:
            wrapped.extend(self._wrap_line(pdf, segment, max_w))
        return wrapped

    def _compute_sticker_layout(
        self, pdf: FPDF, text: str, usable_w: float, usable_h: float, gap: float
    ) -> dict:
        """Compute QR size, font size, and wrapped lines for a single sticker.

        Priority: keep font as large as possible, let text wrap to more lines,
        and shrink the QR code before shrinking the font.

        For each font size (largest first), wrap the text and check:
        1. ≤ 3 lines: QR 75%, text 25% — fits comfortably.
        2. 4-5 lines: QR shrinks from 75% down to 62%, text grows up to 38%.
        3. > 5 lines: QR locked at 62% — only reached if text doesn't fit
           at this font size within 5 lines, so try next smaller font.
        """
        if not text:
            qr_size = min(usable_w, usable_h * self._QR_BASELINE)
            return {"qr_size": qr_size, "font_size": 8, "lines": []}

        text = self._sanitize_text(text)
        text_h_baseline = usable_h * (1 - self._QR_BASELINE) - gap
        text_h_max = usable_h * (1 - self._QR_MIN) - gap

        for font_size in self._FONT_SIZES:
            pdf.set_font("Helvetica", style="B", size=font_size)
            wrapped = self._wrap_text(pdf, text, usable_w)
            line_h = font_size * 0.45
            total_h = len(wrapped) * line_h
            num_lines = len(wrapped)

            # Rule 1: ≤ 3 lines, fits in baseline 25% text area
            if num_lines <= 3 and total_h <= text_h_baseline:
                qr_size = min(usable_w, usable_h * self._QR_BASELINE)
                return {"qr_size": qr_size, "font_size": font_size, "lines": wrapped}

            # Rule 2: 4-5 lines, shrink QR just enough (down to 62%)
            if num_lines <= self._TEXT_EXPAND_MAX_LINES and total_h <= text_h_max:
                needed_text_h = total_h + gap
                qr_ratio = max(self._QR_MIN, 1 - (needed_text_h / usable_h))
                qr_ratio = min(qr_ratio, self._QR_BASELINE)
                qr_size = min(usable_w, usable_h * qr_ratio)
                return {"qr_size": qr_size, "font_size": font_size, "lines": wrapped}

            # Rule 3: > 5 lines — if text fits in 38% area, accept it
            # (this means font is already being reduced since we got here)
            if total_h <= text_h_max:
                qr_size = min(usable_w, usable_h * self._QR_MIN)
                return {"qr_size": qr_size, "font_size": font_size, "lines": wrapped}

            # Text doesn't fit at this font size at all — try smaller font

        # Final fallback: smallest font, QR at 62%
        font_size = self._FONT_SIZES[-1]
        pdf.set_font("Helvetica", style="B", size=font_size)
        wrapped = self._wrap_text(pdf, text, usable_w)
        qr_size = min(usable_w, usable_h * self._QR_MIN)
        return {"qr_size": qr_size, "font_size": font_size, "lines": wrapped}

    def _draw_wrapped_lines(
        self,
        pdf: FPDF,
        lines: list[str],
        font_size: float,
        x: float,
        y: float,
        max_w: float,
        max_h: float,
    ) -> None:
        """Draw pre-wrapped bold lines centered in a bounding box."""
        if not lines:
            return

        pdf.set_font("Helvetica", style="B", size=font_size)
        line_h = font_size * 0.45
        total_h = len(lines) * line_h
        start_y = y + (max_h - total_h) / 2

        for i, line in enumerate(lines):
            w = pdf.get_string_width(line)
            text_x = x + (max_w - w) / 2
            pdf.text(text_x, start_y + (i + 1) * line_h, line)

    def _empty_pdf(self, layout: dict) -> bytes:
        """Return a single-page empty PDF."""
        pdf = FPDF(unit="mm", format=(layout["page_width"], layout["page_height"]))
        pdf.add_page()
        pdf.set_font("Helvetica", size=12)
        pdf.text(10, 20, "No stickers to generate.")
        return pdf.output()

    def compute_layout_info(self, layout: dict, release_count: int) -> dict:
        """Compute how many stickers fit and how many pages are needed."""
        page_w = layout["page_width"]
        page_h = layout["page_height"]
        sticker_w = layout["sticker_width"]
        sticker_h = layout["sticker_height"]
        margin_top = layout["margin_top"]
        margin_left = layout["margin_left"]
        spacing_x = layout["spacing_x"]
        spacing_y = layout["spacing_y"]

        cols = int((page_w - 2 * margin_left + spacing_x) / (sticker_w + spacing_x))
        rows = int((page_h - 2 * margin_top + spacing_y) / (sticker_h + spacing_y))
        per_page = max(cols * rows, 1)
        pages = math.ceil(release_count / per_page) if release_count > 0 else 1

        return {
            "cols": cols,
            "rows": rows,
            "stickers_per_page": per_page,
            "total_pages": pages,
        }
