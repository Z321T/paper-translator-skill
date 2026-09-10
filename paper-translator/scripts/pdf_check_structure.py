"""Quick PDF structure check: page count, metadata, section headers.

Use to rapidly assess a paper before full translation.
Uses font size heuristics to detect section headers.

Usage:
    uv run python scripts/pdf_check_structure.py <paper.pdf>

Install:
    uv add pdfplumber
"""

import sys
import pdfplumber


def check_structure(pdf_path: str) -> dict:
    """Analyze PDF structure for translation planning.

    Returns dict with page_count, metadata, and detected sections.
    """
    result = {"page_count": 0, "metadata": {}, "large_text_entries": []}

    with pdfplumber.open(pdf_path) as pdf:
        result["page_count"] = len(pdf.pages)

        # Check first page for title-like text
        if pdf.pages:
            p1 = pdf.pages[0]
            words = p1.extract_words()
            # Words with large font size (>14pt) on page 1 are likely title/authors
            large_words = [
                w for w in words
                if w.get("height", 0) and w["height"] > 14
            ]
            if large_words:
                title_line = " ".join(
                    w["text"] for w in sorted(large_words, key=lambda w: (w["top"], w["x0"]))
                )
                result["title_candidate"] = title_line[:200]

            # Detect two-column layout
            if words:
                xs = [w["x0"] for w in words]
                mid_gap = any(
                    abs(w["x0"] - pdf.pages[0].width / 2) < pdf.pages[0].width * 0.1
                    and w.get("text", "").strip()
                    for w in words
                )
                result["likely_two_column"] = (
                    max(xs) - min(xs) > pdf.pages[0].width * 0.7
                )

        # Sample font sizes to detect section headers
        for i, page in enumerate(pdf.pages[:3]):
            words = page.extract_words()
            for w in words:
                h = w.get("height", 0)
                text = w.get("text", "").strip()
                if h > 11 and len(text) > 3 and text[0].isdigit():
                    result["large_text_entries"].append({
                        "page": i + 1,
                        "text": text[:80],
                        "font_size": round(h, 1),
                    })

    return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python pdf_check_structure.py <paper.pdf>")
        sys.exit(1)

    info = check_structure(sys.argv[1])
    print(f"Pages: {info['page_count']}")
    print(f"Two-column layout likely: {info.get('likely_two_column', 'unknown')}")
    if "title_candidate" in info:
        print(f"Title candidate: {info['title_candidate'][:120]}")
    print(f"Large text entries (section header candidates): {len(info['large_text_entries'])}")
    for entry in info["large_text_entries"][:10]:
        print(f"  p{entry['page']} [{entry['font_size']}pt] {entry['text']}")
