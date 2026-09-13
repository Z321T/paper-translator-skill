# paper-translator v1.3.0

`paper-translator` is a model-led skill for turning an academic PDF into a
portable bilingual Markdown bundle: each English passage is followed by its
Chinese translation, with meaningful figures, tables, formulas, captions, and
relative image links preserved.

## Workflow

1. **Choose scope and output.** Confirm whether the user wants the whole paper
   or selected pages/sections. The current `mineru_precise_extract.py` helper
   extracts the whole document and has no page-range option. Keep that full
   extraction for PDF verification, then apply the selected translation scope
   during verification and translation. The default output is
   `paper_translation.md` beside `paper_translation_assets/`.
2. **Authorize and configure.** MinerU is a third-party service. Before a
   local PDF upload or submission of a remote URL, including a non-public URL,
   disclose the processing and obtain document-specific authorization. Copy
   `paper-translator/.env.example` to `.env` in the paper workspace and fill
   in the token placeholder. Never print or commit the token; `.env` is
   ignored by Git.
3. **Use precise-first extraction.** Run
   `paper-translator/scripts/mineru_precise_extract.py` with MinerU precise v4
   (`model_version: "vlm"`), formula recognition, and table recognition:

   ```text
   uv run python paper-translator/scripts/mineru_precise_extract.py \
     <source.pdf-or-url> --output <extract-directory>
   ```

   Lightweight MinerU extraction is not part of this workflow.
4. **Verify against the PDF.** The source PDF is authoritative. The active
   language model compares MinerU's Markdown, structure metadata, and images
   with rendered PDF pages, checks reading order and completeness, and repairs
   discrepancies before translation.
5. **Use an adaptive local fallback when needed.** Only a fallback-eligible
   precise-extraction failure (for example, a network, service, task, or
   result failure) permits fallback. Missing or rejected credentials are
   configuration/authentication errors and must be fixed instead. First
   inspect the paper's layout, then adapt the bundled heuristic examples for
   that paper; their successful exit code is not a completeness proof.
6. **Translate and audit.** The language model owns the final translation and
   assembly. Preserve formulas and citations, translate captions and
   substantive footnotes, and check that every relative POSIX image link still
   resolves when the Markdown file and its asset directory move together.

See [`paper-translator/SKILL.md`](paper-translator/SKILL.md) for the complete
workflow and [`paper-translator/references/mineru-precise-api.md`](paper-translator/references/mineru-precise-api.md)
for the focused API contract. The API reference is intentionally not
duplicated here.

## Repository layout

```text
paper-translator/
├── .env.example
├── SKILL.md
├── references/
│   ├── cs-glossary.md
│   ├── mineru-precise-api.md
│   └── translation-format.md
└── scripts/
    ├── mineru_precise_extract.py
    ├── pdf_check_structure.py
    ├── pdf_extract_images.py
    ├── pdf_extract_text.py
    └── pdf_extract_two_column.py
```

The `pdf_extract_*.py` files are layout-specific heuristic examples. Adapt
them only after inspecting the source PDF; do not treat them as universal
parsers. A real `.env` belongs in the paper-processing workspace and is never
part of the repository.
