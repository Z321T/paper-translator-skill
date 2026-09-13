# MinerU-First Paper Translation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make authenticated MinerU precise extraction the preferred input path while keeping translation and PDF verification model-owned and providing an adaptive local fallback.

**Architecture:** Add a standard-library Python client that loads a workspace `.env`, submits remote or local PDFs only to MinerU's authenticated v4 endpoints, polls with a deadline, and safely publishes downloaded archives. Keep API mechanics in a conditional reference; rewrite the skill entrypoint around a single source-of-truth and fallback decision model, with existing PDF scripts explicitly positioned as adaptable heuristics.

**Tech Stack:** Python 3.12 standard library (`argparse`, `urllib`, `zipfile`, `pathlib`), pytest, Markdown Skill instructions, MinerU precise REST API v4.

**Spec:** `docs/superpowers/specs/2026-09-13-mineru-first-paper-translation-design.md`

## Global Constraints

- Never place a real API token in tracked files, test fixtures, command arguments, logs, or generated output.
- Load `MINERU_API_TOKEN` from a workspace `.env` or the process environment; process variables take precedence.
- Send the Bearer token only to authenticated endpoints under the fixed origin `https://mineru.net`.
- Use only MinerU precise v4 endpoints with `model_version: "vlm"`; never call `/api/v1/agent/*`.
- Obtain document-specific user authorization before uploading a local PDF or submitting a non-public URL.
- Treat the PDF as authoritative and require model verification before translation.
- Treat existing local PDF scripts as heuristic examples that may need paper-specific adaptation.
- Keep the output bundle portable: Markdown links remain relative and use POSIX separators.

---

### Task 1: Configuration, Errors, and HTTP Boundary

**Files:**
- Create: `tests/test_mineru_precise_extract.py`
- Create: `paper-translator/scripts/mineru_precise_extract.py`
- Create: `paper-translator/.env.example`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `Config(token: str, timeout_seconds: float, poll_interval_seconds: float)`.
- Produces: `MineruError(category: str, message: str, fallback_allowed: bool)`.
- Produces: `load_config(env_file: Path, environ: Mapping[str, str] | None = None) -> Config`.
- Produces: `HttpResponse(status: int, body: bytes, headers: Mapping[str, str])`.
- Produces: `urlopen_request(method: str, url: str, *, headers: Mapping[str, str], json_body: Mapping[str, object] | None, body_file: Path | None, timeout: float) -> HttpResponse`.

- [ ] **Step 1: Write failing configuration and secret-safety tests**

Create `tests/test_mineru_precise_extract.py` with a path-based import because the skill directory contains a hyphen:

```python
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

MODULE_PATH = (
    Path(__file__).parents[1]
    / "paper-translator"
    / "scripts"
    / "mineru_precise_extract.py"
)
SPEC = importlib.util.spec_from_file_location("mineru_precise_extract", MODULE_PATH)
assert SPEC and SPEC.loader
mineru = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mineru)


def test_load_config_reads_env_without_printing_token(tmp_path, capsys):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "MINERU_API_TOKEN=test-token-not-a-real-secret\n"
        "MINERU_API_TIMEOUT_SECONDS=45\n",
        encoding="utf-8",
    )

    config = mineru.load_config(env_file, environ={})

    assert config.token == "test-token-not-a-real-secret"
    assert config.timeout_seconds == 45
    assert "test-token" not in capsys.readouterr().out


def test_process_environment_overrides_env_file(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("MINERU_API_TOKEN=file-token\n", encoding="utf-8")

    config = mineru.load_config(
        env_file,
        environ={"MINERU_API_TOKEN": "process-token"},
    )

    assert config.token == "process-token"


@pytest.mark.parametrize("contents", ["", "MINERU_API_TOKEN=\n"])
def test_load_config_rejects_missing_token(tmp_path, contents):
    env_file = tmp_path / ".env"
    env_file.write_text(contents, encoding="utf-8")

    with pytest.raises(mineru.MineruError) as error:
        mineru.load_config(env_file, environ={})

    assert error.value.category == "configuration"
    assert error.value.fallback_allowed is False
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `uv run pytest tests/test_mineru_precise_extract.py -v`

Expected: collection fails because `mineru_precise_extract.py` does not exist.

- [ ] **Step 3: Implement the minimal configuration and HTTP types**

Create the module with these concrete definitions before adding API behavior:

```python
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

