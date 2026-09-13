from __future__ import annotations

import importlib.util
import io
import json
import math
import random
import re
import socket
import sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request
from zipfile import ZIP_BZIP2, ZIP_DEFLATED, ZIP_LZMA, ZipFile, ZipInfo

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


def make_zip_info_bytes(info: ZipInfo, contents: bytes) -> bytes:
    archive = io.BytesIO()
    with ZipFile(archive, "w", compression=ZIP_DEFLATED) as zip_file:
        zip_file.writestr(info, contents)
    return archive.getvalue()


def make_corrupt_compressed_zip_bytes(compression: int, corruption_offset: int) -> bytes:
    archive = io.BytesIO()
    contents = b"# Paper\n" + random.Random(7).randbytes(10000)
    with ZipFile(archive, "w", compression=compression) as zip_file:
        zip_file.writestr("full.md", contents)
    corrupted = bytearray(archive.getvalue())
    with ZipFile(io.BytesIO(corrupted)) as zip_file:
        member = zip_file.getinfo("full.md")
    data_offset = (
        member.header_offset
        + 30
        + len(member.filename.encode("utf-8"))
        + len(member.extra)
    )
    assert corruption_offset < member.compress_size
    corrupted[data_offset + corruption_offset] ^= 0xFF
    return bytes(corrupted)


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


def test_load_config_rejects_non_string_token_without_traceback(tmp_path):
    with pytest.raises(mineru.MineruError) as error:
        mineru.load_config(
            tmp_path / ".env", environ={"MINERU_API_TOKEN": None}  # type: ignore[dict-item]
        )

    assert error.value.category == "configuration"
    assert error.value.fallback_allowed is False


@pytest.mark.parametrize("contents", ["", "MINERU_API_TOKEN=\n"])
def test_load_config_rejects_missing_token(tmp_path, contents):
    env_file = tmp_path / ".env"
    env_file.write_text(contents, encoding="utf-8")

    with pytest.raises(mineru.MineruError) as error:
        mineru.load_config(env_file, environ={})

    assert error.value.category == "configuration"
    assert error.value.fallback_allowed is False


def test_config_repr_does_not_disclose_token():
    config = mineru.Config("secret-token-never-log-me")

    assert "secret-token-never-log-me" not in repr(config)


@pytest.mark.parametrize("timeout", [0, -1, math.nan, math.inf, -math.inf])
def test_config_rejects_non_positive_or_non_finite_timeout(timeout):
    with pytest.raises(mineru.MineruError) as error:
        mineru.Config("fake-token", timeout_seconds=timeout)

    assert error.value.category == "configuration"
    assert error.value.fallback_allowed is False


@pytest.mark.parametrize("poll_interval", [-1, math.nan, math.inf, -math.inf])
def test_config_rejects_invalid_poll_interval(poll_interval):
    with pytest.raises(mineru.MineruError) as error:
        mineru.Config("fake-token", poll_interval_seconds=poll_interval)

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


def test_authenticated_redirect_handler_rejects_cross_origin():
    handler = mineru.SafeRedirectHandler(
        policy="api", allowed_origin=mineru.API_ORIGIN
    )
    request = Request("https://mineru.net/api/v4/extract/task")

    with pytest.raises(mineru.MineruError) as error:
        handler.redirect_request(
            request,
            object(),
            302,
            "found",
            {},
            "https://attacker.example/collect",
        )

    assert error.value.category == "security"
    assert error.value.fallback_allowed is False


def test_authenticated_redirect_handler_allows_only_same_mineru_origin():
    handler = mineru.SafeRedirectHandler(
        policy="api", allowed_origin=mineru.API_ORIGIN
    )
    request = Request(
        "https://mineru.net/api/v4/extract/task",
        headers={"Authorization": "Bearer fake-token"},
    )

    redirected = handler.redirect_request(
        request,
        object(),
        307,
        "temporary redirect",
        {},
        "https://mineru.net/api/v4/extract/task/next",
    )

    assert redirected is not None
    assert redirected.full_url == "https://mineru.net/api/v4/extract/task/next"


