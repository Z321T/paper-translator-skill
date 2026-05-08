"""Two-column layout-aware PDF text extraction for academic papers.

Handles the dense two-column format common in CS conference papers
(ICML, NeurIPS, CVPR, etc.). Uses word-level bounding box positions
to detect the inter-column gap and extract left/right columns separately.

Usage:
    uv run python scripts/pdf_extract_two_column.py <paper.pdf> [output.txt]

Install:
    uv pip install pdfplumber
"""

import sys
from pathlib import Path
import pdfplumber


def extract_page_two_column(page) -> str:
    """Extract text from one page, separating left and right columns.

    Strategy:
    1. Get word-level positions from pdfplumber
    2. Find the gap between left and right text columns by analyzing
       the x-coordinate distribution of word midpoints
    3. Split words into left/right groups by column boundary
    4. Reconstruct text column by column (left first, then right)
    """
    words = page.extract_words(
        x_tolerance=3, y_tolerance=3, keep_blank_chars=False
    )
    if not words:
        return page.extract_text() or ""

    page_width = page.width

    # Find column boundary by analyzing gap between adjacent words
    # that appear on the same horizontal line
    lines = {}
    for w in words:
        y_key = round(w["top"], 0)
        lines.setdefault(y_key, []).append(w)

    gaps = []
    for line_words in lines.values():
        sorted_w = sorted(line_words, key=lambda w: w["x0"])
        for i in range(len(sorted_w) - 1):
            gap = sorted_w[i + 1]["x0"] - sorted_w[i]["x1"]
            # A column gap is typically 5-25% of page width
            if page_width * 0.05 < gap < page_width * 0.40:
                mid = (sorted_w[i]["x1"] + sorted_w[i + 1]["x0"]) / 2
                gaps.append(mid)

    if not gaps:
        return page.extract_text() or ""

    # Use median gap position as column boundary
    boundary = sorted(gaps)[len(gaps) // 2]

    # Separate words into left and right columns
    left_words = [w for w in words if w["x1"] < boundary]
    right_words = [w for w in words if w["x0"] > boundary]

    left_text = _words_to_paragraphs(left_words)
    right_text = _words_to_paragraphs(right_words)

    return f"{left_text}\n{right_text}"


def _words_to_paragraphs(words: list[dict]) -> str:
    """Group sorted words into lines, then into paragraphs.

    A paragraph break is detected when the vertical gap between
    consecutive lines exceeds the typical line spacing.
    """
    if not words:
        return ""

    # Group by Y position
    lines = {}
    for w in words:
        y_key = round(w["top"], 0)
        lines.setdefault(y_key, []).append(w)

    sorted_y = sorted(lines.keys())

    # Build line text
    line_texts = []
    for y in sorted_y:
        sorted_w = sorted(lines[y], key=lambda w: w["x0"])
        line = ""
        prev_x1 = None
        for w in sorted_w:
            text = w.get("text", "").strip()
            if not text:
                continue
            if prev_x1 is not None:
                gap = w["x0"] - prev_x1
                if gap > 5:
                    line += " "
            line += text
            prev_x1 = w["x1"]
        line_texts.append((y, line.strip()))

    if not line_texts:
        return ""

    # Detect paragraphs by line spacing
    if len(line_texts) >= 2:
        spacings = []
        for i in range(1, len(line_texts)):
            spacings.append(line_texts[i][0] - line_texts[i - 1][0])
        if spacings:
            median_spacing = sorted(spacings)[len(spacings) // 2]
            threshold = median_spacing * 1.5
        else:
            threshold = 15
    else:
        threshold = 15

    paragraphs = []
    current_para = [line_texts[0][1]]
    for i in range(1, len(line_texts)):
        gap = line_texts[i][0] - line_texts[i - 1][0]
        if gap > threshold:
            paragraphs.append(" ".join(current_para))
            current_para = [line_texts[i][1]]
        else:
            current_para.append(line_texts[i][1])
    paragraphs.append(" ".join(current_para))

    return "\n\n".join(paragraphs)


def extract_all(pdf_path: str) -> str:
    """Extract full PDF with two-column handling."""
    parts = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            text = extract_page_two_column(page)
            parts.append(f"=== Page {i + 1} ===\n{text}")
    return "\n\n".join(parts)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python pdf_extract_two_column.py <paper.pdf> [output.txt]")
        sys.exit(1)

    pdf_path = sys.argv[1]
    text = extract_all(pdf_path)

    out_path = sys.argv[2] if len(sys.argv) > 2 else Path(pdf_path).with_suffix(".two_column.txt")
    Path(out_path).write_text(text, encoding="utf-8")
    with pdfplumber.open(pdf_path) as pdf:
        n_pages = len(pdf.pages)
    print(f"Extracted {len(text)} chars from {n_pages} pages → {out_path}")
