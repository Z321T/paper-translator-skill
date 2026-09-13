from __future__ import annotations

import argparse
from dataclasses import dataclass
from io import BytesIO
import json
import os
from pathlib import Path
import shutil
import sys
import time
from typing import Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
import uuid
from zipfile import BadZipFile, ZipFile


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
        values[key.strip()] = value.strip().strip('"').strip("'")
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
    except (TypeError, ValueError) as exc:
        raise MineruError(
            "configuration",
            "MINERU_API_TIMEOUT_SECONDS must be numeric",
            fallback_allowed=False,
        ) from exc
    if timeout <= 0:
        raise MineruError(
            "configuration",
            "MINERU_API_TIMEOUT_SECONDS must be positive",
            fallback_allowed=False,
        )
    return Config(token=token, timeout_seconds=timeout)


def urlopen_request(
    method: str,
    url: str,
    *,
    headers: Mapping[str, str],
    json_body: Mapping[str, object] | None,
    body_file: Path | None,
    timeout: float,
) -> HttpResponse:
    request_headers = dict(headers)
    upload_stream = None
    if body_file is not None:
        # The upload URL is already signed; the API bearer token must not be sent.
        for key in tuple(request_headers):
            if key.lower() == "authorization":
                del request_headers[key]
        upload_stream = body_file.open("rb")
        data = upload_stream
    elif json_body is not None:
        data = json.dumps(json_body).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")
    else:
        data = None
    if any(key.lower() == "authorization" for key in request_headers):
        destination = urlsplit(url)
        origin = f"{destination.scheme}://{destination.netloc}"
        if origin != API_ORIGIN:
            raise MineruError(
                "security",
                "authenticated requests must target the MinerU API origin",
                fallback_allowed=False,
            )
    request = Request(url, data=data, headers=request_headers, method=method)
    try:
        try:
            with urlopen(request, timeout=timeout) as response:
                return HttpResponse(
                    status=response.status,
                    body=response.read(),
                    headers=dict(response.headers.items()),
                )
        except HTTPError as error:
            return HttpResponse(
                status=error.code,
                body=error.read(),
                headers=dict(error.headers.items()),
            )
        except URLError as error:
            raise MineruError("network", "MinerU request failed", fallback_allowed=True) from error
    finally:
        if upload_stream is not None:
            upload_stream.close()


def _decode_api_response(response: HttpResponse) -> dict[str, object]:
    if not 200 <= response.status < 300:
        category = "authentication" if response.status in {401, 403} else "service"
        raise MineruError(
            category,
            "MinerU API request was rejected",
            fallback_allowed=category != "authentication",
        )
    try:
        decoded = json.loads(response.body)
    except (TypeError, ValueError) as exc:
        raise MineruError(
            "service", "MinerU API returned invalid JSON", fallback_allowed=True
        ) from exc
    if not isinstance(decoded, dict):
        raise MineruError(
            "service", "MinerU API returned an invalid response", fallback_allowed=True
        )
    code = decoded.get("code")
    if code != 0:
        authentication = str(code) in {"A0202", "A0211"}
        raise MineruError(
            "authentication" if authentication else "service",
            "MinerU API reported a request failure",
            fallback_allowed=not authentication,
        )
    data = decoded.get("data")
    if not isinstance(data, dict):
        raise MineruError(
            "service", "MinerU API response data is invalid", fallback_allowed=True
        )
    return data