def test_signed_redirect_handler_rejects_all_redirects():
    handler = mineru.SafeRedirectHandler(
        policy="signed", allowed_origin="https://storage.example"
    )
    request = Request("https://storage.example/signed-upload")

    with pytest.raises(mineru.MineruError) as error:
        handler.redirect_request(
            request,
            object(),
            307,
            "temporary redirect",
            {},
            "https://storage.example/other-upload",
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


@pytest.mark.parametrize("body_file", [None])
def test_request_boundary_rejects_unhandled_redirect_response(monkeypatch, body_file):
    class Response:
        status = 302
        headers = {"Location": "https://attacker.example/collect"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b""

    monkeypatch.setattr(mineru, "urlopen", lambda request, timeout: Response())

    with pytest.raises(mineru.MineruError) as error:
        mineru.urlopen_request(
            "GET",
            "https://cdn.example/signed-result.zip",
            headers={},
            json_body=None,
            body_file=body_file,
            timeout=1,
        )

    assert error.value.category == "security"
    assert error.value.fallback_allowed is False


@pytest.mark.parametrize(
    ("error_type", "message"),
    [
        (socket.timeout, "socket timed out"),
        (TimeoutError, "request timed out"),
        (OSError, "connection reset"),
    ],
    ids=["socket-timeout", "timeout-error", "network-os-error"],
)
def test_urlopen_request_classifies_network_os_errors_as_fallback(
    monkeypatch, error_type, message
):
    def fake_urlopen(request, timeout):
        raise error_type(message)

    monkeypatch.setattr(mineru, "urlopen", fake_urlopen)

    with pytest.raises(mineru.MineruError) as error:
        mineru.urlopen_request(
            "GET",
            "https://mineru.net/api/v4/extract/task",
            headers={"Authorization": "Bearer test-token"},
            json_body=None,
            body_file=None,
            timeout=1,
        )

    assert error.value.category == "network"
    assert error.value.fallback_allowed is True


def test_urlopen_request_preserves_local_file_errors(tmp_path):
    missing_file = tmp_path / "missing.pdf"

    with pytest.raises(mineru.MineruError) as error:
        mineru.urlopen_request(
            "PUT",
            "https://storage.example/signed-upload",
            headers={},
            json_body=None,
            body_file=missing_file,
            timeout=1,
        )

    assert error.value.category == "local_io"
    assert error.value.fallback_allowed is False


def test_http_error_body_read_oserror_is_classified_as_network_fallback(monkeypatch):
    class BrokenErrorBody:
        def read(self):
            raise OSError("connection reset while reading error body")

        def close(self):
            pass

    def fake_urlopen(request, timeout):
        raise HTTPError(
            "https://mineru.net/api/v4/extract/task",
            503,
            "service unavailable",
            {},
            BrokenErrorBody(),
        )

    monkeypatch.setattr(mineru, "urlopen", fake_urlopen)

    with pytest.raises(mineru.MineruError) as error:
        mineru.urlopen_request(
            "GET",
            "https://mineru.net/api/v4/extract/task",
            headers={"Authorization": "Bearer fake-token"},
            json_body=None,
            body_file=None,
            timeout=1,
        )

    assert error.value.category == "network"
    assert error.value.fallback_allowed is True


@pytest.mark.parametrize("status", [401, 403])
def test_http_error_body_read_oserror_preserves_authentication_classification(
    monkeypatch, status
):
    class BrokenErrorBody:
        def read(self):
            raise OSError("connection reset while reading error body")

        def close(self):
            pass

    def fake_urlopen(request, timeout):
        raise HTTPError(
            "https://mineru.net/api/v4/extract/task",
            status,
            "authentication rejected",
            {},
            BrokenErrorBody(),
        )

    monkeypatch.setattr(mineru, "urlopen", fake_urlopen)

    with pytest.raises(mineru.MineruError) as error:
        mineru.urlopen_request(
            "GET",
            "https://mineru.net/api/v4/extract/task",
            headers={"Authorization": "Bearer fake-token"},
            json_body=None,
            body_file=None,
            timeout=1,
        )

    assert error.value.category == "authentication"
    assert error.value.fallback_allowed is False


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
    forbidden_endpoint = "/api/v1/" + "agent/"
    assert all(forbidden_endpoint not in request["url"] for request in requests)


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
    assert "is_ocr" not in requests[0]["json"]
    assert requests[0]["json"]["files"][0]["is_ocr"] is True
    assert requests[0]["json"]["language"] == "ja"
    assert requests[1]["method"] == "PUT"
    assert requests[1]["url"] == "https://storage.example/upload"
    assert requests[1]["body_file"] == source
    assert "Authorization" not in requests[1]["headers"]
    assert "Content-Type" not in requests[1]["headers"]
    assert requests[2]["method"] == "GET"
    assert requests[2]["url"] == "https://mineru.net/api/v4/extract-results/batch/batch-1"


def test_local_file_accepts_string_signed_upload_url(tmp_path):
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"%PDF-1.7")
    requests = []
    responses = [
        mineru.HttpResponse(
            200,
            b'{"code":0,"data":{"batch_id":"batch-1","file_urls":['
            b'"https://storage.example/upload"]}}',
            {},
        ),
        mineru.HttpResponse(200, b"", {}),
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

    result = client.extract(str(source), output_dir)

    assert result == output_dir
    assert (output_dir / "full.md").read_text(encoding="utf-8") == "# Paper"
    assert requests[1]["method"] == "PUT"
    assert requests[1]["url"] == "https://storage.example/upload"
    assert requests[1]["body_file"] == source


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


@pytest.mark.parametrize(
    ("compression", "corruption_offset"),
    [
        (ZIP_DEFLATED, 0),
        (ZIP_BZIP2, 0),
        (ZIP_LZMA, 2),
    ],
    ids=["deflate", "bzip2", "lzma"],
)
def test_corrupt_compressed_member_is_result_error_and_clean_retryable(
    tmp_path, compression, corruption_offset
):
    archive = make_corrupt_compressed_zip_bytes(compression, corruption_offset)

    def fake_request(method, url, *, headers, json_body, body_file, timeout):
        return mineru.HttpResponse(200, archive, {})

    client = mineru.MineruClient(mineru.Config("fake-token"), request=fake_request)

    with pytest.raises(mineru.MineruError) as error:
        client._download_result("https://cdn.example/result.zip", tmp_path / "published")

    assert error.value.category == "result"
    assert error.value.fallback_allowed is True
    assert error.value.clean_retry is True


def test_corrupt_compressed_member_gets_exactly_one_clean_retry(tmp_path):
    archive = make_corrupt_compressed_zip_bytes(ZIP_DEFLATED, 0)
    responses = [
        mineru.HttpResponse(200, b'{"code":0,"data":{"task_id":"task-1"}}', {}),
        mineru.HttpResponse(
            200,
            b'{"code":0,"data":{"state":"done","full_zip_url":"https://cdn.example/bad.zip"}}',
            {},
        ),
        mineru.HttpResponse(200, archive, {}),
        mineru.HttpResponse(200, b'{"code":0,"data":{"task_id":"task-2"}}', {}),
        mineru.HttpResponse(
            200,
            b'{"code":0,"data":{"state":"done","full_zip_url":"https://cdn.example/bad-again.zip"}}',
            {},
        ),
        mineru.HttpResponse(200, archive, {}),
    ]
    requests = []

    def fake_request(method, url, *, headers, json_body, body_file, timeout):
        requests.append((method, url))
        return responses.pop(0)

    client = mineru.MineruClient(
        mineru.Config("fake-token", retry_attempts=1, poll_interval_seconds=0),
        request=fake_request,
        sleep=lambda _: None,
        monotonic=lambda: 0,
    )

    with pytest.raises(mineru.MineruError) as error:
        client.extract("https://example.org/paper.pdf", tmp_path / "published")

    assert error.value.category == "result"
    assert error.value.fallback_allowed is True
    assert len([method for method, _ in requests if method == "POST"]) == 2
    assert len(requests) == 6


def test_result_archive_without_markdown_is_rejected(tmp_path):
    archive = make_zip_bytes({"images/figure.png": b"png"})

    def fake_request(method, url, *, headers, json_body, body_file, timeout):
        return mineru.HttpResponse(200, archive, {})

    client = mineru.MineruClient(mineru.Config("fake-token"), request=fake_request)

    with pytest.raises(mineru.MineruError) as error:
        client._download_result("https://cdn.example/result.zip", tmp_path / "published")

    assert error.value.category == "result"
    assert error.value.fallback_allowed is True


def test_result_archive_rejects_too_many_members(tmp_path, monkeypatch):
    monkeypatch.setattr(mineru, "MAX_ARCHIVE_MEMBERS", 1)
    archive = make_zip_bytes({"one.txt": "1", "two.txt": "2"})

    def fake_request(method, url, *, headers, json_body, body_file, timeout):
        return mineru.HttpResponse(200, archive, {})

    client = mineru.MineruClient(mineru.Config("fake-token"), request=fake_request)

    with pytest.raises(mineru.MineruError) as error:
        client._download_result("https://cdn.example/result.zip", tmp_path / "published")

    assert error.value.category == "result"
    assert error.value.fallback_allowed is True


def test_result_archive_rejects_oversized_member(tmp_path, monkeypatch):
    monkeypatch.setattr(mineru, "MAX_ARCHIVE_MEMBER_BYTES", 1)
    archive = make_zip_bytes({"full.md": "too large"})

    def fake_request(method, url, *, headers, json_body, body_file, timeout):
        return mineru.HttpResponse(200, archive, {})

    client = mineru.MineruClient(mineru.Config("fake-token"), request=fake_request)

    with pytest.raises(mineru.MineruError) as error:
        client._download_result("https://cdn.example/result.zip", tmp_path / "published")

    assert error.value.category == "result"
    assert error.value.fallback_allowed is True


def test_result_archive_rejects_excessive_compression_ratio(tmp_path, monkeypatch):
    monkeypatch.setattr(mineru, "MAX_ARCHIVE_COMPRESSION_RATIO", 1.0)
    info = ZipInfo("full.md")
    info.compress_type = ZIP_DEFLATED
    archive = make_zip_info_bytes(info, b"x" * 1000)

    def fake_request(method, url, *, headers, json_body, body_file, timeout):
        return mineru.HttpResponse(200, archive, {})

    client = mineru.MineruClient(mineru.Config("fake-token"), request=fake_request)

    with pytest.raises(mineru.MineruError) as error:
        client._download_result("https://cdn.example/result.zip", tmp_path / "published")

    assert error.value.category == "result"
    assert error.value.fallback_allowed is True


def test_result_archive_rejects_compressed_download_over_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(mineru, "MAX_ARCHIVE_COMPRESSED_BYTES", 1)
    archive = make_zip_bytes({"full.md": "# Paper"})

    def fake_request(method, url, *, headers, json_body, body_file, timeout):
        return mineru.HttpResponse(200, archive, {})

    client = mineru.MineruClient(mineru.Config("fake-token"), request=fake_request)

    with pytest.raises(mineru.MineruError) as error:
        client._download_result("https://cdn.example/result.zip", tmp_path / "published")

    assert error.value.category == "result"
    assert error.value.fallback_allowed is True


def test_service_result_url_is_validated_before_download(tmp_path):
    requests = []

    def fake_request(method, url, *, headers, json_body, body_file, timeout):
        requests.append((method, url))
        responses = {
            "POST": mineru.HttpResponse(
                200, b'{"code":0,"data":{"task_id":"task-1"}}', {}
            ),
            "GET": mineru.HttpResponse(
                200,
                b'{"code":0,"data":{"state":"done","full_zip_url":"file:///tmp/result.zip"}}',
                {},
            ),
        }
        return responses[method]

    client = mineru.MineruClient(
        mineru.Config("fake-token", poll_interval_seconds=0), request=fake_request
    )

    with pytest.raises(mineru.MineruError) as error:
        client.extract("https://example.org/paper.pdf", tmp_path / "published")

    assert error.value.category == "security"
    assert error.value.fallback_allowed is False
    assert len(requests) == 2


def test_malformed_remote_url_is_a_safe_mineru_error(tmp_path):
    def fail_request(*args, **kwargs):
        raise AssertionError("malformed URL must not reach the network")

    client = mineru.MineruClient(mineru.Config("fake-token"), request=fail_request)

    with pytest.raises(mineru.MineruError) as error:
        client.extract("https://", tmp_path / "published")

    assert error.value.category == "security"
    assert error.value.fallback_allowed is False


@pytest.mark.parametrize(
    "url",
    [
        "https://",
        "https:// bad.example/paper.pdf",
        "https://example.org/paper.pdf ",
        "https://example.org:bad/paper.pdf",
        "https://[bad/paper.pdf",
    ],
)
def test_malformed_remote_url_variants_are_safe_mineru_errors(tmp_path, url):
    client = mineru.MineruClient(
        mineru.Config("fake-token"),
        request=lambda *args, **kwargs: pytest.fail("invalid URL reached network"),
    )

    with pytest.raises(mineru.MineruError) as error:
        client.extract(url, tmp_path / "published")

    assert error.value.category == "security"
    assert error.value.fallback_allowed is False


def test_missing_local_source_is_a_safe_local_io_error(tmp_path):
    client = mineru.MineruClient(
        mineru.Config("fake-token"),
        request=lambda *args, **kwargs: pytest.fail("missing local source reached network"),
    )

    with pytest.raises(mineru.MineruError) as error:
        client.extract(str(tmp_path / "missing.pdf"), tmp_path / "published")

    assert error.value.category == "local_io"
    assert error.value.fallback_allowed is False


def test_output_directory_io_error_is_classified(tmp_path):
    parent_file = tmp_path / "not-a-directory"
    parent_file.write_text("file", encoding="utf-8")
    archive = make_zip_bytes({"full.md": "# Paper"})

    def fake_request(method, url, *, headers, json_body, body_file, timeout):
        return mineru.HttpResponse(200, archive, {})

    client = mineru.MineruClient(mineru.Config("fake-token"), request=fake_request)

    with pytest.raises(mineru.MineruError) as error:
        client._download_result("https://cdn.example/result.zip", parent_file / "published")

    assert error.value.category == "local_io"
    assert error.value.fallback_allowed is False


def test_output_directory_path_shape_error_is_classified(tmp_path):
    archive = make_zip_bytes({"full.md": "# Paper"})

    def fake_request(method, url, *, headers, json_body, body_file, timeout):
        return mineru.HttpResponse(200, archive, {})

    client = mineru.MineruClient(mineru.Config("fake-token"), request=fake_request)

    with pytest.raises(mineru.MineruError) as error:
        client._download_result("https://cdn.example/result.zip", Path("."))

    assert error.value.category == "local_io"
    assert error.value.fallback_allowed is False


def test_output_replace_error_is_classified(tmp_path, monkeypatch):
    archive = make_zip_bytes({"full.md": "# Paper"})

    def fake_request(method, url, *, headers, json_body, body_file, timeout):
        return mineru.HttpResponse(200, archive, {})

    def fail_replace(staging_dir, output_dir):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(mineru, "_replace_directory", fail_replace)
    client = mineru.MineruClient(mineru.Config("fake-token"), request=fake_request)

    with pytest.raises(mineru.MineruError) as error:
        client._download_result("https://cdn.example/result.zip", tmp_path / "published")

    assert error.value.category == "local_io"
    assert error.value.fallback_allowed is False


def test_output_replace_unexpected_error_is_classified(tmp_path, monkeypatch):
    archive = make_zip_bytes({"full.md": "# Paper"})

    def fake_request(method, url, *, headers, json_body, body_file, timeout):
        return mineru.HttpResponse(200, archive, {})

    def fail_replace(staging_dir, output_dir):
        raise RuntimeError("simulated replace failure")

    monkeypatch.setattr(mineru, "_replace_directory", fail_replace)
    client = mineru.MineruClient(mineru.Config("fake-token"), request=fake_request)

    with pytest.raises(mineru.MineruError) as error:
        client._download_result("https://cdn.example/result.zip", tmp_path / "published")

    assert error.value.category == "local_io"
    assert error.value.fallback_allowed is False


def test_output_write_error_is_classified(tmp_path, monkeypatch):
    archive = make_zip_bytes({"full.md": "# Paper"})

    def fake_request(method, url, *, headers, json_body, body_file, timeout):
        return mineru.HttpResponse(200, archive, {})

    original_open = Path.open

    def fail_staging_open(path, *args, **kwargs):
        if ".published.staging-" in str(path):
            raise OSError("simulated output write failure")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_staging_open)
    client = mineru.MineruClient(mineru.Config("fake-token"), request=fake_request)

    with pytest.raises(mineru.MineruError) as error:
        client._download_result("https://cdn.example/result.zip", tmp_path / "published")

    assert error.value.category == "local_io"
    assert error.value.fallback_allowed is False


def test_remote_rate_limit_retry_preserves_reason_and_is_bounded(tmp_path):
    requests = []
    sleeps = []
    responses = [
        mineru.HttpResponse(429, b'{"code":429,"msg":"quota exceeded"}', {}),
        mineru.HttpResponse(503, b'{"code":0,"msg":"temporary outage"}', {}),
        mineru.HttpResponse(200, b'{"code":0,"data":{"task_id":"task-1"}}', {}),
        mineru.HttpResponse(
            200,
            b'{"code":0,"data":{"state":"done","full_zip_url":"https://cdn.example/result.zip"}}',
            {},
        ),
        mineru.HttpResponse(200, make_zip_bytes({"full.md": "# Paper"}), {}),
    ]

    def fake_request(method, url, *, headers, json_body, body_file, timeout):
        requests.append((method, url, timeout))
        return responses.pop(0)

    client = mineru.MineruClient(
        mineru.Config(
            "secret-token",
            timeout_seconds=30,
            poll_interval_seconds=0,
            retry_backoff_seconds=1,
            retry_attempts=3,
        ),
        request=fake_request,
        sleep=sleeps.append,
        monotonic=lambda: 0,
    )

    result = client.extract("https://example.org/paper.pdf", tmp_path / "published")

    assert result.exists()
    assert len(requests) == 5
    assert sleeps == [1, 2]


def test_final_rate_limit_is_fallback_error_with_clean_reason(tmp_path):
    responses = [
        mineru.HttpResponse(429, b'{"code":429,"err_msg":"quota exceeded"}', {}),
        mineru.HttpResponse(429, b'{"code":429,"err_msg":"quota exceeded"}', {}),
        mineru.HttpResponse(429, b'{"code":429,"err_msg":"quota exceeded"}', {}),
    ]

    def fake_request(method, url, *, headers, json_body, body_file, timeout):
        return responses.pop(0)

    client = mineru.MineruClient(
        mineru.Config(
            "secret-token",
            timeout_seconds=30,
            poll_interval_seconds=0,
            retry_backoff_seconds=0,
            retry_attempts=3,
        ),
        request=fake_request,
        sleep=lambda _: None,
        monotonic=lambda: 0,
    )

    with pytest.raises(mineru.MineruError) as error:
        client.extract("https://example.org/paper.pdf", tmp_path / "published")

    assert error.value.category == "rate_limit"
    assert error.value.fallback_allowed is True
    assert "quota exceeded" in str(error.value)
    assert "secret-token" not in str(error.value)


def test_task_failure_preserves_sanitized_reason(tmp_path):
    responses = [
        mineru.HttpResponse(200, b'{"code":0,"data":{"task_id":"task-1"}}', {}),
        mineru.HttpResponse(
            200,
            b'{"code":0,"data":{"state":"failed","err_msg":"unsupported PDF format; token=secret-token"}}',
            {},
        ),
    ]

    def fake_request(method, url, *, headers, json_body, body_file, timeout):
        return responses.pop(0)

    client = mineru.MineruClient(
        mineru.Config("secret-token", timeout_seconds=30, poll_interval_seconds=0),
        request=fake_request,
        sleep=lambda _: None,
        monotonic=lambda: 0,
    )

    with pytest.raises(mineru.MineruError) as error:
        client.extract("https://example.org/paper.pdf", tmp_path / "published")

    assert error.value.category == "document"
    assert error.value.fallback_allowed is True
    assert "unsupported PDF format" in str(error.value)
    assert "secret-token" not in str(error.value)


def test_authentication_failure_is_not_retried(tmp_path):
    requests = []

    def fake_request(method, url, *, headers, json_body, body_file, timeout):
        requests.append((method, url))
        return mineru.HttpResponse(
            401, b'{"code":401,"msg":"invalid token"}', {}
        )

    client = mineru.MineruClient(
        mineru.Config(
            "secret-token",
            timeout_seconds=30,
            retry_backoff_seconds=0,
            retry_attempts=3,
        ),
        request=fake_request,
        sleep=lambda _: None,
        monotonic=lambda: 0,
    )

    with pytest.raises(mineru.MineruError) as error:
        client.extract("https://example.org/paper.pdf", tmp_path / "published")

    assert error.value.category == "authentication"
    assert error.value.fallback_allowed is False
    assert len(requests) == 1


def test_timeout_is_global_and_clamps_sleep_before_next_poll(tmp_path):
    requests = []
    sleeps = []

    class Clock:
        now = 0.0

        def monotonic(self):
            return self.now

        def sleep(self, delay):
            sleeps.append(delay)
            self.now += delay

    clock = Clock()

    def fake_request(method, url, *, headers, json_body, body_file, timeout):
        requests.append((method, url, timeout))
        clock.now += 0.25
        if method == "POST":
            return mineru.HttpResponse(
                200, b'{"code":0,"data":{"task_id":"task-1"}}', {}
            )
        return mineru.HttpResponse(
            200, b'{"code":0,"data":{"state":"running"}}', {}
        )

    client = mineru.MineruClient(
        mineru.Config(
            "fake-token",
            timeout_seconds=1,
            poll_interval_seconds=10,
            retry_backoff_seconds=0,
        ),
        request=fake_request,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )

    with pytest.raises(mineru.MineruError) as error:
        client.extract("https://example.org/paper.pdf", tmp_path / "published")

    assert error.value.fallback_allowed is True
    assert len(requests) == 2
    assert all(timeout > 0 for _, _, timeout in requests)
    assert sleeps == [pytest.approx(0.5)]


def test_corrupt_result_gets_one_clean_precise_retry(tmp_path):
    requests = []
    responses = [
        mineru.HttpResponse(200, b'{"code":0,"data":{"task_id":"task-1"}}', {}),
        mineru.HttpResponse(
            200,
            b'{"code":0,"data":{"state":"done","full_zip_url":"https://cdn.example/bad.zip"}}',
            {},
        ),
        mineru.HttpResponse(200, make_zip_bytes({"images/only.png": b"bad"}), {}),
        mineru.HttpResponse(200, b'{"code":0,"data":{"task_id":"task-2"}}', {}),
        mineru.HttpResponse(
            200,
            b'{"code":0,"data":{"state":"done","full_zip_url":"https://cdn.example/good.zip"}}',
            {},
        ),
        mineru.HttpResponse(200, make_zip_bytes({"full.md": "# Paper"}), {}),
    ]

    def fake_request(method, url, *, headers, json_body, body_file, timeout):
        requests.append((method, url))
        return responses.pop(0)

    client = mineru.MineruClient(
        mineru.Config("fake-token", poll_interval_seconds=0),
        request=fake_request,
        sleep=lambda _: None,
        monotonic=lambda: 0,
    )

    output_dir = tmp_path / "published"
    result = client.extract("https://example.org/paper.pdf", output_dir)

    assert result == output_dir
    assert (output_dir / "full.md").read_text(encoding="utf-8") == "# Paper"
    assert [method for method, _ in requests].count("POST") == 2


def test_result_reason_redacts_urls_and_tokens(tmp_path):
    responses = [
        mineru.HttpResponse(
            500,
            b'{"code":500,"msg":"temporary outage at https://secret.example/x?token=secret-token"}',
            {},
        )
    ]

    def fake_request(method, url, *, headers, json_body, body_file, timeout):
        return responses.pop(0)

    client = mineru.MineruClient(
        mineru.Config(
            "secret-token",
            timeout_seconds=30,
            retry_backoff_seconds=0,
            retry_attempts=1,
        ),
        request=fake_request,
        sleep=lambda _: None,
        monotonic=lambda: 0,
    )

    with pytest.raises(mineru.MineruError) as error:
        client.extract("https://example.org/paper.pdf", tmp_path / "published")

    assert error.value.category == "service"
    assert "temporary outage" in str(error.value)
    assert "https://secret.example" not in str(error.value)
    assert "secret-token" not in str(error.value)


def test_http_error_code_in_body_cannot_bypass_authentication_classification(tmp_path):
    responses = [
        mineru.HttpResponse(
            400, b'{"code":"A0202","msg":"invalid token"}', {}
        )
    ]

    def fake_request(method, url, *, headers, json_body, body_file, timeout):
        return responses.pop(0)

    client = mineru.MineruClient(
        mineru.Config("secret-token", retry_attempts=3, retry_backoff_seconds=0),
        request=fake_request,
        sleep=lambda _: None,
        monotonic=lambda: 0,
    )

    with pytest.raises(mineru.MineruError) as error:
        client.extract("https://example.org/paper.pdf", tmp_path / "published")

    assert error.value.category == "authentication"
    assert error.value.fallback_allowed is False


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (400, "invalid token"),
        (400, "token is invalid"),
        (404, "unauthorized request"),
        (404, "not authorized"),
        (503, "authorization failed"),
        (503, "token revoked"),
        (503, "authentication required"),
    ],
)
def test_http_authentication_reason_is_not_retried(tmp_path, status, reason):
    requests = []

    def fake_request(method, url, *, headers, json_body, body_file, timeout):
        requests.append((method, url))
        return mineru.HttpResponse(status, json.dumps({"msg": reason}).encode(), {})

    client = mineru.MineruClient(
        mineru.Config(
            "secret-token", retry_attempts=3, retry_backoff_seconds=0, timeout_seconds=30
        ),
        request=fake_request,
        sleep=lambda _: None,
        monotonic=lambda: 0,
    )

    with pytest.raises(mineru.MineruError) as error:
        client.extract("https://example.org/paper.pdf", tmp_path / "published")

    assert error.value.category == "authentication"
    assert error.value.fallback_allowed is False
    assert len(requests) == 1
    assert "secret-token" not in str(error.value)


