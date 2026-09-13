"""Simple PDF text extraction using pdfplumber.

Heuristic example for model-guided PDF extraction. Inspect the source pages
first, then adapt thresholds, regions, and reading-order logic to the paper.
A successful run does not establish extraction completeness.

Usage:
    uv run python scripts/pdf_extract_text.py <paper.pdf> [output.txt]
"""

import sys
from pathlib import Path
import pdfplumber


def extract_text(pdf_path: str) -> list[dict]:
    """Extract text from each page of a PDF.

    Returns list of {'page': int, 'text': str} dicts.
    """
    results = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text()
            results.append({"page": i + 1, "text": text or ""})
    return results


def extract_continuous(pdf_path: str) -> str:
    """Extract all text as a single string with page markers."""
    parts = []
    for r in extract_text(pdf_path):
        parts.append(f"--- Page {r['page']} ---\n{r['text']}")
    return "\n\n".join(parts)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python pdf_extract_text.py <paper.pdf> [output.txt]")
        sys.exit(1)

    pdf_path = sys.argv[1]
    text = extract_continuous(pdf_path)

    out_path = sys.argv[2] if len(sys.argv) > 2 else Path(pdf_path).with_suffix(".txt")
    Path(out_path).write_text(text, encoding="utf-8")
    print(f"Extracted {len(text)} chars from {Path(pdf_path).name} → {out_path}")
