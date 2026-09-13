# MinerU-First Paper Translation Skill Design

## Objective

Revise `paper-translator` into a model-led translation skill with a clear extraction hierarchy:

1. Use MinerU's authenticated precise API as the preferred extraction path.
2. Treat MinerU output as an extraction draft and verify it against the source PDF.
3. Fall back to model visual inspection plus paper-specific extraction code when MinerU cannot complete the job.
4. Keep bundled PDF parsing scripts as heuristic examples rather than universal parsers.
5. Require the active language model to perform the final Chinese translation.

The output remains a portable bilingual Markdown file with an adjacent asset directory.

## Design Principles

### Source of truth

The source PDF is authoritative. MinerU Markdown, structured JSON, OCR output, and local script output are intermediate evidence. The model must resolve discrepancies by inspecting the relevant PDF pages.

### Division of responsibility

- MinerU and local scripts extract layout, text, formulas, tables, captions, and images.
- The model reconstructs reading order, verifies completeness, corrects extraction errors, and performs the translation.
- Deterministic helpers handle API calls, polling, downloads, path validation, and asset management.
- Heuristic helpers demonstrate techniques that the model may adapt after inspecting the actual paper.

### Secret handling

The repository contains only `.env.example`. A real `.env` belongs in the paper-processing workspace and is excluded by Git.

The API helper loads `MINERU_API_TOKEN` from `.env`. The model checks whether the variable is configured but must not print, quote, copy into commands, store in generated Markdown, or expose its value in logs. The token is sent only in the HTTPS `Authorization` header required by MinerU.

MinerU processing sends the source document to a third-party service. Before uploading a local file or submitting a non-public URL, disclose that data flow and obtain the user's authorization for that document. A configured token does not by itself authorize uploading every document. If authorization is declined, use the local fallback without attempting MinerU.

## Proposed Skill Layout

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

`SKILL.md` contains the decision model and essential invariants. MinerU request details belong in `references/mineru-precise-api.md`. Existing formatting and terminology guidance remains in its current reference files.

## Configuration Contract

`paper-translator/.env.example` contains placeholders only:

```dotenv
MINERU_API_TOKEN=replace_with_your_token
MINERU_API_TIMEOUT_SECONDS=600
```

The helper searches for `.env` in the current paper workspace by default and accepts an explicit `--env-file` path. Environment variables already present in the process take precedence over file values. It never prints the token.

The authenticated API origin is fixed to the official `https://mineru.net` service. Do not accept a token-bearing base URL from `.env` or a CLI argument, because redirecting an authenticated request could disclose the credential.

If `.env` is missing or `MINERU_API_TOKEN` is empty, the workflow stops and asks the user to configure it. Missing credentials are not classified as MinerU service unavailability and do not trigger the automatic local fallback.

## Primary Extraction Path

### Submission

The helper uses only MinerU's authenticated precise API. It must not call `/api/v1/agent/*` or otherwise use the lightweight mode.

- For a remote PDF URL, submit an authenticated precise task and poll its task-result endpoint.
- For a local PDF, request signed upload URLs through the authenticated batch upload flow, upload the file to the signed URL without forwarding the MinerU bearer token, and poll the batch-result endpoint.
- Request the precise `vlm` model with formula and table recognition enabled. Enable OCR when the source is scanned or when an initial inspection shows no usable text layer.
- Download the completed result archive into a task-specific extraction directory.

API fields and endpoints can change. Keep the exact maintained request contract in `references/mineru-precise-api.md`, link to MinerU's official documentation, and fail with an actionable message if the response shape no longer matches the documented contract.

### Safe output handling

The helper must:

- use bounded polling with a configurable overall timeout;
- distinguish authentication, rate-limit, service, task, and local I/O failures;
- download only from the result URL returned by MinerU;
- reject archive entries that escape the destination directory;
- write into a staging directory and publish results only after a complete successful extraction;
- avoid logging request headers, signed upload URLs, or secrets;
- return non-zero status on incomplete work.

### Model verification gate

Successful API completion is not sufficient. Before translating, the model compares the extraction with the PDF and builds a verification inventory containing:

- title, authors, affiliations, venue, and all section headings;
- page coverage and reading order;
- figure and table numbers with captions;
- display equations and equation numbers;
- substantive footnotes and appendix sections;
- extracted image assets and their logical locations.

Inspect the first pages, every page containing a detected figure, table, or display equation, pages around section transitions, and any page with suspicious extraction. Also sample middle and final pages even if no anomaly was reported. Correct discrepancies using the PDF page as authority. Do not start final translation while known omissions or reading-order errors remain unresolved.

## Fallback Extraction Path

Enter the fallback when MinerU is operationally unusable for the document:

