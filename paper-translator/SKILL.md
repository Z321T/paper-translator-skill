---
name: paper-translator
description: Translate English academic paper PDFs into bilingual Chinese markdown documents (English original + Chinese translation side by side). Use when the user provides a PDF of an academic paper and asks for Chinese translation ("翻译论文", "translate this paper", "中英对照", "论文翻译"). Also triggers on requests like "把这个PDF翻译成中文" or "生成论文翻译文档". Covers all academic disciplines with optimized handling for CS/ML papers (ICML, NeurIPS, CVPR, etc. two-column format). Outputs a self-contained markdown file preserving all mathematical notation, tables, and figure/table captions.
---

# Paper Translator

Translate English academic paper PDFs into bilingual Chinese markdown — English original followed by Chinese translation for each section, preserving all academic content.

## Workflow

### Step 1: Assess the PDF

Read the PDF with the Read tool to determine:

- Page count, whether it's two-column or single-column layout
- Paper structure: identify Abstract, Introduction, Method, Experiments, Conclusion, Appendix sections
- Whether the paper is CS/ML (ICML/NeurIPS/CVPR two-column format) or another discipline

For CS papers in two-column format, read pages in groups of 3-5. For single-column papers, read 5-10 pages at a time.

**Page ranges to read** (adaptive, based on what you find):
1. First: pages 1-3 → confirm title, authors, abstract, intro start
2. Middle: pages in chunks to cover method + experiments
3. Last: final pages to capture conclusion + appendix

If the Read tool fails (e.g., `pdftoppm` not found), fall back to Python extraction. Use the reference scripts in `scripts/`:
```bash
uv pip install pdfplumber pypdf
uv run python scripts/pdf_extract_two_column.py <paper.pdf>
```

### Step 2: Extract and Structure Content

When reading the PDF, capture these elements **exactly as written**:

- **Title, authors, affiliations, venue** (from page 1)
- **All section headers** (numbered or named) in their original hierarchy
- **All body text** per section, including inline citations like `(Author et al., 2023)`
- **All mathematical notation**: preserve LaTeX-style formulas exactly — `$...$` for inline, `$$...$$` for display
- **All table content**: numbers, headers, footnotes
- **All figure/table captions**: these are critical — "Figure 1: ..." "Table 2: ..."
- **All footnote content** (substantive footnotes, not just URLs)
- **Appendix content** in full

**Skip**: page numbers, running headers/footers, journal DOI bars, copyright boilerplate, reviewer instructions.

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

Write the complete markdown file as `paper_translation.md` in the project root.

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

### Step 5: Verify Completeness

After writing, check:

- [ ] Every section from the original paper appears in translation
- [ ] All mathematical formulas are preserved verbatim
- [ ] All table/figure captions are translated
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

### Large Papers (30+ pages)

- Read appendix first to understand its length and structure
- For very long appendices with repetitive content (e.g., full hyperparameter tables), translate the descriptive text and note the table structure
- If the paper is a thesis or survey (50+ pages), ask the user if they want full translation or main-body-only

## Reference Files

- **[references/translation-format.md](references/translation-format.md)** — Complete output format specification with annotated examples. Read this when the user has specific formatting requirements or when you need to verify your output matches the expected format.
- **[references/cs-glossary.md](references/cs-glossary.md)** — Standard Chinese translations for common CS/ML technical terms. Read this before starting translation to ensure terminology consistency.

## Reference Scripts

All scripts in `scripts/` are reference code — they should be adapted to the current environment before use. Install dependencies with `uv pip install <package>`.

- **`scripts/pdf_extract_text.py`** — Basic text extraction using pdfplumber. Use as fallback when Read tool cannot render a PDF.
- **`scripts/pdf_extract_two_column.py`** — Two-column layout-aware extraction for academic papers. Uses word-level bounding boxes to detect and separate columns.
- **`scripts/pdf_check_structure.py`** — Quick structure check: page count, metadata, section headers detected via font size analysis.