@pytest.mark.parametrize(
    "reason",
    [
        "authentication model is unavailable",
        "credential management is documented",
        "authorization protocol is unsupported",
    ],
)
def test_ordinary_document_reason_is_not_misclassified_as_authentication(
    tmp_path, reason
):
    requests = []

    def fake_request(method, url, *, headers, json_body, body_file, timeout):
        requests.append((method, url))
        return mineru.HttpResponse(
            503, json.dumps({"code": 0, "msg": reason}).encode(), {}
        )

    client = mineru.MineruClient(
        mineru.Config(
            "secret-token", retry_attempts=3, retry_backoff_seconds=0, timeout_seconds=30
        ),
        request=fake_request,
        sleep=lambda _: None,
        monotonic=lambda: 0,
    )

    with pytest.raises(mineru.MineruError) as error:
        client.extract("https://example.org/paper.pdf", tmp_path / "published")

    assert error.value.category == "service"
    assert error.value.fallback_allowed is True
    assert len(requests) == 3


def test_task_authentication_reason_is_not_fallback_or_retried(tmp_path):
    responses = [
        mineru.HttpResponse(200, b'{"code":0,"data":{"task_id":"task-1"}}', {}),
        mineru.HttpResponse(
            200,
            b'{"code":0,"data":{"state":"failed","err_msg":"unauthorized: token=secret-token"}}',
            {},
        ),
    ]
    requests = []

    def fake_request(method, url, *, headers, json_body, body_file, timeout):
        requests.append((method, url))
        return responses.pop(0)

    client = mineru.MineruClient(
        mineru.Config("secret-token", retry_attempts=3, retry_backoff_seconds=0),
        request=fake_request,
        sleep=lambda _: None,
        monotonic=lambda: 0,
    )

    with pytest.raises(mineru.MineruError) as error:
        client.extract("https://example.org/paper.pdf", tmp_path / "published")

    assert error.value.category == "authentication"
    assert error.value.fallback_allowed is False
    assert len(requests) == 2
    assert "unauthorized" in str(error.value)
    assert "secret-token" not in str(error.value)