- network timeout or connection failure after bounded retries;
- HTTP rate limiting or server failure;
- MinerU task state reports failure;
- document limits or unsupported input prevent precise processing;
- downloaded results are missing, corrupt, or materially incomplete after one clean retry.

An invalid or missing token is a configuration problem. Report it and request correction rather than silently bypassing the required precise path.

### Model-led adaptation

The model first renders or views representative pages and classifies the actual layout: single column, multiple columns, spanning headings, marginal notes, rotated content, scanned pages, full-width figures, cross-page tables, or mixed layouts.

It then chooses among native PDF tools, the installed `pdf` skill's techniques, and task-local code. Bundled scripts are examples of coordinate extraction, column splitting, image rendering, and manifest generation. They are not assumed to cover the document unchanged.

The model may copy and adapt a bundled example into a task-specific working script, tune its thresholds and regions, combine multiple methods, or write a new extractor. It should not modify the installed skill merely to process one paper. A successful exit code proves only that code ran; completeness is established by the same model verification gate used for MinerU output.

## Translation Contract

The active language model performs the final translation. MinerU, OCR engines, extracted Markdown, and helper scripts must not be treated as the final Chinese translation.

Translate every in-scope paragraph without summarizing. Preserve formulas, citations, equation numbers, dataset names, model names, and document hierarchy according to the existing translation format and glossary. For a paper long enough to require scope negotiation, settle full-paper versus selected-section scope before extraction and apply the chosen scope consistently to the appendix and tables.

## Failure and Retry Policy

- Configuration missing: stop and explain how to create `.env` from `.env.example`.
- Authentication rejected: stop, report a credential problem without revealing the value, and ask for a corrected token.
- Rate limit, timeout, or 5xx: retry with bounded backoff, then use the local fallback.
- Task failure or unsupported document: use the local fallback and record the reason.
- Partial or corrupt result: make one clean precise-API retry, then use the local fallback.
- Extraction discrepancy: repair only the affected pages when possible and repeat verification.
- Unrecoverable content: identify the exact pages and elements; do not silently omit them or claim completeness.

The lightweight MinerU API is never a fallback.

## Files to Change

- Rewrite `paper-translator/SKILL.md` around the extraction hierarchy, model responsibilities, verification gate, and failure policy.
- Add `paper-translator/.env.example` with placeholders.
- Add `paper-translator/references/mineru-precise-api.md` with focused current API instructions and official links.
- Add `paper-translator/scripts/mineru_precise_extract.py` as the deterministic precise-API client.
- Update existing script docstrings to say they are heuristic examples that require layout-specific review and adaptation.
- Add tests for the API helper and skill invariants.
- Add `.env` to `.gitignore` while retaining `.env.example`.
- Update `README.md`, dependency metadata only if the implementation requires it, and the project version consistently.

## Test Strategy

### API helper tests

Write tests before the helper implementation and verify that they fail for the missing behavior. Cover:

- loading a placeholder-free token from `.env` without logging it;
- environment variables overriding `.env` values;
- refusing missing or empty credentials;
- using only authenticated precise endpoints;
- omitting the bearer token from signed-file upload requests;
- successful task polling and result download;
- bounded timeout and failure classification;
- safe archive extraction rejecting path traversal;
- staging behavior preserving an existing result on failure.

Mock network boundaries; do not use a real credential in automated tests.

### Skill behavior checks

Use realistic prompts or static invariant checks to verify that the revised skill:

- chooses precise MinerU rather than lightweight extraction;
- stops for missing or rejected credentials;
- verifies API output against the original PDF;
- delegates final translation to the model;
- uses visual inspection before adapting fallback scripts;
- does not equate script success with extraction completeness;
- does not mutate a user's project dependency files merely to run a reference script.

### Final validation

- Run the complete test suite.
- Run the skill quick validator.
- Parse all Python files and exercise every new CLI `--help` path.
- Scan tracked files and diffs for token-like secrets and `.env` files.
- Confirm the Markdown and asset bundle contract remains portable.

## Acceptance Criteria

The revision is complete when:

1. A configured run attempts MinerU precise extraction before local parsing.
2. No lightweight MinerU endpoint is used or recommended.
3. No real token is present in tracked files, tests, examples, command output, or generated documents.
4. A local file or non-public URL is not sent to MinerU without document-specific user authorization.
5. Missing credentials and service unavailability have different, explicit behavior.
6. MinerU output is visually checked against the PDF before translation.
7. Final translation is explicitly model-owned.
8. Fallback scripts are clearly heuristic and layout-adaptive.
9. Existing bilingual structure, formulas, citations, figures, tables, and portability guarantees remain intact.
10. Automated tests and skill validation pass.
