---
name: paper-translator
description: Use when a user provides an academic PDF and asks for a Chinese translation, bilingual English-Chinese Markdown, paper translation, 中英对照, 翻译论文, or a Markdown document that preserves the PDF's figures, images, tables, formulas, or captions.
---

# Paper Translator

Translate English academic paper PDFs into portable bilingual Markdown bundles — English original followed by Chinese translation for each section, with the paper's meaningful visual content preserved.

## Workflow

### Step 1: Assess the PDF

Read the PDF with the Read tool to determine:

- Page count, whether it's two-column or single-column layout
- Paper structure: identify Abstract, Introduction, Method, Experiments, Conclusion, Appendix sections
- Whether the paper is CS/ML (ICML/NeurIPS/CVPR two-column format) or another discipline
- Visual inventory: figure numbers, tables, photos, plots, diagrams, screenshots, and the pages where they appear
- Target Markdown path. Default to `paper_translation.md`; derive its asset directory as `<markdown-stem>_assets`

For CS papers in two-column format, read pages in groups of 3-5. For single-column papers, read 5-10 pages at a time.

**Page ranges to read** (adaptive, based on what you find):
1. First: pages 1-3 → confirm title, authors, abstract, intro start
2. Middle: pages in chunks to cover method + experiments
3. Last: final pages to capture conclusion + appendix

If the Read tool fails (e.g., `pdftoppm` not found), fall back to Python extraction. Use the reference scripts in `scripts/`:
```bash
uv add pdfplumber pypdf pymupdf
uv run python scripts/pdf_extract_two_column.py <paper.pdf>
```

If the workspace already contains `uv.lock`, run `uv sync` instead of creating another environment. In a workspace without `pyproject.toml`, initialize one with Python 3.12.10 before adding dependencies:

```bash
uv init --bare --python 3.12.10
uv add pdfplumber pypdf pymupdf
```

These commands and all reference scripts must work on Windows, Linux, and macOS. Do not place shell-specific commands or absolute machine paths in generated Markdown.

### Step 2: Extract and Structure Content

When reading the PDF, capture these elements **exactly as written**:

- **Title, authors, affiliations, venue** (from page 1)
- **All section headers** (numbered or named) in their original hierarchy
- **All body text** per section, including inline citations like `(Author et al., 2023)`
- **All mathematical notation**: preserve LaTeX-style formulas exactly — `$...$` for inline, `$$...$$` for display
- **All table content**: numbers, headers, footnotes
- **All meaningful visual content**: figures, photos, plots, diagrams, screenshots, and their relationship to captions
- **All figure/table captions**: these are critical — "Figure 1: ..." "Table 2: ..."
- **All footnote content** (substantive footnotes, not just URLs)
- **Appendix content** in full

**Skip**: page numbers, running headers/footers, journal DOI bars, copyright boilerplate, reviewer instructions.

#### Preserve visual assets

The output is a bundle with the Markdown file and an adjacent asset directory:

```text
paper_translation.md
paper_translation_assets/
  manifest.json
  page-003-image-01.png
  page-005-clip-01-figure-2.png
```

Run the image extractor before assembling the Markdown:

```bash
uv run python scripts/pdf_extract_images.py paper.pdf --markdown paper_translation.md
```

The script automatically renders embedded image blocks as PNG and writes `manifest.json`. Compare every extracted asset with the rendered PDF page. An embedded block can omit vector lines, labels, legends, or other elements that form a complete figure.

For a vector or composite figure, determine its bounding box by viewing the source page, then render the complete region. Coordinates are PDF points in `x0,y0,x1,y1` order; `--clip` may be repeated:

```bash
uv run python scripts/pdf_extract_images.py paper.pdf --markdown paper_translation.md --clip "5:42,118,553,472=figure-2"
```

Each run validates all inputs, renders into a uniquely named sibling staging directory, and replaces the generated asset directory only after the whole run succeeds. The staging directory uses each platform's ordinary directory permission semantics; on Windows, the final asset directory inherits the Markdown output directory's DACL and remains readable without a manual permission prompt. Supply every required `--clip` argument in the final run. The `<markdown-stem>_assets/` directory is generated output and is replaced on rerun; do not store unrelated files in it.

Use this decision rule for each visual:

| Source content | Markdown representation |
|:---------------|:------------------------|
| Photo, microscopy image, screenshot, heatmap, data plot | Preserve the original visual as an extracted or cropped PNG |
| Vector/composite figure | Crop the complete rendered figure; use Mermaid only when every label, edge, group, and direction can be reproduced faithfully |
| Data table | Rebuild as a Markdown table when all cells, headers, notes, and emphasis can be preserved; otherwise include the cropped original as well |
| Decorative rule, publisher logo, repeated header graphic | Omit |

Every meaningful figure must have exactly one of these outcomes: a referenced image asset or a faithful Markdown/Mermaid reconstruction. A translated caption alone is not a preserved figure.

### Step 3: Translate by Section

For each logical section, produce the bilingual output:

**Format pattern** (follow exactly):

```
## Section Number. English Title | 中文标题

English paragraph text as extracted, with all citations and formulas intact.

中文翻译文本，保留原文中的所有引用标记和数学公式。翻译应准确传达原文的学术含义，而非逐字直译。

$$\mathcal{L} = \sum_i \ell(y_i, \hat{y}_i) + \lambda \|\theta\|_2^2$$

公式保持原样不翻译。公式前后用空行分隔。
```

**Translation rules** (by content type):

| Content Type | Action |
|:-------------|:-------|
| Section headers | Translate after `\|` separator, keep English header before it |
| Body text paragraphs | English paragraph → then Chinese translation paragraph |
| Mathematical notation (`$...$`, `$$...$$`) | **Never translate** — keep exactly as original |
| Table content | Reproduce table structure exactly; translate Chinese annotations below. Add Chinese column header translations in parentheses on first occurrence |
| Figure/image content | Insert the image or faithful Markdown reconstruction at the original logical position before its bilingual caption |
| Figure/table captions | Translate fully; keep "Figure X:" / "Table X:" prefix |
| Citations `(Author et al., 2023)` | Keep as-is, do not translate |
| Footnotes `[^1]:` | Translate substantive content; keep URLs unchanged |
| Algorithm numbers / Equation numbers | Keep as-is |
| Proper nouns (model names, dataset names) | Keep English on first use, add Chinese translation in parentheses. E.g., "ResNet-50 (残差网络-50)". Use English only on subsequent mentions |

**Translation quality standards**:

1. **Accurate over literary**: Prioritize faithfully conveying the paper's technical meaning. A technically correct but slightly awkward translation is better than a beautiful but imprecise one.
2. **Consistent terminology**: Use the same Chinese term for the same English concept throughout. Consult `references/cs-glossary.md` for standard CS translations.
3. **Preserve logical flow**: The English→Chinese paragraph pairing should let readers verify translations against the original.
4. **Don't summarize or abbreviate**: Every paragraph in the original must appear in translation. If a paragraph is long, translate all of it.

### Step 4: Assemble the Output Document

Write the complete Markdown file as `paper_translation.md` in the project root, with assets in `paper_translation_assets/`. For a custom Markdown filename, use `<markdown-stem>_assets/` beside it.

Image links must be relative to the Markdown file, use POSIX `/` separators on every operating system, and never use absolute paths or `file://` URIs. Use ASCII lowercase image filenames containing only letters, digits, and hyphens. The extractor percent-encodes spaces, parentheses, and non-ASCII characters in Markdown link destinations when a custom Markdown stem contains them; preserve that encoding. Example:

```markdown
![Figure 1: Overview of the proposed architecture](paper_translation_assets/page-003-figure-1.png)

**Figure 1:** Overview of the proposed architecture.

**图 1：** 所提出架构的总体结构。
```

Replace the extractor's generic manifest alt text with a concise, descriptive alt text based on the figure. Keep the image before the English and Chinese captions. If a figure has subpanels, preserve the complete figure and describe `(a)`, `(b)`, and other panels in the captions rather than splitting it without need.

**Document structure**:

```markdown
# English Paper Title
## 中文论文标题（翻译版）

**Authors**: ... | **Affiliation**: ... | **Venue**: ...
**注**: 原文发表信息

---

## Abstract | 摘要

> English abstract text (blockquote).

> 中文摘要翻译 (blockquote)。

---

## 1. Section Title | 中文章节标题

[English-Chinese paragraph pairs throughout]

---

## Appendix A: Title | 附录A：中文标题

[Full appendix translation]

---

*Paper metadata / copyright notice*
*论文元数据 / 版权声明翻译*
```