@pytest.mark.parametrize(
    "code",
    ["A0202", "A0211", 401, 403],
    ids=["A0202", "A0211", "401", "403"],
)
def test_task_authentication_code_is_not_fallback_or_retried(tmp_path, code):
    responses = [
        mineru.HttpResponse(200, b'{"code":0,"data":{"task_id":"task-1"}}', {}),
        mineru.HttpResponse(
            200,
            json.dumps(
                {
                    "code": 0,
                    "data": {
                        "state": "failed",
                        "code": code,
                        "err_msg": "request rejected",
                    },
                }
            ).encode(),
            {},
        ),
    ]
    requests = []

    def fake_request(method, url, *, headers, json_body, body_file, timeout):
        requests.append((method, url))
        return responses.pop(0)

    client = mineru.MineruClient(
        mineru.Config("secret-token", retry_attempts=3, retry_backoff_seconds=0),
        request=fake_request,
        sleep=lambda _: None,
        monotonic=lambda: 0,
    )

    with pytest.raises(mineru.MineruError) as error:
        client.extract("https://example.org/paper.pdf", tmp_path / "published")

    assert error.value.category == "authentication"
    assert error.value.fallback_allowed is False
    assert len(requests) == 2


@pytest.mark.parametrize(
    "body",
    [
        b'{"data":{"task_id":"task-1"}}',
        b'{"code":[],"msg":"temporary"}',
        b'{"code":{},"msg":"temporary"}',
        b'{"code":true,"msg":"temporary"}',
        b'{"code":1.5,"msg":"temporary"}',
        b'{"code":null,"msg":"temporary"}',
        b"[]",
        b"not-json",
    ],
    ids=[
        "missing",
        "list",
        "dict",
        "bool",
        "float",
        "null",
        "top-level-list",
        "invalid-json",
    ],
)
def test_http_503_malformed_response_is_not_retried(tmp_path, body):
    requests = []

    def fake_request(method, url, *, headers, json_body, body_file, timeout):
        requests.append((method, url))
        return mineru.HttpResponse(503, body, {})

    client = mineru.MineruClient(
        mineru.Config(
            "fake-token", retry_attempts=3, retry_backoff_seconds=0, timeout_seconds=30
        ),
        request=fake_request,
        sleep=lambda _: None,
        monotonic=lambda: 0,
    )

    with pytest.raises(mineru.MineruError) as error:
        client.extract("https://example.org/paper.pdf", tmp_path / "published")

    assert error.value.category == "service"
    assert error.value.fallback_allowed is True
    assert error.value.retryable is False
    assert len(requests) == 1


