from __future__ import annotations

import importlib.util
import io
import re
import sys
from pathlib import Path
from zipfile import ZipFile

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


def make_zip_bytes(files: dict[str, str | bytes]) -> bytes:
    archive = io.BytesIO()
    with ZipFile(archive, "w") as zip_file:
        for name, contents in files.items():
            zip_file.writestr(name, contents)
    return archive.getvalue()


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


def test_authenticated_request_rejects_non_mineru_origin():
    with pytest.raises(mineru.MineruError) as error:
        mineru.urlopen_request(
            "GET",
            "https://attacker.example/upload",
            headers={"Authorization": "Bearer test-token"},
            json_body=None,
            body_file=None,
            timeout=1,
        )

    assert error.value.category == "security"
    assert error.value.fallback_allowed is False


def test_signed_upload_strips_authorization(monkeypatch, tmp_path):
    upload = tmp_path / "upload.bin"
    upload.write_bytes(b"payload")
    seen = {}

    class Response:
        status = 200
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b"ok"

    def fake_urlopen(request, timeout):
        seen["request"] = request
        return Response()

    monkeypatch.setattr(mineru, "urlopen", fake_urlopen)
    response = mineru.urlopen_request(
        "PUT",
        "https://storage.example/signed-upload",
        headers={"Authorization": "Bearer test-token", "Content-Type": "application/pdf"},
        json_body=None,
        body_file=upload,
        timeout=1,
    )

    assert response.status == 200
    assert "Authorization" not in seen["request"].headers


def test_remote_source_uses_precise_v4_endpoints_and_publishes_result(tmp_path):
    requests = []
    responses = [
        mineru.HttpResponse(200, b'{"code":0,"data":{"task_id":"task-1"}}', {}),
        mineru.HttpResponse(
            200,
            b'{"code":0,"data":{"state":"done","full_zip_url":"https://cdn.example/result.zip"}}',
            {},
        ),
        mineru.HttpResponse(200, make_zip_bytes({"full.md": "# Paper"}), {}),
    ]

    def fake_request(method, url, *, headers, json_body, body_file, timeout):
        requests.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers),
                "json": json_body,
                "body_file": body_file,
            }
        )
        return responses.pop(0)

    output_dir = tmp_path / "published"
    client = mineru.MineruClient(
        mineru.Config("fake-token", timeout_seconds=10, poll_interval_seconds=0),
        request=fake_request,
        sleep=lambda _: None,
        monotonic=lambda: 0,
    )

    result = client.extract("https://example.org/paper.pdf", output_dir)

    assert result == output_dir
    assert (output_dir / "full.md").read_text(encoding="utf-8") == "# Paper"
    assert requests[0]["method"] == "POST"
    assert requests[0]["url"] == "https://mineru.net/api/v4/extract/task"
    assert requests[1]["method"] == "GET"
    assert requests[1]["url"] == "https://mineru.net/api/v4/extract/task/task-1"
    assert requests[0]["headers"]["Authorization"] == "Bearer fake-token"
    assert requests[1]["headers"]["Authorization"] == "Bearer fake-token"
    assert requests[0]["json"]["model_version"] == "vlm"
    assert requests[0]["json"]["enable_formula"] is True
    assert requests[0]["json"]["enable_table"] is True
    assert all("/api/v1/agent/" not in request["url"] for request in requests)


def test_local_file_uses_signed_upload_and_batch_polling(tmp_path):
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"%PDF-1.7")
    requests = []
    responses = [
        mineru.HttpResponse(
            200,
            b'{"code":0,"data":{"batch_id":"batch-1","file_urls":['
            b'{"name":"paper.pdf","url":"https://storage.example/upload"}]}}',
            {},
        ),
        mineru.HttpResponse(200, b"", {}),
        mineru.HttpResponse(
            200,
            b'{"code":0,"data":{"extract_result":[{"file_name":"paper.pdf",'
            b'"state":"waiting-file"}]}}',
            {},
        ),
        mineru.HttpResponse(
            200,
            b'{"code":0,"data":{"extract_result":[{"file_name":"paper.pdf",'
            b'"state":"running"}]}}',
            {},
        ),
        mineru.HttpResponse(
            200,
            b'{"code":0,"data":{"extract_result":[{"file_name":"paper.pdf",'
            b'"state":"done","full_zip_url":"https://cdn.example/result.zip"}]}}',
            {},
        ),
        mineru.HttpResponse(200, make_zip_bytes({"full.md": "# Paper"}), {}),
    ]

    def fake_request(method, url, *, headers, json_body, body_file, timeout):
        requests.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers),
                "json": json_body,
                "body_file": body_file,
            }
        )
        return responses.pop(0)

    client = mineru.MineruClient(
        mineru.Config("fake-token", timeout_seconds=10, poll_interval_seconds=0),
        request=fake_request,
        sleep=lambda _: None,
        monotonic=lambda: 0,
    )
    output_dir = tmp_path / "published"

    result = client.extract(str(source), output_dir, ocr=True, language="ja")

    assert result == output_dir
    assert requests[0]["method"] == "POST"
    assert requests[0]["url"] == "https://mineru.net/api/v4/file-urls/batch"
    assert requests[0]["json"]["files"][0]["name"] == "paper.pdf"
    assert re.fullmatch(r"[0-9a-f]{32}", requests[0]["json"]["files"][0]["data_id"])
    assert requests[0]["json"]["model_version"] == "vlm"
    assert requests[0]["json"]["enable_formula"] is True
    assert requests[0]["json"]["enable_table"] is True
    assert requests[0]["json"]["is_ocr"] is True
    assert requests[0]["json"]["language"] == "ja"
    assert requests[1]["method"] == "PUT"
    assert requests[1]["url"] == "https://storage.example/upload"
    assert requests[1]["body_file"] == source
    assert "Authorization" not in requests[1]["headers"]
    assert "Content-Type" not in requests[1]["headers"]
    assert requests[2]["method"] == "GET"
    assert requests[2]["url"] == "https://mineru.net/api/v4/extract-results/batch/batch-1"


