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
        printer_offset_top: float = 0.0,
        printer_offset_left: float = 0.0,
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
            printer_offset_top: mm to subtract from top margin to compensate
                for printer origin offset (positive = shift content up).
            printer_offset_left: mm to subtract from left margin to compensate
                for printer origin offset (positive = shift content left).

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
        margin_top = layout["margin_top"] - printer_offset_top
        margin_left = layout["margin_left"] - printer_offset_left
        spacing_x = layout["spacing_x"]
        spacing_y = layout["spacing_y"]

        # Grid calculation uses the original layout margins (not offset-adjusted)
        cols = int((page_w - 2 * layout["margin_left"] + spacing_x) / (sticker_w + spacing_x))
        rows_count = int(
            (page_h - 2 * layout["margin_top"] + spacing_y) / (sticker_h + spacing_y)
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

        padding_top = 1  # mm padding from top of sticker
        padding_bottom = 3.5  # mm padding at bottom of sticker
        padding = 2.5  # mm padding on sides
        gap = 0.25  # mm between QR and text
        usable_w = sticker_w - 2 * padding
        usable_h = sticker_h - padding_top - padding_bottom

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

            # Draw a 10mm verification square in the bottom-right corner of
            # each page so the user can measure it after printing and confirm
            # the output is at true 1:1 scale.
            verify_size = 10  # mm
            verify_x = page_w - margin_left - verify_size
            verify_y = page_h - 5 - verify_size  # 5mm from bottom edge

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
                            sl = sticker_layouts[slot]
                            qr_size_mm = sl["qr_size"]

                            # Place QR code centered horizontally
                            qr_x = x + (sticker_w - qr_size_mm) / 2
                            qr_y = y + padding_top
                            pdf.image(
                                qr_files[slot],
                                x=qr_x,
                                y=qr_y,
                                w=qr_size_mm,
                                h=qr_size_mm,
                            )

                            # Draw BottomText below QR code
                            text_y = qr_y + qr_size_mm + gap
                            text_h = y + sticker_h - padding_bottom - text_y
                            self._draw_wrapped_lines(
                                pdf, sl["lines"], sl["font_size"],
                                x + padding, text_y, usable_w, max(text_h, 1)
                            )
                        # Inactive slots are left empty

                # Verification square and print instruction
                pdf.set_draw_color(180, 180, 180)
                pdf.rect(verify_x, verify_y, verify_size, verify_size)
                pdf.set_font("Helvetica", size=5)
                pdf.set_text_color(180, 180, 180)
                label = f"{verify_size}x{verify_size}mm"
                label_w = pdf.get_string_width(label)
                pdf.text(
                    verify_x + (verify_size - label_w) / 2,
                    verify_y + verify_size / 2 + 1,
                    label,
                )
                notice = 'Print at "Actual size" (100%) - do not use "Fit to page"'
                notice_w = pdf.get_string_width(notice)
                pdf.text(
                    verify_x + verify_size - notice_w,
                    verify_y - 1,
                    notice,
                )
                pdf.set_text_color(0, 0, 0)

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

    def generate_test_page(
        self,
        layout: dict,
        printer_offset_top: float = 0.0,
        printer_offset_left: float = 0.0,
    ) -> bytes:
        """Generate a single-page test PDF that visualises all layout dimensions.

        Annotations are placed inside sticker cells and along page edges so
        they never overlap sticker borders or get cut off.
        """
        page_w = layout["page_width"]
        page_h = layout["page_height"]
        sticker_w = layout["sticker_width"]
        sticker_h = layout["sticker_height"]
        margin_top_orig = layout["margin_top"]
        margin_left_orig = layout["margin_left"]
        spacing_x = layout["spacing_x"]
        spacing_y = layout["spacing_y"]

        # The test page always draws at the original (unadjusted) margins
        # so the user can measure printed output against expected values.
        # The printer offset is only applied in the actual QR sticker PDF.
        margin_top = margin_top_orig
        margin_left = margin_left_orig

        cols = int((page_w - 2 * margin_left_orig + spacing_x) / (sticker_w + spacing_x))
        rows = int((page_h - 2 * margin_top_orig + spacing_y) / (sticker_h + spacing_y))

        pdf = FPDF(unit="mm", format=(page_w, page_h))
        pdf.set_auto_page_break(auto=False)
        pdf.viewer_preferences = ViewerPreferences(print_scaling="None")
        pdf.add_page()

        # Colours
        sticker_col = (180, 180, 180)
        dim_col = (200, 60, 60)
        note_col = (120, 120, 120)
        dim_font = 6

        # --- Draw all sticker outlines (light dashed) ---
        pdf.set_draw_color(*sticker_col)
        pdf.set_dash_pattern(dash=1, gap=1)
        for r in range(rows):
            for c in range(cols):
                x = margin_left + c * (sticker_w + spacing_x)
                y = margin_top + r * (sticker_h + spacing_y)
                pdf.rect(x, y, sticker_w, sticker_h)
        pdf.set_dash_pattern()

        # --- Drawing helpers ---
        def set_dim():
            pdf.set_draw_color(*dim_col)
            pdf.set_font("Helvetica", style="B", size=dim_font)
            pdf.set_text_color(*dim_col)

        def h_arrow(y, x1, x2):
            """Horizontal line with end ticks."""
            tick = 1.2
            pdf.line(x1, y, x2, y)
            pdf.line(x1, y - tick, x1, y + tick)
            pdf.line(x2, y - tick, x2, y + tick)

        def v_arrow(x, y1, y2):
            """Vertical line with end ticks."""
            tick = 1.2
            pdf.line(x, y1, x, y2)
            pdf.line(x - tick, y1, x + tick, y1)
            pdf.line(x - tick, y2, x + tick, y2)

        def text_centered(text, cx, cy):
            """Draw text centered on (cx, cy)."""
            lw = pdf.get_string_width(text)
            pdf.text(cx - lw / 2, cy + 1, text)

        def text_vertical(text, cx, cy):
            """Draw text rotated 90° CCW, centered on (cx, cy)."""
            with pdf.rotation(90, cx, cy):
                lw = pdf.get_string_width(text)
                pdf.text(cx - lw / 2, cy + 1, text)

        # Helper: sticker cell origin (col, row) -> (x, y)
        def cell_xy(col, row):
            return (
                margin_left + col * (sticker_w + spacing_x),
                margin_top + row * (sticker_h + spacing_y),
            )

        # Helper: center of sticker cell
        def cell_center(col, row):
            x, y = cell_xy(col, row)
            return x + sticker_w / 2, y + sticker_h / 2

        set_dim()

        # ============================================================
        # 1) TITLE — centered at top of page (above the sticker grid)
        # ============================================================
        pdf.set_font("Helvetica", style="B", size=9)
        pdf.set_text_color(0, 0, 0)
        layout_name = layout.get("name", "Layout")
        title = f"Test Page: {layout_name} ({cols}x{rows})"
        title_w = pdf.get_string_width(title)
        title_y = min(margin_top / 2, 8)
        pdf.text(page_w / 2 - title_w / 2, title_y, title)

        # Instructions just below title
        pdf.set_font("Helvetica", size=5.5)
        pdf.set_text_color(*note_col)
        instructions = [
            'Print at "Actual size" (100%).',
            "Measure the margins with a ruler.",
            "Offset Top = measured top margin - expected top margin.",
            "Offset Left = measured left margin - expected left margin.",
        ]
        if printer_offset_top != 0 or printer_offset_left != 0:
            instructions.append(
                f"Current offsets applied: top={printer_offset_top}mm, left={printer_offset_left}mm"
            )
        for i, line in enumerate(instructions):
            lw = pdf.get_string_width(line)
            pdf.text(page_w / 2 - lw / 2, title_y + 3 + i * 2.5, line)

        set_dim()

        # ============================================================
        # 2) PAGE W — along bottom edge, label horizontal centered
        # ============================================================
        pw_y = page_h - 4
        h_arrow(pw_y, 0, page_w)
        text_centered(f"Page W: {page_w}mm", page_w / 2, pw_y - 2.5)

        # ============================================================
        # 3) PAGE H — along right edge, label vertical
        # ============================================================
        ph_x = page_w - 4
        v_arrow(ph_x, 0, page_h)
        text_vertical(f"Page H: {page_h}mm", ph_x - 2, page_h / 2)

        # ============================================================
        # 4) MARGIN T — vertical arrow from page top to first sticker,
        #    label vertical next to the arrow line
        # ============================================================
        s1_cx, s1_cy = cell_center(0, 0)
        s1_x, s1_y = cell_xy(0, 0)
        v_arrow(s1_cx, 0, s1_y)
        text_vertical(f"Margin T: {margin_top_orig}mm", s1_cx + 3, s1_y / 2)

        # ============================================================
        # 5) MARGIN L — horizontal arrow from page left to first sticker,
        #    label vertical next to the arrow line
        # ============================================================
        h_arrow(s1_cy, 0, s1_x)
        text_vertical(f"Margin L: {margin_left_orig}mm", s1_x / 2, s1_cy - 3)

        # ============================================================
        # 6) STICKER W & H — inside 1st sticker of 2nd row
        #    W arrow in upper third, H arrow in right third, labels
        #    placed to avoid overlap.
        # ============================================================
        if rows >= 2:
            sw_x, sw_y = cell_xy(0, 1)
            sw_cx, sw_cy = cell_center(0, 1)
        else:
            # Fallback: use 2nd sticker of 1st row, or 1st sticker
            col = 1 if cols >= 2 else 0
            sw_x, sw_y = cell_xy(col, 0)
            sw_cx, sw_cy = cell_center(col, 0)
        # Sticker W: horizontal arrow in the upper third of the cell
        sw_ay = sw_y + sticker_h * 0.3
        h_arrow(sw_ay, sw_x, sw_x + sticker_w)
        text_centered(f"Sticker W: {sticker_w}mm", sw_cx, sw_ay - 2.5)
        # Sticker H: vertical arrow in the right third of the cell
        sh_ax = sw_x + sticker_w * 0.7
        v_arrow(sh_ax, sw_y, sw_y + sticker_h)
        text_vertical(f"Sticker H: {sticker_h}mm", sh_ax + 3, sw_cy)

        # ============================================================
        # 7) SPACE X — between stickers 1 and 2 of row 3,
        #    label vertical just above the line.
        #    SPACE Y — between sticker 2 of row 2 and sticker 2 of row 3,
        #    label horizontal just to the right of the line.
        # ============================================================
        # Space X
        sx_row = 2 if rows >= 3 else (1 if rows >= 2 else 0)
        if cols >= 2 and spacing_x > 0:
            gap_x1 = margin_left + sticker_w  # right edge of col 0
            gap_x2 = gap_x1 + spacing_x       # left edge of col 1
            gap_xc = (gap_x1 + gap_x2) / 2
            _, gap_xy = cell_xy(0, sx_row)
            gap_x_mid_y = gap_xy + sticker_h / 2
            h_arrow(gap_x_mid_y, gap_x1, gap_x2)
            text_vertical(f"Space X: {spacing_x}mm", gap_xc, gap_x_mid_y - 3)

        # Space Y
        sy_col = 1 if cols >= 2 else 0
        sy_row_top = 1 if rows >= 2 else 0
        if rows >= 2 and spacing_y > 0:
            _, sy_top_y = cell_xy(sy_col, sy_row_top)
            gap_y1 = sy_top_y + sticker_h      # bottom of upper row
            gap_y2 = gap_y1 + spacing_y         # top of lower row
            gap_yc = (gap_y1 + gap_y2) / 2
            sy_cell_x, _ = cell_xy(sy_col, sy_row_top)
            sy_line_x = sy_cell_x + sticker_w / 2
            v_arrow(sy_line_x, gap_y1, gap_y2)
            pdf.text(sy_line_x + 2, gap_yc + 1, f"Space Y: {spacing_y}mm")

        # ============================================================
        # 8) 10x10mm verification square — inside 3rd sticker of 1st row
        # ============================================================
        verify_size = 10
        if cols >= 3:
            v_cx, v_cy = cell_center(2, 0)
        elif cols >= 2:
            v_cx, v_cy = cell_center(1, 0)
        else:
            v_cx, v_cy = cell_center(0, rows - 1)

        vx = v_cx - verify_size / 2
        vy = v_cy - verify_size / 2
        pdf.set_draw_color(*dim_col)
        pdf.rect(vx, vy, verify_size, verify_size)
        pdf.set_font("Helvetica", style="B", size=5)
        pdf.set_text_color(*dim_col)
        # Size label below the square
        lbl = f"{verify_size}x{verify_size}mm"
        lbl_w = pdf.get_string_width(lbl)
        pdf.text(vx + (verify_size - lbl_w) / 2, vy + verify_size + 3, lbl)
        # "Verification square" label above the square
        title_lbl = "Verification square"
        title_lbl_w = pdf.get_string_width(title_lbl)
        pdf.text(vx + (verify_size - title_lbl_w) / 2, vy - 2, title_lbl)

        pdf.set_text_color(0, 0, 0)
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
