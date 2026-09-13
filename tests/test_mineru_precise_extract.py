from __future__ import annotations

import importlib.util
import sys
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
sys.modules[SPEC.name] = mineru
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