@pytest.mark.parametrize(
    "body",
    [b"", b'{"code":0,"msg":"temporary"}', b'{"code":"0","msg":"temporary"}'],
    ids=["empty", "integer-success-code", "string-success-code"],
)
def test_http_503_without_body_or_with_valid_code_is_retried(tmp_path, body):
    requests = []

    def fake_request(method, url, *, headers, json_body, body_file, timeout):
        requests.append((method, url))
        return mineru.HttpResponse(503, body, {})

    client = mineru.MineruClient(
        mineru.Config(
            "fake-token", retry_attempts=3, retry_backoff_seconds=0, timeout_seconds=30
        ),
        request=fake_request,
        sleep=lambda _: None,
        monotonic=lambda: 0,
    )

    with pytest.raises(mineru.MineruError) as error:
        client.extract("https://example.org/paper.pdf", tmp_path / "published")

    assert error.value.category == "service"
    assert error.value.fallback_allowed is True
    assert len(requests) == 3


@pytest.mark.parametrize(
    "code",
    [
        [],
        {},
        True,
        1.5,
        "not-a-status-code",
    ],
    ids=["list", "dict", "bool", "float", "string"],
)
def test_api_response_rejects_malformed_code_without_raw_type_error(code):
    body = json.dumps({"code": code, "data": {"task_id": "task-1"}}).encode()

    with pytest.raises(mineru.MineruError) as error:
        mineru._decode_api_response(
            mineru.HttpResponse(200, body, {}), token="fake-token"
        )

    assert error.value.category == "service"
    assert error.value.fallback_allowed is True
    assert error.value.retryable is False