def _remove_path(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def _replace_directory(staging_dir: Path, output_dir: Path) -> None:
    backup_dir: Path | None = None
    if output_dir.exists():
        backup_dir = output_dir.with_name(
            f".{output_dir.name}.backup-{uuid.uuid4().hex}"
        )
        output_dir.replace(backup_dir)
    try:
        staging_dir.replace(output_dir)
    except Exception:
        if backup_dir is not None and backup_dir.exists() and not output_dir.exists():
            backup_dir.replace(output_dir)
        raise
    if backup_dir is not None:
        _remove_path(backup_dir)


class MineruClient:
    def __init__(
        self,
        config: Config,
        request=urlopen_request,
        sleep=time.sleep,
        monotonic=time.monotonic,
    ):
        self.config = config
        self.request = request
        self.sleep = sleep
        self.monotonic = monotonic

    def _api_request(
        self,
        method: str,
        path: str,
        *,
        json_body: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        response = self.request(
            method,
            f"{API_ORIGIN}{path}",
            headers={"Authorization": f"Bearer {self.config.token}"},
            json_body=json_body,
            body_file=None,
            timeout=self.config.timeout_seconds,
        )
        return _decode_api_response(response)

    def _download_result(self, result_url: str, output_dir: Path) -> Path:
        response = self.request(
            "GET",
            result_url,
            headers={},
            json_body=None,
            body_file=None,
            timeout=self.config.timeout_seconds,
        )
        if not 200 <= response.status < 300:
            raise MineruError(
                "result", "MinerU result download failed", fallback_allowed=True
            )
        output_dir.parent.mkdir(parents=True, exist_ok=True)
        staging_dir = output_dir.with_name(
            f".{output_dir.name}.staging-{uuid.uuid4().hex}"
        )
        try:
            staging_dir.mkdir()
            try:
                with ZipFile(BytesIO(response.body)) as archive:
                    staging_root = staging_dir.resolve()
                    markdown_found = False
                    for member in archive.infolist():
                        destination = (staging_dir / member.filename).resolve()
                        if not destination.is_relative_to(staging_root):
                            raise MineruError(
                                "result",
                                "MinerU result archive contains an unsafe path",
                                fallback_allowed=True,
                            )
                        if not member.is_dir() and Path(member.filename).suffix.lower() == ".md":
                            markdown_found = True
                    if not markdown_found:
                        raise MineruError(
                            "result",
                            "MinerU result archive contains no Markdown file",
                            fallback_allowed=True,
                        )
                    archive.extractall(staging_dir)
            except (BadZipFile, OSError) as exc:
                raise MineruError(
                    "result", "MinerU result archive is invalid", fallback_allowed=True
                ) from exc
            _replace_directory(staging_dir, output_dir)
        finally:
            _remove_path(staging_dir)
        return output_dir

    def _submission_options(self, *, ocr: bool, language: str) -> dict[str, object]:
        return {
            "model_version": "vlm",
            "is_ocr": ocr,
            "enable_formula": True,
            "enable_table": True,
            "language": language,
        }

    def _extract_local(
        self, source: Path, output_dir: Path, *, ocr: bool, language: str
    ) -> Path:
        payload = self._submission_options(ocr=ocr, language=language)
        payload["files"] = [{"name": source.name, "data_id": uuid.uuid4().hex}]
        data = self._api_request("POST", "/api/v4/file-urls/batch", json_body=payload)
        batch_id = data.get("batch_id")
        file_urls = data.get("file_urls")
        if not isinstance(batch_id, str) or not batch_id or not isinstance(file_urls, list):
            raise MineruError(
                "service", "MinerU upload response is invalid", fallback_allowed=True
            )
        upload_url = next(
            (
                item.get("url")
                for item in file_urls
                if isinstance(item, dict) and item.get("name") == source.name
            ),
            None,
        )
        if not isinstance(upload_url, str) or not upload_url:
            raise MineruError(
                "service", "MinerU upload URL is missing", fallback_allowed=True
            )
        upload_response = self.request(
            "PUT",
            upload_url,
            headers={},
            json_body=None,
            body_file=source,
            timeout=self.config.timeout_seconds,
        )
        if not 200 <= upload_response.status < 300:
            raise MineruError("service", "MinerU upload failed", fallback_allowed=True)
        deadline = self.monotonic() + self.config.timeout_seconds
        while True:
            data = self._api_request(
                "GET", f"/api/v4/extract-results/batch/{batch_id}"
            )
            results = data.get("extract_result")
            matching_result = next(
                (
                    item
                    for item in results
                    if isinstance(item, dict) and item.get("file_name") == source.name
                ),
                None,
            ) if isinstance(results, list) else None
            if not isinstance(matching_result, dict):
                raise MineruError(
                    "service", "MinerU batch result is invalid", fallback_allowed=True
                )
            state = matching_result.get("state")
            if state == "done":
                result_url = matching_result.get("full_zip_url")
                if not isinstance(result_url, str) or not result_url:
                    raise MineruError(
                        "result", "MinerU task completed without a result archive", fallback_allowed=True
                    )
                return self._download_result(result_url, output_dir)
            if state == "failed":
                raise MineruError("service", "MinerU task failed", fallback_allowed=True)
            if state not in {"waiting-file", "pending", "running", "converting"}:
                raise MineruError(
                    "service", "MinerU task returned an unknown state", fallback_allowed=True
                )
            if self.monotonic() >= deadline:
                raise MineruError("service", "MinerU task timed out", fallback_allowed=True)
            self.sleep(self.config.poll_interval_seconds)

    def extract(
        self,
        source: str,
        output_dir: Path,
        *,
        ocr: bool = False,
        language: str = "en",
    ) -> Path:
        local_source = Path(source)
        if local_source.is_file():
            return self._extract_local(
                local_source, output_dir, ocr=ocr, language=language
            )
        payload = self._submission_options(ocr=ocr, language=language)
        payload["url"] = source
        data = self._api_request("POST", "/api/v4/extract/task", json_body=payload)
        task_id = data.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            raise MineruError("service", "MinerU task ID is invalid", fallback_allowed=True)
        deadline = self.monotonic() + self.config.timeout_seconds
        while True:
            result = self._api_request("GET", f"/api/v4/extract/task/{task_id}")
            state = result.get("state")
            if state == "done":
                result_url = result.get("full_zip_url")
                if not isinstance(result_url, str) or not result_url:
                    raise MineruError(
                        "result", "MinerU task completed without a result archive", fallback_allowed=True
                    )
                return self._download_result(result_url, output_dir)
            if state == "failed":
                raise MineruError("service", "MinerU task failed", fallback_allowed=True)
            if state not in {"pending", "running", "converting"}:
                raise MineruError(
                    "service", "MinerU task returned an unknown state", fallback_allowed=True
                )
            if self.monotonic() >= deadline:
                raise MineruError("service", "MinerU task timed out", fallback_allowed=True)
            self.sleep(self.config.poll_interval_seconds)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extract a paper with MinerU's precise v4 API."
    )
    parser.add_argument("source", help="PDF URL or local PDF path")
    parser.add_argument("--output", type=Path, required=True, help="output directory")
    parser.add_argument(
        "--env-file", type=Path, default=Path(".env"), help="MinerU environment file"
    )
    parser.add_argument("--ocr", action="store_true", help="enable OCR")
    parser.add_argument("--language", default="en", help="document language code")
    return parser


def _sanitized_message(error: MineruError, config: Config | None) -> str:
    message = str(error)
    if config is not None:
        message = message.replace(config.token, "[redacted]")
    return message


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config: Config | None = None
    try:
        config = load_config(args.env_file)
        result = MineruClient(config).extract(
            args.source, args.output, ocr=args.ocr, language=args.language
        )
    except MineruError as error:
        print(
            f"{error.category}: {_sanitized_message(error, config)}", file=sys.stderr
        )
        return 3 if error.fallback_allowed else 2
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