def test_result_archive_with_markdown_and_images_is_published(tmp_path):
    archive = make_zip_bytes({"full.md": "# Paper", "images/figure.png": b"png"})

    def fake_request(method, url, *, headers, json_body, body_file, timeout):
        assert method == "GET"
        assert headers == {}
        return mineru.HttpResponse(200, archive, {})

    output_dir = tmp_path / "published"
    client = mineru.MineruClient(mineru.Config("fake-token"), request=fake_request)

    result = client._download_result("https://cdn.example/result.zip", output_dir)

    assert result == output_dir
    assert (output_dir / "full.md").read_text(encoding="utf-8") == "# Paper"
    assert (output_dir / "images" / "figure.png").read_bytes() == b"png"


@pytest.mark.parametrize("member", ["../escape.txt", "/absolute.txt"])
def test_result_archive_rejects_unsafe_member_without_writing_outside(tmp_path, member):
    archive = make_zip_bytes({member: "unsafe", "full.md": "# Paper"})

    def fake_request(method, url, *, headers, json_body, body_file, timeout):
        return mineru.HttpResponse(200, archive, {})

    output_dir = tmp_path / "published"
    client = mineru.MineruClient(mineru.Config("fake-token"), request=fake_request)

    with pytest.raises(mineru.MineruError) as error:
        client._download_result("https://cdn.example/result.zip", output_dir)

    assert error.value.category == "result"
    assert error.value.fallback_allowed is True
    assert not (tmp_path / "escape.txt").exists()
    assert not (tmp_path / "absolute.txt").exists()
    assert not output_dir.exists()


def test_corrupt_result_archive_preserves_existing_publication(tmp_path):
    output_dir = tmp_path / "published"
    output_dir.mkdir()
    (output_dir / "keep.txt").write_text("keep", encoding="utf-8")

    def fake_request(method, url, *, headers, json_body, body_file, timeout):
        return mineru.HttpResponse(200, b"not a zip", {})

    client = mineru.MineruClient(mineru.Config("fake-token"), request=fake_request)

    with pytest.raises(mineru.MineruError) as error:
        client._download_result("https://cdn.example/result.zip", output_dir)

    assert error.value.category == "result"
    assert error.value.fallback_allowed is True
    assert (output_dir / "keep.txt").read_text(encoding="utf-8") == "keep"


def test_result_archive_without_markdown_is_rejected(tmp_path):
    archive = make_zip_bytes({"images/figure.png": b"png"})

    def fake_request(method, url, *, headers, json_body, body_file, timeout):
        return mineru.HttpResponse(200, archive, {})

    client = mineru.MineruClient(mineru.Config("fake-token"), request=fake_request)

    with pytest.raises(mineru.MineruError) as error:
        client._download_result("https://cdn.example/result.zip", tmp_path / "published")

    assert error.value.category == "result"
    assert error.value.fallback_allowed is True


def test_cli_exposes_operational_options_without_secret_arguments():
    parser = mineru.build_parser()
    option_strings = {
        option for action in parser._actions for option in action.option_strings
    }

    assert {"--output", "--env-file", "--ocr", "--language"} <= option_strings
    assert "--token" not in option_strings
    assert "--api-base-url" not in option_strings


@pytest.mark.parametrize(
    ("error", "expected_exit"),
    [
        (mineru.MineruError("authentication", "fake-token was rejected", fallback_allowed=False), 2),
        (mineru.MineruError("service", "temporary failure", fallback_allowed=True), 3),
    ],
)
def test_cli_reports_sanitized_mineru_error_and_fallback_exit_code(
    monkeypatch, capsys, tmp_path, error, expected_exit
):
    class FailingClient:
        def __init__(self, config):
            self.config = config

        def extract(self, source, output_dir, *, ocr, language):
            raise error

    monkeypatch.setattr(
        mineru, "load_config", lambda env_file: mineru.Config("fake-token")
    )
    monkeypatch.setattr(mineru, "MineruClient", FailingClient)

    exit_code = mineru.main(
        ["https://example.org/paper.pdf", "--output", str(tmp_path / "published")]
    )

    captured = capsys.readouterr()
    assert exit_code == expected_exit
    assert captured.out == ""
    assert captured.err.startswith(f"{error.category}:")
    assert "fake-token" not in captured.err
