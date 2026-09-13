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
        request_headers.pop("Authorization", None)
        upload_stream = body_file.open("rb")
        data = upload_stream
    elif json_body is not None:
        data = json.dumps(json_body).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")
    else:
        data = None
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