def test_api_response_requires_code_field():
    with pytest.raises(mineru.MineruError) as error:
        mineru._decode_api_response(
            mineru.HttpResponse(
                200,
                b'{"msg":"schema changed","data":{"task_id":"task-1"}}',
                {},
            ),
            token="fake-token",
        )

    assert error.value.category == "service"
    assert error.value.fallback_allowed is True
    assert error.value.retryable is False
    assert "schema changed" in str(error.value)


def test_success_response_with_authentication_reason_is_rejected():
    with pytest.raises(mineru.MineruError) as error:
        mineru._decode_api_response(
            mineru.HttpResponse(
                200,
                b'{"code":0,"msg":"unauthorized","data":{"task_id":"task-1"}}',
                {},
            ),
            token="fake-token",
        )

    assert error.value.category == "authentication"
    assert error.value.fallback_allowed is False
    assert error.value.retryable is False


def test_http_408_is_retried_with_a_bounded_attempt_count(tmp_path):
    requests = []
    responses = [
        mineru.HttpResponse(408, b'{"code":408,"msg":"request timeout"}', {}),
        mineru.HttpResponse(408, b'{"code":408,"msg":"request timeout"}', {}),
        mineru.HttpResponse(408, b'{"code":408,"msg":"request timeout"}', {}),
    ]

    def fake_request(method, url, *, headers, json_body, body_file, timeout):
        requests.append((method, url))
        return responses.pop(0)

    client = mineru.MineruClient(
        mineru.Config(
            "fake-token", retry_attempts=3, retry_backoff_seconds=0, timeout_seconds=30
        ),
        request=fake_request,
        sleep=lambda _: None,
        monotonic=lambda: 0,
    )

    with pytest.raises(mineru.MineruError) as error:
        client.extract("https://example.org/paper.pdf", tmp_path / "published")

    assert error.value.category == "service"
    assert error.value.fallback_allowed is True
    assert len(requests) == 3