**File naming**: Use `paper_translation.md` as default. If the user specifies a different name, use that.

Treat the Markdown file and its `<markdown-stem>_assets/` directory as one portable bundle. They may be moved together to another directory; do not copy only the Markdown file and leave its assets behind.

### Step 5: Verify Completeness

After writing, check:

- [ ] Every section from the original paper appears in translation
- [ ] All mathematical formulas are preserved verbatim
- [ ] All table/figure captions are translated
- [ ] Every meaningful figure is present as an image or faithful Markdown/Mermaid reconstruction, not caption-only
- [ ] Every Markdown image link is relative, uses `/`, and resolves to an existing file
- [ ] `manifest.json` records each extracted or cropped image with its source page and bounding box
- [ ] The asset directory inherits the output directory's access permissions and opens without an ownership or permission prompt
- [ ] The Markdown file and `<markdown-stem>_assets/` directory still work after being moved together
- [ ] All citations are intact
- [ ] Appendix content is fully translated (not summarized)
- [ ] No page numbers or running headers leaked into the output
- [ ] Bilingual format is consistent throughout (English block → Chinese block)

## Handling Difficult Cases

### Two-Column CS Papers

CS conference papers (ICML, NeurIPS, CVPR, etc.) use dense two-column layout. The Read tool may interleave text from left and right columns. When this happens:

1. Continue reading — the interleaving pattern is usually consistent within a page
2. Reconstruct the logical flow from context: section headers, paragraph breaks, figure/table anchors
3. If extraction quality is poor for a specific page, fall back to `scripts/pdf_extract_two_column.py` for that page
4. For critical content (formulas, tables), cross-reference the raw extracted text file

### Papers With Heavy Mathematical Content

- Keep all `\mathbb{}`, `\mathcal{}`, `\mathbf{}`, `\boldsymbol{}` commands
- Keep all `\sum`, `\prod`, `\int`, `\lim` operators
- Keep `\arg\max`, `\arg\min`, `\text{}` blocks
- If a formula spans unusual notation (e.g., tensor diagrams, commutative diagrams), describe it in prose rather than attempting LaTeX reconstruction

### Figures That Do Not Extract Cleanly

- Do not assume an embedded raster is the whole figure; inspect it against the rendered page
- Use `--clip` when labels, arrows, legends, vector layers, or multiple image blocks belong to one figure
- Crop to the visual boundary and exclude surrounding body text; keep the caption as Markdown text outside the PNG when practical
- If automatic extraction produces duplicates, reference only the complete, correct asset in Markdown
- If a visual cannot be extracted or reconstructed accurately, report that item explicitly instead of silently leaving only its caption

### Large Papers (30+ pages)

- Read appendix first to understand its length and structure
- For very long appendices with repetitive content (e.g., full hyperparameter tables), translate the descriptive text and note the table structure
- If the paper is a thesis or survey (50+ pages), ask the user if they want full translation or main-body-only

## Reference Files

- **[references/translation-format.md](references/translation-format.md)** — Complete output format specification with annotated examples. Read this when the user has specific formatting requirements or when you need to verify your output matches the expected format.
- **[references/cs-glossary.md](references/cs-glossary.md)** — Standard Chinese translations for common CS/ML technical terms. Read this before starting translation to ensure terminology consistency.

## Reference Scripts

All scripts in `scripts/` are cross-platform reference code. Use the current `uv` project and install missing dependencies with `uv add <package>`.

- **`scripts/pdf_extract_images.py`** — Extracts embedded images, renders manual crops for vector/composite figures, and emits portable relative Markdown paths in an asset manifest. Uses PyMuPDF.
- **`scripts/pdf_extract_text.py`** — Basic text extraction using pdfplumber. Use as fallback when Read tool cannot render a PDF.
- **`scripts/pdf_extract_two_column.py`** — Two-column layout-aware extraction for academic papers. Uses word-level bounding boxes to detect and separate columns.
- **`scripts/pdf_check_structure.py`** — Quick structure check: page count, metadata, section headers detected via font size analysis.
