---
name: paper-translator
description: Use when a user provides an academic PDF and asks for a Chinese translation, bilingual English-Chinese Markdown, paper translation, 中英对照, 翻译论文, or a portable Markdown bundle that preserves figures, images, tables, formulas, and captions.
---

# Paper Translator

Translate an academic PDF into a portable bilingual Markdown bundle: English original followed by Chinese translation, with meaningful visuals retained in a sibling asset directory.

## Core contract

- The source PDF is authoritative for every claim, formula, table, figure, caption, citation, and reading-order decision. Extraction output is evidence to verify against the PDF, not a replacement for it.
- The active language model performs the final translation and assembly. MinerU and local scripts extract or inspect; they do not own translation quality or completeness.
- Preserve the portable bundle contract: the Markdown file and `<markdown-stem>_assets/` directory move together; image links are relative, use `/`, and resolve within that bundle.

## Workflow

### 1. Choose scope and output

Confirm the requested translation scope before processing. The current helper extracts the whole document and has no page-range option. If the user selected pages or sections, keep the whole extraction for PDF verification, then apply the selected translation scope during verification and translation. Choose `paper_translation.md` by default, with `paper_translation_assets/` beside it; for a custom name, use `<markdown-stem>_assets/`.

Inventory the source PDF before translation: title metadata, authors, affiliations, institutions, venue, page coverage, all section headings, appendix, formulas, tables, figures, captions, substantive footnotes, and likely layout risks (columns, scans, vector composites, or rotated pages). Exclude page numbers, running heads, DOI bars, and other boilerplate.

### 2. Authorize and configure MinerU

Before any upload or URL submission, obtain document-specific authorization: MinerU is a third-party service. A local PDF is uploaded to MinerU, and a remote URL—including a non-public URL—is submitted so MinerU can retrieve and process the referenced document. Disclose this processing before either path. Require a `.env` file copied from `paper-translator/.env.example` and populated with the user's token; never put a token in Markdown, commands, logs, or generated output.

Read [the precise MinerU API reference](references/mineru-precise-api.md) before invoking the helper. It defines the current endpoint, privacy, credential, and error rules.

### 3. Run precise extraction

Use `scripts/mineru_precise_extract.py` for both local PDF paths and URL sources. It uses MinerU precise v4 with `model_version` set to `vlm`, formula recognition, and table recognition.

```text
uv run python paper-translator/scripts/mineru_precise_extract.py <source.pdf-or-url> --output <extract-directory>
```

Never use MinerU lightweight extraction for this workflow. Do not substitute a lightweight endpoint or mode when precise extraction is unavailable.

### 4. Verify against the PDF

Treat the extracted directory as a verification aid. Compare its `full.md`, content list, model/layout JSON, and images with the rendered source pages. Build a verification inventory that records title, authors, affiliations, venue, page coverage, section headings, figure numbers and captions, table numbers and captions, equation numbers, substantive footnotes, appendix sections, and extracted asset locations. Reconcile the structural inventory, then perform anomaly-directed visual checks wherever reading order, formulas, tables, captions, figure boundaries, OCR, or vector layers look uncertain.

Required page checks are not optional: inspect the first pages and last/final pages, sample middle pages, inspect every page containing a figure, every page containing a table, every page containing a display equation, and inspect all pages at section transitions. Also inspect any page flagged as suspicious by extraction. Do not start translation while the inventory has a missing page, section, figure, table, equation, or reading-order discrepancy.

The PDF settles every discrepancy. Do not translate from a plausible but unverified extraction.

### 5. Adaptive local fallback

Use local fallback only after a fallback-eligible precise-extraction failure, such as a network, service, task, or result error. Missing or invalid credentials are configuration or authentication problems, not service unavailability: fix credentials and rerun; do not fall back. The helper reports these as non-fallback errors (exit 2); eligible failures use exit 3.

First inspect rendered source pages to understand the layout. Then adapt the appropriate heuristic example only for the paper at hand:

- `scripts/pdf_check_structure.py` for page and heading reconnaissance;
- `scripts/pdf_extract_text.py` for simple text recovery;
- `scripts/pdf_extract_two_column.py` for column-aware text recovery; and
- `scripts/pdf_extract_images.py` for embedded assets and complete visual crops.

These examples are not completeness proofs. Adjust regions, thresholds, and reading order after visual inspection, and verify their results against the PDF.

### 6. Translate and assemble

Translate every in-scope logical section as English followed by Chinese. Preserve formulas verbatim, keep citations and equation/algorithm markers intact, retain complete tables and figures at their logical positions, translate captions and substantive footnotes, and include the requested appendix scope.

Follow [translation format](references/translation-format.md) for the bilingual structure, asset naming, and annotated examples. Read [the CS glossary](references/cs-glossary.md) before translation when it applies, then maintain terminology consistently. The language model performs the final translation; do not summarize omitted content as a substitute for translation.

### 7. Final audit

Before delivering the bundle, audit it against the source PDF:

- every in-scope section and appendix is present in English and Chinese;
- formulas, citations, footnotes, and numbering are intact;
- tables and figure captions are complete and translated;
- every meaningful figure is an asset or a faithful reconstruction, never caption-only;
- image assets, figure boundaries, and composite/vector visuals match the source; and
- all links are relative, use `/`, resolve to existing files, and remain valid after moving the Markdown and asset directory together.