def test_configured_retry_attempts_remain_globally_bounded(tmp_path):
    requests = []

    def fake_request(method, url, *, headers, json_body, body_file, timeout):
        requests.append((method, url))
        return mineru.HttpResponse(503, b'{"code":503,"msg":"temporary"}', {})

    client = mineru.MineruClient(
        mineru.Config(
            "fake-token",
            timeout_seconds=30,
            retry_attempts=100,
            retry_backoff_seconds=0,
        ),
        request=fake_request,
        sleep=lambda _: None,
        monotonic=lambda: 0,
    )

    with pytest.raises(mineru.MineruError):
        client.extract("https://example.org/paper.pdf", tmp_path / "published")

    assert len(requests) == mineru.MAX_RETRY_ATTEMPTS


def test_upload_url_is_validated_before_signed_upload(tmp_path):
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"%PDF-1.7")
    requests = []

    def fake_request(method, url, *, headers, json_body, body_file, timeout):
        requests.append((method, url))
        return mineru.HttpResponse(
            200,
            b'{"code":0,"data":{"batch_id":"batch-1","file_urls":["file:///tmp/upload"]}}',
            {},
        )

    client = mineru.MineruClient(mineru.Config("fake-token"), request=fake_request)

    with pytest.raises(mineru.MineruError) as error:
        client.extract(str(source), tmp_path / "published")

    assert error.value.category == "security"
    assert error.value.fallback_allowed is False
    assert requests == [("POST", "https://mineru.net/api/v4/file-urls/batch")]


