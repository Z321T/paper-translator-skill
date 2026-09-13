# MinerU Precise v4 API Reference

Use this reference only after the translation workflow has selected MinerU precise extraction and the user has authorized the upload. This is a focused reference for `scripts/mineru_precise_extract.py`, not a replacement for the source PDF verification step.

## Official sources and volatile fields

- [MinerU Precision Extract API documentation](https://mineru.net/doc/docs/index_en/)
- [MinerU API rate-limit documentation](https://mineru.net/doc/docs/limit_en/)

Verify volatile fields—endpoints, supported languages, quotas, file/page limits, response schemas, and model options—at those official pages before changing the helper or promising a service capability. This skill deliberately uses only the precise v4 API with `model_version: "vlm"`.

## Configure credentials

Copy `paper-translator/.env.example` to the workspace that contains the paper as `.env`, then replace only the placeholder:

```dotenv
MINERU_API_TOKEN=replace_with_your_token
MINERU_API_TIMEOUT_SECONDS=600
```

Do not commit `.env`, display the token, place it in command arguments, or add it to output files. A missing, blank, malformed, rejected, or unauthorized token is a configuration/authentication error. It is not a service outage and is not eligible for local fallback.

## Run the helper

From the workspace containing the paper, use a local file path:

```text
uv run python paper-translator/scripts/mineru_precise_extract.py paper.pdf --output paper_mineru
```

For a remotely reachable PDF, use its URL:

```text
uv run python paper-translator/scripts/mineru_precise_extract.py https://example.org/paper.pdf --output paper_mineru
```

Optional `--ocr` enables OCR and `--language <code>` supplies the document language. The helper reads `.env` by default; use `--env-file <path>` only when the authorized credential file is elsewhere.

The current helper extracts the whole document and has no page-range option. If the requested output has a selected translation scope, retain the full extraction for verification against the PDF, then apply that selected translation scope during verification and translation.

## Precise v4 protocol used by the helper

All API-origin requests use `Authorization: Bearer <token>` and expect a JSON object with a scalar `code: 0` and object `data` on success. A missing or malformed `code` is a safe schema failure, not a successful response.

| Source | Request and result flow |
| --- | --- |
| URL | `POST /api/v4/extract/task` with `url`, `model_version: "vlm"`, `is_ocr`, `enable_formula: true`, `enable_table: true`, and `language`; poll `GET /api/v4/extract/task/{task_id}`. |
| Local file | `POST /api/v4/file-urls/batch` with `model_version: "vlm"`, formula/table flags, language, and `files`; put `is_ocr` inside `files[0]` (not at the top level); `PUT` the file to the returned signed URL; poll `GET /api/v4/extract-results/batch/{batch_id}`. |

For URL tasks, the helper accepts `pending`, `running`, and `converting` while polling; `done` supplies `full_zip_url`, and `failed` ends the task. For local-file batch results it also accepts `waiting-file`; `done` similarly supplies `full_zip_url`. Any other state, timeout, malformed response, failed task, upload failure, or unusable result archive is treated as a fallback-eligible service/result failure.

The signed upload URL and the signed result-download URL are requested without the bearer token. They are already authorized URLs and may have a different origin; keep the bearer token only on requests to the MinerU API origin.

The helper applies bounded exponential backoff only to network failures,
HTTP 408, HTTP 429, and HTTP 5xx responses. It never retries configuration,
authentication, or malformed-response failures. A corrupt, incomplete, or otherwise unusable
result archive receives one clean precise retry using a new task; if that also
fails, the helper reports a fallback-eligible result error. Every request and
wait uses the remaining overall timeout.

API bearer requests may follow redirects only when the destination remains on
the exact `https://mineru.net` origin. Signed upload and download requests do
not follow redirects at all, so a PDF cannot be sent to a target that was not
authorized by the returned signed URL. Returned upload/result URLs must be
absolute HTTPS URLs without userinfo, fragments, or unsupported schemes.

## Error routing

The helper exits with status 2 for non-fallback errors: configuration, authentication, or security failures. Repair the `.env` value, authorization, or request safety issue and rerun precise extraction.

It exits with status 3 for fallback-eligible network, rate-limit, service,
task, document, result, or archive failures. Only then may the workflow begin
adaptive local fallback, starting with visual layout inspection of rendered
source pages. A local parser run cannot make the source PDF less authoritative.

## Upload disclosure and verification outputs

MinerU is a third-party service. A local-source invocation uploads the PDF to MinerU; a URL-source invocation submits the remote URL—including a non-public URL—so MinerU can retrieve and process the referenced document. Tell the user about this processing and obtain document-specific authorization before either path. Do not upload or submit confidential or restricted material without that authorization.

The downloaded ZIP is published into the requested output directory. During verification, inspect `full.md`, the content-list JSON, model/layout JSON, and the extracted `images/` content alongside rendered PDF pages. File names can vary with MinerU output revisions, so locate the corresponding content-list, model, and layout JSON rather than assuming a fixed optional filename. Confirm the archive represents the source before using it to guide translation.
