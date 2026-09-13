import ast
import re
from pathlib import Path


ROOT = Path(__file__).parents[1]
README_PATH = ROOT / "README.md"
PYPROJECT_PATH = ROOT / "pyproject.toml"
SKILL_PATH = ROOT / "paper-translator" / "SKILL.md"
MINERU_REFERENCE_PATH = (
    ROOT / "paper-translator" / "references" / "mineru-precise-api.md"
)
ENV_EXAMPLE = ROOT / "paper-translator" / ".env.example"
GITIGNORE = ROOT / ".gitignore"
HEURISTIC_SCRIPTS = [
    ROOT / "paper-translator" / "scripts" / "pdf_check_structure.py",
    ROOT / "paper-translator" / "scripts" / "pdf_extract_images.py",
    ROOT / "paper-translator" / "scripts" / "pdf_extract_text.py",
    ROOT / "paper-translator" / "scripts" / "pdf_extract_two_column.py",
]


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


def test_skill_excludes_legacy_setup_and_agent_endpoint_guidance():
    skill = SKILL_PATH.read_text(encoding="utf-8")
    assert "uv add" not in skill
    forbidden_endpoint = "/api/v1/" + "agent/"
    assert forbidden_endpoint not in skill


def test_skill_distinguishes_configuration_from_service_unavailability():
    skill = SKILL_PATH.read_text(encoding="utf-8").lower()
    assert "missing or invalid credentials" in skill
    assert "not service unavailability" in skill
    assert "service unavailability" in skill


def test_release_version_is_consistent_in_readme_and_project_metadata():
    readme = README_PATH.read_text(encoding="utf-8")
    pyproject = PYPROJECT_PATH.read_text(encoding="utf-8")

    assert "1.3.0" in readme
    assert 'version = "1.3.0"' in pyproject


def test_readme_documents_current_precise_first_layout_and_fallback():
    readme = README_PATH.read_text(encoding="utf-8")
    lowered = readme.lower()

    assert "paper-translator/" in readme
    for path in (".env.example", "mineru-precise-api.md", "mineru_precise_extract.py"):
        assert path in readme
    assert "precise-first" in lowered
    assert "adaptive local fallback" in lowered


def test_scope_and_remote_processing_disclosure_are_explicit():
    readme = README_PATH.read_text(encoding="utf-8").lower()
    skill = SKILL_PATH.read_text(encoding="utf-8").lower()
    reference = MINERU_REFERENCE_PATH.read_text(encoding="utf-8").lower()

    for document in (readme, skill, reference):
        assert "whole document" in document
        assert "selected translation scope" in document
    for document in (readme, skill, reference):
        assert "third-party" in document
        assert "non-public url" in document