def test_signed_upload_auth_failure_is_not_fallback_or_retried(tmp_path):
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"%PDF-1.7")
    requests = []
    responses = [
        mineru.HttpResponse(
            200,
            b'{"code":0,"data":{"batch_id":"batch-1","file_urls":["https://storage.example/upload"]}}',
            {},
        ),
        mineru.HttpResponse(403, b'{"msg":"signed URL rejected"}', {}),
    ]

    def fake_request(method, url, *, headers, json_body, body_file, timeout):
        requests.append((method, url))
        return responses.pop(0)

    client = mineru.MineruClient(
        mineru.Config("fake-token", retry_attempts=3, retry_backoff_seconds=0),
        request=fake_request,
        sleep=lambda _: None,
        monotonic=lambda: 0,
    )

    with pytest.raises(mineru.MineruError) as error:
        client.extract(str(source), tmp_path / "published")

    assert error.value.category == "authentication"
    assert error.value.fallback_allowed is False
    assert requests == [
        ("POST", "https://mineru.net/api/v4/file-urls/batch"),
        ("PUT", "https://storage.example/upload"),
    ]


@pytest.mark.parametrize(
    ("status", "reason"),
    [(400, "invalid token"), (503, "unauthorized request")],
)
def test_signed_upload_authentication_reason_is_not_retried(
    tmp_path, status, reason
):
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"%PDF-1.7")
    requests = []

    def fake_request(method, url, *, headers, json_body, body_file, timeout):
        requests.append((method, url))
        if method == "POST":
            return mineru.HttpResponse(
                200,
                b'{"code":0,"data":{"batch_id":"batch-1","file_urls":["https://storage.example/upload"]}}',
                {},
            )
        return mineru.HttpResponse(
            status, json.dumps({"msg": reason}).encode(), {}
        )

    client = mineru.MineruClient(
        mineru.Config("secret-token", retry_attempts=3, retry_backoff_seconds=0),
        request=fake_request,
        sleep=lambda _: None,
        monotonic=lambda: 0,
    )

    with pytest.raises(mineru.MineruError) as error:
        client.extract(str(source), tmp_path / "published")

    assert error.value.category == "authentication"
    assert error.value.fallback_allowed is False
    assert requests == [
        ("POST", "https://mineru.net/api/v4/file-urls/batch"),
        ("PUT", "https://storage.example/upload"),
    ]


@pytest.mark.parametrize(
    ("status", "reason"),
    [(400, "invalid token"), (503, "unauthorized result request")],
)
def test_signed_result_authentication_reason_is_not_retried(
    tmp_path, status, reason
):
    requests = []

    def fake_request(method, url, *, headers, json_body, body_file, timeout):
        requests.append((method, url))
        return mineru.HttpResponse(
            status, json.dumps({"msg": reason}).encode(), {}
        )

    client = mineru.MineruClient(
        mineru.Config("secret-token", retry_attempts=3, retry_backoff_seconds=0),
        request=fake_request,
        sleep=lambda _: None,
        monotonic=lambda: 0,
    )

    with pytest.raises(mineru.MineruError) as error:
        client._download_result(
            "https://storage.example/result.zip", tmp_path / "published"
        )

    assert error.value.category == "authentication"
    assert error.value.fallback_allowed is False
    assert requests == [("GET", "https://storage.example/result.zip")]


def test_signed_result_http_408_is_retried(tmp_path):
    archive = make_zip_bytes({"full.md": "# Paper"})
    responses = [
        mineru.HttpResponse(408, b'{"msg":"request timeout"}', {}),
        mineru.HttpResponse(200, archive, {}),
    ]
    requests = []

    def fake_request(method, url, *, headers, json_body, body_file, timeout):
        requests.append((method, url))
        return responses.pop(0)

    client = mineru.MineruClient(
        mineru.Config("fake-token", retry_attempts=2, retry_backoff_seconds=0),
        request=fake_request,
        sleep=lambda _: None,
        monotonic=lambda: 0,
    )

    result = client._download_result(
        "https://storage.example/result.zip", tmp_path / "published"
    )

    assert result.exists()
    assert requests == [
        ("GET", "https://storage.example/result.zip"),
        ("GET", "https://storage.example/result.zip"),
    ]


def test_unsupported_archive_compression_is_a_result_error(tmp_path):
    archive_bytes = bytearray(make_zip_bytes({"full.md": "# Paper"}))
    archive_bytes[8:10] = (99).to_bytes(2, "little")
    central_offset = archive_bytes.find(b"PK\x01\x02")
    assert central_offset >= 0
    archive_bytes[central_offset + 10 : central_offset + 12] = (99).to_bytes(
        2, "little"
    )
    archive = bytes(archive_bytes)

    def fake_request(method, url, *, headers, json_body, body_file, timeout):
        return mineru.HttpResponse(200, archive, {})

    client = mineru.MineruClient(mineru.Config("fake-token"), request=fake_request)

    with pytest.raises(mineru.MineruError) as error:
        client._download_result("https://cdn.example/result.zip", tmp_path / "published")

    assert error.value.category == "result"
    assert error.value.fallback_allowed is True


def test_non_bytes_result_body_is_a_safe_result_error(tmp_path):
    def fake_request(method, url, *, headers, json_body, body_file, timeout):
        return mineru.HttpResponse(200, None, {})  # type: ignore[arg-type]

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