API_ORIGIN = "https://mineru.net"
DEFAULT_TIMEOUT_SECONDS = 600.0
DEFAULT_POLL_INTERVAL_SECONDS = 3.0


@dataclass(frozen=True)
class Config:
    token: str
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS


class MineruError(RuntimeError):
    def __init__(self, category: str, message: str, *, fallback_allowed: bool):
        super().__init__(message)
        self.category = category
        self.fallback_allowed = fallback_allowed


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: bytes
    headers: Mapping[str, str]


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"").strip("'")
    return values


def load_config(env_file: Path, environ: Mapping[str, str] | None = None) -> Config:
    file_values = _read_env_file(env_file)
    process_values = os.environ if environ is None else environ
    token = process_values.get("MINERU_API_TOKEN", file_values.get("MINERU_API_TOKEN", "")).strip()
    if not token:
        raise MineruError(
            "configuration",
            f"MINERU_API_TOKEN is missing; create {env_file} from .env.example",
            fallback_allowed=False,
        )
    timeout_text = process_values.get(
        "MINERU_API_TIMEOUT_SECONDS",
        file_values.get("MINERU_API_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS)),
    )
    try:
        timeout = float(timeout_text)
    except ValueError as exc:
        raise MineruError("configuration", "MINERU_API_TIMEOUT_SECONDS must be numeric", fallback_allowed=False) from exc
    if timeout <= 0:
        raise MineruError("configuration", "MINERU_API_TIMEOUT_SECONDS must be positive", fallback_allowed=False)
    return Config(token=token, timeout_seconds=timeout)
```

Implement `urlopen_request` so JSON requests add `Content-Type: application/json`, signed uploads stream the file without an Authorization header, HTTP bodies are captured for classification, and no headers are printed.

- [ ] **Step 4: Add safe example configuration and ignore rule**

Create `paper-translator/.env.example`:

```dotenv
# Copy this file to the workspace containing the paper and name it .env.
MINERU_API_TOKEN=replace_with_your_token
MINERU_API_TIMEOUT_SECONDS=600
```

Append `.env` to `.gitignore`. Do not ignore `.env.example`.

- [ ] **Step 5: Run tests and verify GREEN**

Run: `uv run pytest tests/test_mineru_precise_extract.py -v`

Expected: all configuration tests pass.

- [ ] **Step 6: Commit the configuration boundary**

```bash
git add .gitignore paper-translator/.env.example paper-translator/scripts/mineru_precise_extract.py tests/test_mineru_precise_extract.py
git commit -m "feat: add secure MinerU configuration boundary"
```

---

### Task 2: Precise API Submission, Polling, and Safe Publication

**Files:**
- Modify: `tests/test_mineru_precise_extract.py`
- Modify: `paper-translator/scripts/mineru_precise_extract.py`

**Interfaces:**
- Consumes: `Config`, `HttpResponse`, `MineruError`, `urlopen_request` from Task 1.
- Produces: `MineruClient(config: Config, request=urlopen_request, sleep=time.sleep, monotonic=time.monotonic)`.
- Produces: `MineruClient.extract(source: str, output_dir: Path, *, ocr: bool = False, language: str = "en") -> Path` returning the published extraction directory.
- Produces: CLI `python mineru_precise_extract.py SOURCE --output DIR [--env-file FILE] [--ocr] [--language CODE]`.

- [ ] **Step 1: Add failing remote precise-endpoint tests**

Use an injected fake request callable that records method, URL, headers, and JSON. Return:

```python
responses = [
    mineru.HttpResponse(200, b'{"code":0,"data":{"task_id":"task-1"}}', {}),
    mineru.HttpResponse(200, b'{"code":0,"data":{"state":"done","full_zip_url":"https://cdn.example/result.zip"}}', {}),
    mineru.HttpResponse(200, make_zip_bytes({"full.md": "# Paper"}), {}),
]
```

Assert that submission uses `POST https://mineru.net/api/v4/extract/task`, polling uses `GET https://mineru.net/api/v4/extract/task/task-1`, both MinerU requests carry `Authorization: Bearer <fake token>`, the payload contains `model_version == "vlm"`, `enable_formula is True`, and `enable_table is True`, and no recorded URL contains `/api/v1/agent/`.

- [ ] **Step 2: Run the remote test and verify RED**

Run: `uv run pytest tests/test_mineru_precise_extract.py -k remote -v`

Expected: FAIL because `MineruClient` is undefined.

- [ ] **Step 3: Implement remote submission and bounded polling**

Implement `_decode_api_response` to require HTTP 2xx, JSON object shape, and MinerU `code == 0`. Classify 401/403 and MinerU codes `A0202`/`A0211` as `authentication` with `fallback_allowed=False`; 429, 5xx, and documented temporary-service codes as fallback-allowed service failures.

Implement URL submission with this exact payload:

```python
{
    "url": source,
    "model_version": "vlm",
    "is_ocr": ocr,
    "enable_formula": True,
    "enable_table": True,
    "language": language,
}
```

Poll states `pending`, `running`, and `converting` until `done`, `failed`, an unknown terminal state, or the monotonic deadline. Never include the token in exception messages.

- [ ] **Step 4: Add failing local signed-upload tests**

Create a temporary `paper.pdf`; fake the upload-link response with `batch_id` and one signed URL, then return `waiting-file`, `running`, and `done` batch states. Assert:

- upload-link request is `POST https://mineru.net/api/v4/file-urls/batch`;
- payload contains one file named `paper.pdf`, precise `vlm`, formula/table flags, OCR, and language;
- signed upload is `PUT` with the file body;
- signed upload headers contain no `Authorization` and no forced `Content-Type`;
- polling uses `GET https://mineru.net/api/v4/extract-results/batch/<batch-id>`.

- [ ] **Step 5: Run the local test and verify RED**

Run: `uv run pytest tests/test_mineru_precise_extract.py -k local -v`

Expected: FAIL because local-path routing is not implemented.

- [ ] **Step 6: Implement local upload and batch polling**

Route sources whose `Path.is_file()` is true to the signed-upload flow. Generate a non-secret `data_id` with `uuid.uuid4().hex`. Match the returned batch result by `file_name`, accept `waiting-file`, `pending`, `running`, and `converting` as nonterminal, and require `full_zip_url` at `done`.

- [ ] **Step 7: Add failing safe archive and atomic-publication tests**

Test a valid ZIP containing `full.md` and `images/figure.png`. Test ZIP members `../escape.txt` and `/absolute.txt`; both must raise category `result` with fallback allowed and must not write outside staging. Pre-create an output directory containing `keep.txt`, trigger a corrupt ZIP, and assert `keep.txt` remains unchanged.

- [ ] **Step 8: Run archive tests and verify RED**

Run: `uv run pytest tests/test_mineru_precise_extract.py -k 'archive or publication' -v`

Expected: FAIL because safe extraction and atomic publication are absent.

- [ ] **Step 9: Implement safe download and publication**

Download the result ZIP without Authorization because the result URL is independently signed. Validate every member by resolving it below the staging root before extraction. Require at least one Markdown file. Publish with the same sibling staging, backup, replace, and rollback pattern already used by `pdf_extract_images.py`.

- [ ] **Step 10: Implement the CLI without secret-bearing arguments**

The parser exposes source, output, environment file, OCR, and language options. It must not expose `--token` or `--api-base-url`. On `MineruError`, print only category and sanitized message to stderr and return exit code `2` when fallback is forbidden or `3` when local fallback is permitted.

- [ ] **Step 11: Run all helper tests and verify GREEN**

Run: `uv run pytest tests/test_mineru_precise_extract.py -v`

Expected: all tests pass without network access.

- [ ] **Step 12: Commit the precise API client**

```bash
git add paper-translator/scripts/mineru_precise_extract.py tests/test_mineru_precise_extract.py
git commit -m "feat: add MinerU precise extraction client"
```

---

### Task 3: Rewrite the Skill Around One Decision Model

**Files:**
- Modify: `paper-translator/SKILL.md`
- Create: `paper-translator/references/mineru-precise-api.md`
- Modify: `paper-translator/scripts/pdf_check_structure.py`
- Modify: `paper-translator/scripts/pdf_extract_images.py`
- Modify: `paper-translator/scripts/pdf_extract_text.py`
- Modify: `paper-translator/scripts/pdf_extract_two_column.py`
- Create: `tests/test_skill_contract.py`

**Interfaces:**
- Consumes: `mineru_precise_extract.py` CLI from Task 2.
- Produces: an agent-facing workflow with phases `scope → authorize/configure → precise extract → verify → adaptive fallback if eligible → model translate → final audit`.
- Produces: a conditional MinerU API reference discoverable from `SKILL.md`.

- [ ] **Step 1: Write failing static contract tests**

Create `tests/test_skill_contract.py` that reads `SKILL.md`, `.env.example`, and heuristic script docstrings. Assert:

```python
def test_skill_requires_precise_vlm_and_forbids_lightweight():
    skill = SKILL_PATH.read_text(encoding="utf-8")
    assert "mineru_precise_extract.py" in skill
    assert "precise" in skill.lower()
    assert "model_version" in skill
    assert "vlm" in skill
    assert "lightweight" in skill.lower()
    assert "never" in skill.lower()


def test_skill_makes_pdf_authoritative_and_translation_model_owned():
    skill = SKILL_PATH.read_text(encoding="utf-8").lower()
    assert "source pdf is authoritative" in skill
    assert "language model performs the final translation" in skill


def test_env_example_contains_no_secret_and_real_env_is_ignored():
    example = ENV_EXAMPLE.read_text(encoding="utf-8")
    assert "replace_with_your_token" in example
    assert not re.search(r"sk-[A-Za-z0-9]{16,}", example)
    assert ".env" in GITIGNORE.read_text(encoding="utf-8").splitlines()


def test_fallback_scripts_are_labeled_heuristic_examples():
    for path in HEURISTIC_SCRIPTS:
        module = ast.parse(path.read_text(encoding="utf-8"))
        docstring = ast.get_docstring(module) or ""
        assert "heuristic example" in docstring.lower()
        assert "inspect" in docstring.lower()
        assert "adapt" in docstring.lower()
```

Also assert that `SKILL.md` does not instruct `uv add`, does not mention `/api/v1/agent/`, and routes missing credentials differently from service unavailability.

- [ ] **Step 2: Run contract tests and verify RED**

Run: `uv run pytest tests/test_skill_contract.py -v`

Expected: FAIL because the existing skill lacks the precise-first workflow and heuristic labels.

- [ ] **Step 3: Write the focused MinerU reference**

Create `references/mineru-precise-api.md` containing:

- official documentation links and a note to verify volatile fields there;
- `.env` setup without any real token;
- local and URL CLI examples using `mineru_precise_extract.py`;
- precise endpoints and response states used by the helper;
- authentication versus fallback-eligible errors;
- third-party upload disclosure;
- the fact that signed upload and result URLs do not receive the bearer token;
- the MinerU output files relevant to verification (`full.md`, content list, model/layout JSON, images).

- [ ] **Step 4: Rewrite `SKILL.md` as an unambiguous workflow**

Keep the existing name and a discriminating “Use when…” description. Replace the current Read-first/fallback ambiguity with these explicit sections:

1. `Core contract`: source PDF authoritative; model performs final translation.
2. `Choose scope and output`: page range and portable bundle.
3. `Authorize and configure MinerU`: document-specific upload authorization; require `.env`; read the API reference.
4. `Run precise extraction`: invoke the helper with `vlm`; never use lightweight.
5. `Verify against PDF`: inventory and anomaly-directed visual checks.
6. `Adaptive local fallback`: only for fallback-eligible failures; visually inspect layout before adapting examples.
7. `Translate and assemble`: retain bilingual rules and point to formatting/glossary references.
8. `Final audit`: section, formula, table, figure, citation, appendix, and relative-link checks.

Move detailed examples already present in `translation-format.md` out of the entrypoint rather than duplicating them.

- [ ] **Step 5: Label all local parsers as adaptable examples**

Update each module docstring to include this contract:

```text
Heuristic example for model-guided PDF extraction. Inspect the source pages
first, then adapt thresholds, regions, and reading-order logic to the paper.
A successful run does not establish extraction completeness.
```

Do not change their extraction algorithms in this task.

- [ ] **Step 6: Run contract and helper tests and verify GREEN**

Run: `uv run pytest tests/test_skill_contract.py tests/test_mineru_precise_extract.py -v`

Expected: all tests pass.

- [ ] **Step 7: Commit the workflow rewrite**

```bash
git add paper-translator/SKILL.md paper-translator/references/mineru-precise-api.md paper-translator/scripts tests/test_skill_contract.py
git commit -m "docs: make paper translation model-led and MinerU-first"
```

---

### Task 4: Documentation, Versioning, and End-to-End Validation

**Files:**
- Modify: `README.md`
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `tests/test_skill_contract.py`

**Interfaces:**
- Consumes: completed precise helper and revised skill workflow.
- Produces: version `1.3.0` documentation and repository-wide validation evidence.

- [ ] **Step 1: Add failing documentation consistency tests**

Add assertions that `README.md` and `pyproject.toml` both report `1.3.0`, README uses the actual repository path `paper-translator/`, lists `.env.example`, `mineru-precise-api.md`, and `mineru_precise_extract.py`, and describes both the precise-first and adaptive fallback paths.

- [ ] **Step 2: Run the documentation test and verify RED**

Run: `uv run pytest tests/test_skill_contract.py -k 'version or readme' -v`

Expected: FAIL because the repository still reports `1.2.0` and lacks the new files in its inventory.

- [ ] **Step 3: Update project documentation and version**

Set `project.version = "1.3.0"`. Update README headings, actual path, file inventory, security setup, primary extraction path, fallback semantics, and verification responsibility. Keep README concise and do not duplicate the API reference.

- [ ] **Step 4: Refresh the lockfile without adding runtime dependencies**

Run: `uv lock`

Expected: `uv.lock` records project version `1.3.0`; dependency set is unchanged because the helper uses the standard library.

- [ ] **Step 5: Run the complete automated suite**

Run: `uv run pytest -v`

Expected: all tests pass.

- [ ] **Step 6: Run syntax and CLI checks**

Run: `python -m compileall -q paper-translator/scripts tests`

Run: `uv run python paper-translator/scripts/mineru_precise_extract.py --help`

Expected: both commands exit 0 and CLI help contains no token-valued option.

- [ ] **Step 7: Run the Codex skill validator**

Run: `python /home/lucky/.codex/skills/.system/skill-creator/scripts/quick_validate.py paper-translator`

Expected: validator exits 0.

- [ ] **Step 8: Run secret and endpoint scans**

Run: `git grep -n -E 'sk-[A-Za-z0-9]{16,}' -- ':!uv.lock'`

Expected: no output.

Run: `git grep -n '/api/v1/agent/' -- paper-translator tests`

Expected: no output except a negative assertion in tests if that literal is necessary; prefer constructing the forbidden string in the test to keep the repository scan empty.

Run: `git status --short --ignored`

Expected: `.env` is ignored and `.env.example` remains trackable.

- [ ] **Step 9: Review final diff against the acceptance criteria**

Run: `git diff --check`

Run: `git diff --stat`

Confirm every acceptance criterion in the design spec maps to a passing test or a clearly inspectable instruction.

- [ ] **Step 10: Commit the completed revision**

```bash
git add README.md pyproject.toml uv.lock tests/test_skill_contract.py
git commit -m "release: prepare paper-translator 1.3.0"
```

