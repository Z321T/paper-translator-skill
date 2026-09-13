"""Deterministic client for MinerU's authenticated precise v4 extraction API.

The client deliberately keeps authentication, retry, deadline, URL, archive,
and publication policy in one small standard-library module. The returned
directory is an extraction aid; the source PDF remains authoritative.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from io import BytesIO
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import time
from typing import Callable, Mapping, TypeVar
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import uuid
from zipfile import ZipFile


API_ORIGIN = "https://mineru.net"
DEFAULT_TIMEOUT_SECONDS = 600.0
DEFAULT_POLL_INTERVAL_SECONDS = 3.0
DEFAULT_RETRY_ATTEMPTS = 3
DEFAULT_RETRY_BACKOFF_SECONDS = 1.0
MAX_RETRY_ATTEMPTS = 5

# Conservative limits for a paper extraction archive. They prevent a result
# ZIP from consuming unbounded memory/disk while leaving room for image-heavy
# papers.
MAX_ARCHIVE_COMPRESSED_BYTES = 100 * 1024 * 1024
MAX_ARCHIVE_TOTAL_BYTES = 250 * 1024 * 1024
MAX_ARCHIVE_MEMBER_BYTES = 100 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 4096
MAX_ARCHIVE_COMPRESSION_RATIO = 100.0
MAX_ARCHIVE_MEMBER_NAME_LENGTH = 4096

# Conservative authentication-code allowlist. A0202/A0211 are the codes
# named by this repository's MinerU contract; 401/403 mirror HTTP auth
# statuses. Unknown response codes must not be guessed to be authentication.
_AUTHENTICATION_CODES = frozenset({"A0202", "A0211", "401", "403"})

_AUTHENTICATION_REASON_PATTERNS = (
    r"\b(?:invalid|expired|revoked|rejected)\s+(?:access\s+)?tokens?\b",
    r"\b(?:access\s+)?tokens?\s+(?:(?:is|are|was|were|has|have|has\s+been|have\s+been)\s+)?(?:invalid|expired|revoked|rejected)\b",
    r"\b(?:access\s+)?tokens?\s+(?:is\s+)?not\s+valid\b",
    r"\bunauthori[sz]ed\b",
    r"\bnot\s+authori[sz]ed\b",
    r"\bauthori[sz]ation\s+(?:(?:is|was|has\s+been)\s+)?(?:failed|failure|required|rejected|denied|error)\b",
    r"\bauthentication\s+(?:(?:is|was|has\s+been)\s+)?(?:failed|failure|required|rejected|denied|error)\b",
    r"\bnot\s+authenticated\b",
    r"\bpermission\s+denied\b",
    r"\baccess\s+denied\b",
    r"\b(?:invalid|expired|revoked|rejected|missing)\s+credentials?\b",
    r"\bcredentials?\s+(?:(?:are|were|was|have|has|have\s+been|has\s+been)\s+)?(?:invalid|expired|revoked|rejected|missing)\b",
)

_T = TypeVar("_T")


class MineruError(RuntimeError):
    """A safe, classified failure from configuration, I/O, or MinerU."""

    def __init__(
        self,
        category: str,
        message: str,
        *,
        fallback_allowed: bool,
        retryable: bool = False,
        clean_retry: bool = False,
    ):
        super().__init__(message)
        self.category = category
        self.fallback_allowed = fallback_allowed
        self.retryable = retryable
        self.clean_retry = clean_retry


@dataclass(frozen=True)
class Config:
    # repr=False is an additional guard against accidental credential logging.
    token: str = field(repr=False)
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS
    retry_attempts: int = DEFAULT_RETRY_ATTEMPTS
    retry_backoff_seconds: float = DEFAULT_RETRY_BACKOFF_SECONDS

    def __post_init__(self) -> None:
        if not isinstance(self.token, str) or not self.token.strip():
            raise MineruError(
                "configuration",
                "MINERU_API_TOKEN is missing",
                fallback_allowed=False,
            )
        if not _is_finite_positive(self.timeout_seconds):
            raise MineruError(
                "configuration",
                "MINERU_API_TIMEOUT_SECONDS must be a finite positive number",
                fallback_allowed=False,
            )
        if not _is_finite_nonnegative(self.poll_interval_seconds):
            raise MineruError(
                "configuration",
                "MINERU_API_POLL_INTERVAL_SECONDS must be a finite non-negative number",
                fallback_allowed=False,
            )
        if (
            isinstance(self.retry_attempts, bool)
            or not isinstance(self.retry_attempts, int)
            or self.retry_attempts < 1
        ):
            raise MineruError(
                "configuration",
                "MINERU_API_RETRY_ATTEMPTS must be a positive integer",
                fallback_allowed=False,
            )
        if not _is_finite_nonnegative(self.retry_backoff_seconds):
            raise MineruError(
                "configuration",
                "MINERU_API_RETRY_BACKOFF_SECONDS must be finite and non-negative",
                fallback_allowed=False,
            )


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: bytes
    headers: Mapping[str, str]


def _is_finite_positive(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value > 0
    )


def _is_finite_nonnegative(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        if not path.is_file():
            return values
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise MineruError(
            "configuration",
            "unable to read the MinerU environment file",
            fallback_allowed=False,
        ) from exc
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _config_value(
    name: str,
    file_values: Mapping[str, str],
    process_values: Mapping[str, str],
    default: str,
) -> str:
    return process_values.get(name, file_values.get(name, default))


def _parse_float_config(name: str, value: object, *, positive: bool) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise MineruError(
            "configuration",
            f"{name} must be numeric",
            fallback_allowed=False,
        ) from exc
    valid = _is_finite_positive(parsed) if positive else _is_finite_nonnegative(parsed)
    if not valid:
        qualifier = "finite and positive" if positive else "finite and non-negative"
        raise MineruError(
            "configuration",
            f"{name} must be {qualifier}",
            fallback_allowed=False,
        )
    return parsed


def load_config(env_file: Path, environ: Mapping[str, str] | None = None) -> Config:
    file_values = _read_env_file(env_file)
    process_values = os.environ if environ is None else environ
    token_value = _config_value("MINERU_API_TOKEN", file_values, process_values, "")
    token = token_value.strip() if isinstance(token_value, str) else ""
    if not token:
        raise MineruError(
            "configuration",
            f"MINERU_API_TOKEN is missing; create {env_file} from .env.example",
            fallback_allowed=False,
        )
    timeout = _parse_float_config(
        "MINERU_API_TIMEOUT_SECONDS",
        _config_value(
            "MINERU_API_TIMEOUT_SECONDS",
            file_values,
            process_values,
            str(DEFAULT_TIMEOUT_SECONDS),
        ),
        positive=True,
    )
    poll_interval = _parse_float_config(
        "MINERU_API_POLL_INTERVAL_SECONDS",
        _config_value(
            "MINERU_API_POLL_INTERVAL_SECONDS",
            file_values,
            process_values,
            str(DEFAULT_POLL_INTERVAL_SECONDS),
        ),
        positive=False,
    )
    retry_attempts_text = _config_value(
        "MINERU_API_RETRY_ATTEMPTS",
        file_values,
        process_values,
        str(DEFAULT_RETRY_ATTEMPTS),
    )
    try:
        retry_attempts = int(retry_attempts_text)
    except (TypeError, ValueError) as exc:
        raise MineruError(
            "configuration",
            "MINERU_API_RETRY_ATTEMPTS must be a positive integer",
            fallback_allowed=False,
        ) from exc
    retry_backoff = _parse_float_config(
        "MINERU_API_RETRY_BACKOFF_SECONDS",
        _config_value(
            "MINERU_API_RETRY_BACKOFF_SECONDS",
            file_values,
            process_values,
            str(DEFAULT_RETRY_BACKOFF_SECONDS),
        ),
        positive=False,
    )
    return Config(
        token=token,
        timeout_seconds=timeout,
        poll_interval_seconds=poll_interval,
        retry_attempts=retry_attempts,
        retry_backoff_seconds=retry_backoff,
    )


def _safe_reason(value: object, token: str | None = None) -> str:
    """Keep useful API reason text without exposing URLs, tokens, or controls."""

    if value is None:
        return ""
    text = str(value)
    if token:
        text = text.replace(token, "[redacted]")
    text = re.sub(r"(?i)bearer\s+[^\s,;]+", "Bearer [redacted]", text)
    text = re.sub(r"https?://[^\s<>\"']+", "[redacted-url]", text)
    text = re.sub(
        r"(?i)\b(token|authorization|secret|signature|password|access[_-]?key)\s*[=:]\s*[^\s,;]+",
        r"\1=[redacted]",
        text,
    )
    text = " ".join("".join(char if char.isprintable() else " " for char in text).split())
    return text[:500]


def _response_json_payload(response: HttpResponse) -> tuple[object | None, bool]:
    try:
        return json.loads(response.body), True
    except (TypeError, ValueError, UnicodeDecodeError):
        return None, False


def _response_json(response: HttpResponse) -> dict[str, object] | None:
    decoded, parsed = _response_json_payload(response)
    return decoded if parsed and isinstance(decoded, dict) else None


def _reason_from_mapping(mapping: Mapping[str, object] | None) -> str:
    if not mapping:
        return ""
    for key in ("err_msg", "msg", "message", "error", "detail"):
        value = mapping.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def _response_reason(response: HttpResponse, token: str | None = None) -> str:
    decoded = _response_json(response)
    return _safe_reason(_reason_from_mapping(decoded), token)


def _is_authentication_reason(reason: str) -> bool:
    lowered = reason.lower()
    return any(re.search(pattern, lowered) for pattern in _AUTHENTICATION_REASON_PATTERNS)


def _classify_reason(reason: str, default: str) -> str:
    if _is_authentication_reason(reason):
        return "authentication"
    lowered = reason.lower()
    if any(term in lowered for term in ("rate limit", "too many request", "quota")):
        return "rate_limit"
    if any(
        term in lowered
        for term in (
            "unsupported",
            "document",
            "pdf",
            "file",
            "page limit",
            "page count",
            "format",
            "size limit",
        )
    ):
        return "document"
    return default


def _response_code_text(value: object) -> str:
    if isinstance(value, bool):
        return ""
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return value.strip().upper()
    return ""


def _is_valid_code(value: object) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    return isinstance(value, str) and bool(value.strip())


def _is_authentication_code(value: object) -> bool:
    return _response_code_text(value) in _AUTHENTICATION_CODES


def _response_body_is_empty(response: HttpResponse) -> bool:
    body = response.body
    if body is None:
        return True
    if isinstance(body, (bytes, bytearray, str)):
        return not body.strip()
    return False


def _is_success_code(value: object) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and value == 0
    ) or (isinstance(value, str) and value.strip() == "0")


def _validate_url(url: object, *, require_https: bool, purpose: str) -> str:
    if (
        not isinstance(url, str)
        or not url.strip()
        or any(char.isspace() or ord(char) < 32 for char in url)
    ):
        raise MineruError(
            "security",
            f"MinerU returned an invalid {purpose} URL",
            fallback_allowed=False,
        )
    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
        parsed.port  # Force malformed-port validation.
    except ValueError as exc:
        raise MineruError(
            "security",
            f"MinerU returned an invalid {purpose} URL",
            fallback_allowed=False,
        ) from exc
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or hostname is None
        or not hostname.strip()
        or any(char.isspace() for char in parsed.netloc)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise MineruError(
            "security",
            f"MinerU returned an invalid {purpose} URL",
            fallback_allowed=False,
        )
    if require_https and parsed.scheme.lower() != "https":
        raise MineruError(
            "security",
            f"MinerU returned an insecure {purpose} URL",
            fallback_allowed=False,
        )
    return url


def _origin(url: str) -> tuple[str, str, int]:
    _validate_url(url, require_https=True, purpose="request")
    parsed = urlsplit(url)
    assert parsed.hostname is not None
    return (parsed.scheme.lower(), parsed.hostname.lower(), parsed.port or 443)


def _is_api_origin(url: str) -> bool:
    try:
        return _origin(url) == _origin(API_ORIGIN)
    except MineruError:
        return False


class SafeRedirectHandler(HTTPRedirectHandler):
    """Redirect policy for API and independently signed URL requests."""

    # Run before urllib's default handler, which otherwise follows redirects.
    handler_order = 100

    def __init__(self, policy: str, allowed_origin: str):
        super().__init__()
        self.policy = policy
        self.allowed_origin = allowed_origin

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if self.policy == "signed":
            raise MineruError(
                "security",
                "signed MinerU URLs do not permit redirects",
                fallback_allowed=False,
            )
        if self.policy != "api" or not _is_api_origin(newurl) or not _is_api_origin(self.allowed_origin):
            raise MineruError(
                "security",
                "authenticated MinerU requests may redirect only within the API origin",
                fallback_allowed=False,
            )
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is None:
            raise MineruError(
                "security",
                "MinerU returned an unusable redirect",
                fallback_allowed=False,
            )
        return redirected


def urlopen(request: Request, timeout: float | None = None):
    """Open a request with the redirect policy encoded on the Request."""

    policy = getattr(request, "_mineru_redirect_policy", "signed")
    allowed_origin = getattr(request, "_mineru_allowed_origin", API_ORIGIN)
    opener = build_opener(SafeRedirectHandler(policy, allowed_origin))
    return opener.open(request, timeout=timeout)


def _request_has_header(headers: Mapping[str, str], name: str) -> bool:
    return any(key.lower() == name.lower() for key in headers)


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
    has_authorization = _request_has_header(request_headers, "Authorization")
    if not _is_finite_positive(timeout):
        raise MineruError(
            "configuration",
            "request timeout must be finite and positive",
            fallback_allowed=False,
        )
    upload_stream = None
    if body_file is not None:
        policy = "signed"
        # A signed URL is independently authorized; never send Bearer there.
        for key in tuple(request_headers):
            if key.lower() == "authorization":
                del request_headers[key]
        _validate_url(url, require_https=True, purpose="signed upload")
        try:
            upload_stream = body_file.open("rb")
        except (OSError, TypeError) as exc:
            raise MineruError(
                "local_io",
                "unable to read the local upload file",
                fallback_allowed=False,
            ) from exc
        data = upload_stream
    elif has_authorization:
        policy = "api"
        _validate_url(url, require_https=True, purpose="authenticated request")
        if not _is_api_origin(url):
            raise MineruError(
                "security",
                "authenticated requests must target the MinerU API origin",
                fallback_allowed=False,
            )
        data = json.dumps(json_body).encode("utf-8") if json_body is not None else None
        if json_body is not None:
            request_headers.setdefault("Content-Type", "application/json")
    else:
        policy = "signed"
        _validate_url(url, require_https=True, purpose="signed result")
        data = json.dumps(json_body).encode("utf-8") if json_body is not None else None
        if json_body is not None:
            request_headers.setdefault("Content-Type", "application/json")
    request = Request(url, data=data, headers=request_headers, method=method)
    # Request objects allow these private attributes; the module wrapper reads
    # them to install a policy-specific redirect handler.
    request._mineru_redirect_policy = policy  # type: ignore[attr-defined]
    request._mineru_allowed_origin = API_ORIGIN  # type: ignore[attr-defined]
    try:
        try:
            with urlopen(request, timeout=timeout) as response:
                if 300 <= response.status < 400:
                    raise MineruError(
                        "security",
                        "redirect responses are not permitted for this MinerU request",
                        fallback_allowed=False,
                    )
                return HttpResponse(
                    status=response.status,
                    body=response.read(),
                    headers=dict(response.headers.items()),
                )
        except HTTPError as error:
            try:
                body = error.read()
            except OSError as read_error:
                if error.code in {401, 403}:
                    raise MineruError(
                        "authentication",
                        "MinerU API request was rejected",
                        fallback_allowed=False,
                    ) from read_error
                raise MineruError(
                    "network",
                    "MinerU request failed while reading the response",
                    fallback_allowed=True,
                    retryable=True,
                ) from read_error
            if 300 <= error.code < 400:
                raise MineruError(
                    "security",
                    "redirect responses are not permitted for this MinerU request",
                    fallback_allowed=False,
                )
            return HttpResponse(
                status=error.code,
                body=body,
                headers=dict(error.headers.items()) if error.headers else {},
            )
        except MineruError:
            raise
        except URLError as error:
            raise MineruError(
                "network",
                "MinerU request failed",
                fallback_allowed=True,
                retryable=True,
            ) from error
        except (OSError, TimeoutError) as error:
            raise MineruError(
                "network",
                "MinerU request failed",
                fallback_allowed=True,
                retryable=True,
            ) from error
    finally:
        if upload_stream is not None:
            upload_stream.close()


def _decode_api_response(
    response: HttpResponse, *, token: str | None = None
) -> dict[str, object]:
    reason = _response_reason(response, token)
    decoded_value, parsed = _response_json_payload(response)
    decoded = decoded_value if parsed and isinstance(decoded_value, dict) else None
    if isinstance(response.status, bool) or not isinstance(response.status, int):
        raise MineruError(
            "service",
            "MinerU response status is invalid",
            fallback_allowed=True,
        )
    if not 200 <= response.status < 300:
        # Authentication evidence takes precedence over both HTTP status and
        # schema checks, including on a nominally temporary 5xx response.
        if response.status in {401, 403} or _is_authentication_reason(reason):
            suffix = f": {reason}" if reason else ""
            raise MineruError(
                "authentication",
                f"MinerU API request failed{suffix}",
                fallback_allowed=False,
                retryable=False,
            )
        if parsed:
            if not isinstance(decoded_value, dict):
                raise MineruError(
                    "service",
                    "MinerU API response JSON shape is invalid",
                    fallback_allowed=True,
                    retryable=False,
                )
            if "code" not in decoded_value:
                suffix = f": {reason}" if reason else ""
                raise MineruError(
                    "service",
                    f"MinerU API response code is missing{suffix}",
                    fallback_allowed=True,
                    retryable=False,
                )
            code = decoded_value["code"]
            if not _is_valid_code(code):
                suffix = f": {reason}" if reason else ""
                raise MineruError(
                    "service",
                    f"MinerU API response code is invalid{suffix}",
                    fallback_allowed=True,
                    retryable=False,
                )
            if _is_authentication_code(code):
                suffix = f": {reason}" if reason else ""
                raise MineruError(
                    "authentication",
                    f"MinerU API request failed{suffix}",
                    fallback_allowed=False,
                    retryable=False,
                )
        elif not _response_body_is_empty(response):
            raise MineruError(
                "service",
                "MinerU API returned invalid JSON",
                fallback_allowed=True,
                retryable=False,
            )
        if response.status == 429:
            category = "rate_limit"
            fallback_allowed = True
            retryable = True
        elif response.status == 408:
            category = "service"
            fallback_allowed = True
            retryable = True
        elif 400 <= response.status < 500:
            category = _classify_reason(reason, "document")
            fallback_allowed = True
            retryable = False
        else:
            category = "service"
            fallback_allowed = True
            retryable = 500 <= response.status < 600
        suffix = f": {reason}" if reason else ""
        raise MineruError(
            category,
            f"MinerU API request failed{suffix}",
            fallback_allowed=fallback_allowed,
            retryable=retryable,
        )
    if not parsed:
        raise MineruError(
            "service",
            "MinerU API returned invalid JSON",
            fallback_allowed=True,
            retryable=False,
        )
    if not isinstance(decoded_value, dict):
        raise MineruError(
            "service",
            "MinerU API response JSON shape is invalid",
            fallback_allowed=True,
            retryable=False,
        )
    decoded = decoded_value
    if "code" not in decoded:
        if _is_authentication_reason(reason):
            raise MineruError(
                "authentication",
                f"MinerU API reported an authentication failure: {reason}",
                fallback_allowed=False,
                retryable=False,
            )
        suffix = f": {reason}" if reason else ""
        raise MineruError(
            "service",
            f"MinerU API response code is missing{suffix}",
            fallback_allowed=True,
            retryable=False,
        )
    code = decoded["code"]
    reason = _safe_reason(_reason_from_mapping(decoded), token)
    if _is_authentication_reason(reason):
        raise MineruError(
            "authentication",
            f"MinerU API reported an authentication failure: {reason}",
            fallback_allowed=False,
            retryable=False,
        )
    if not _is_valid_code(code):
        suffix = f": {reason}" if reason else ""
        raise MineruError(
            "service",
            f"MinerU API response code is invalid{suffix}",
            fallback_allowed=True,
            retryable=False,
        )
    code_text = _response_code_text(code)
    if not _is_success_code(code):
        if _is_authentication_code(code):
            category = "authentication"
            fallback_allowed = False
            retryable = False
        elif _classify_reason(reason, "") == "rate_limit":
            category = "rate_limit"
            fallback_allowed = True
            retryable = False
        else:
            category = _classify_reason(reason, "service")
            fallback_allowed = True
            retryable = False
        suffix = f": {reason}" if reason else ""
        raise MineruError(
            category,
            f"MinerU API reported a request failure{suffix}",
            fallback_allowed=fallback_allowed,
            retryable=retryable,
        )
    data = decoded.get("data")
    if not isinstance(data, dict):
        raise MineruError(
            "service",
            "MinerU API response data is invalid",
            fallback_allowed=True,
            retryable=False,
        )
    return data


def _remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()


def _cleanup_path(path: Path) -> None:
    try:
        _remove_path(path)
    except OSError:
        # Cleanup must not hide the classified extraction/publication failure.
        pass


def _replace_directory(staging_dir: Path, output_dir: Path) -> None:
    backup_dir: Path | None = None
    try:
        if output_dir.exists() or output_dir.is_symlink():
            backup_dir = output_dir.with_name(
                f".{output_dir.name}.backup-{uuid.uuid4().hex}"
            )
            output_dir.replace(backup_dir)
        try:
            staging_dir.replace(output_dir)
        except OSError:
            if backup_dir is not None and backup_dir.exists() and not output_dir.exists():
                backup_dir.replace(output_dir)
            raise
        if backup_dir is not None:
            _remove_path(backup_dir)
    except MineruError:
        raise
    except Exception as exc:
        raise MineruError(
            "local_io",
            "unable to publish MinerU extraction output",
            fallback_allowed=False,
        ) from exc


def _archive_member_relative_path(name: str) -> Path:
    if not name or len(name) > MAX_ARCHIVE_MEMBER_NAME_LENGTH or "\x00" in name:
        raise MineruError(
            "result",
            "MinerU result archive contains an invalid member name",
            fallback_allowed=True,
        )
    normalized = name.replace("\\", "/")
    pure = PurePosixPath(normalized)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise MineruError(
            "result",
            "MinerU result archive contains an unsafe path",
            fallback_allowed=True,
        )
    return Path(*pure.parts)


def _archive_resource_error(message: str) -> MineruError:
    return MineruError(
        "result",
        message,
        fallback_allowed=True,
        clean_retry=False,
    )


def _archive_corruption_error(_exc: Exception) -> MineruError:
    return MineruError(
        "result",
        "MinerU result archive is corrupt or incomplete",
        fallback_allowed=True,
        clean_retry=True,
    )


def _extract_archive_member(
    archive: ZipFile,
    member: object,
    destination: Path,
    written_total: int,
) -> int:
    """Extract one untrusted member while separating decode and disk errors."""

    try:
        source_stream = archive.open(member, "r")  # type: ignore[arg-type]
    except Exception as exc:
        raise _archive_corruption_error(exc) from exc

    try:
        with source_stream:
            try:
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination_stream = destination.open("wb")
            except Exception as exc:
                raise MineruError(
                    "local_io",
                    "unable to write MinerU output",
                    fallback_allowed=False,
                ) from exc
            try:
                with destination_stream:
                    while True:
                        try:
                            chunk = source_stream.read(1024 * 1024)
                        except Exception as exc:
                            raise _archive_corruption_error(exc) from exc
                        if not chunk:
                            break
                        written_total += len(chunk)
                        if written_total > MAX_ARCHIVE_TOTAL_BYTES:
                            raise _archive_resource_error(
                                "MinerU result archive is too large when decompressed"
                            )
                        try:
                            destination_stream.write(chunk)
                        except Exception as exc:
                            raise MineruError(
                                "local_io",
                                "unable to write MinerU output",
                                fallback_allowed=False,
                            ) from exc
            except MineruError:
                raise
            except Exception as exc:
                raise MineruError(
                    "local_io",
                    "unable to write MinerU output",
                    fallback_allowed=False,
                ) from exc
    except MineruError:
        raise
    except Exception as exc:
        raise _archive_corruption_error(exc) from exc
    return written_total


class MineruClient:
    def __init__(
        self,
        config: Config,
        request: Callable[..., HttpResponse] = urlopen_request,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        *,
        sleeper: Callable[[float], None] | None = None,
        clock: Callable[[], float] | None = None,
    ):
        self.config = config
        self.request = request
        self.sleep = sleeper if sleeper is not None else sleep
        self.monotonic = clock if clock is not None else monotonic

    def _remaining(self, deadline: float) -> float:
        try:
            remaining = deadline - self.monotonic()
        except (TypeError, ValueError, OverflowError) as exc:
            raise MineruError(
                "network",
                "MinerU operation deadline is invalid",
                fallback_allowed=True,
            ) from exc
        if not math.isfinite(remaining) or remaining <= 0:
            raise MineruError(
                "network",
                "MinerU operation timed out",
                fallback_allowed=True,
            )
        return min(remaining, self.config.timeout_seconds)

    def _sleep_bounded(self, delay: float, deadline: float) -> None:
        remaining = self._remaining(deadline)
        bounded = min(delay, remaining)
        if bounded <= 0:
            return
        try:
            self.sleep(bounded)
        except (OSError, TimeoutError) as exc:
            raise MineruError(
                "network",
                "MinerU retry or polling wait failed",
                fallback_allowed=True,
                retryable=True,
            ) from exc

    def _retry_delay(self, attempt: int) -> float:
        # ``attempt`` is zero-based and identifies the failed try.
        return self.config.retry_backoff_seconds * (2**attempt)

    def _request_once(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        json_body: Mapping[str, object] | None,
        body_file: Path | None,
        deadline: float,
    ) -> HttpResponse:
        timeout = self._remaining(deadline)
        try:
            response = self.request(
                method,
                url,
                headers=headers,
                json_body=json_body,
                body_file=body_file,
                timeout=timeout,
            )
        except MineruError:
            raise
        except (OSError, TimeoutError, URLError) as exc:
            raise MineruError(
                "network",
                "MinerU request failed",
                fallback_allowed=True,
                retryable=True,
            ) from exc
        if not isinstance(response, HttpResponse):
            raise MineruError(
                "service",
                "MinerU request returned an invalid response",
                fallback_allowed=True,
            )
        return response

    def _request_with_retry(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        json_body: Mapping[str, object] | None,
        body_file: Path | None,
        deadline: float,
        decode: Callable[[HttpResponse], _T] | None = None,
    ) -> HttpResponse | _T:
        last_response: HttpResponse | None = None
        attempt_limit = min(self.config.retry_attempts, MAX_RETRY_ATTEMPTS)
        for attempt in range(attempt_limit):
            try:
                response = self._request_once(
                    method,
                    url,
                    headers=headers,
                    json_body=json_body,
                    body_file=body_file,
                    deadline=deadline,
                )
            except MineruError as error:
                if error.retryable and attempt + 1 < attempt_limit:
                    self._sleep_bounded(self._retry_delay(attempt), deadline)
                    continue
                raise
            last_response = response
            if decode is not None:
                try:
                    return decode(response)
                except MineruError as error:
                    if error.retryable and attempt + 1 < attempt_limit:
                        self._sleep_bounded(self._retry_delay(attempt), deadline)
                        continue
                    raise
            if not 200 <= response.status < 300:
                response_reason = _response_reason(response, self.config.token)
                if _is_authentication_reason(response_reason):
                    suffix = f": {response_reason}" if response_reason else ""
                    raise MineruError(
                        "authentication",
                        f"MinerU request was rejected{suffix}",
                        fallback_allowed=False,
                    )
            if response.status in {408, 429} or 500 <= response.status < 600:
                if attempt + 1 < attempt_limit:
                    self._sleep_bounded(self._retry_delay(attempt), deadline)
                    continue
            return response
        assert last_response is not None
        return last_response

    def _api_request(
        self,
        method: str,
        path: str,
        *,
        json_body: Mapping[str, object] | None = None,
        deadline: float | None = None,
    ) -> dict[str, object]:
        if deadline is None:
            deadline = self.monotonic() + self.config.timeout_seconds
        decoded = self._request_with_retry(
            method,
            f"{API_ORIGIN}{path}",
            headers={"Authorization": f"Bearer {self.config.token}"},
            json_body=json_body,
            body_file=None,
            deadline=deadline,
            decode=lambda response: _decode_api_response(
                response, token=self.config.token
            ),
        )
        assert isinstance(decoded, dict)
        return decoded

    def _validate_and_download_result_url(self, result_url: object) -> str:
        return _validate_url(result_url, require_https=True, purpose="result")

    def _download_result(
        self,
        result_url: str,
        output_dir: Path,
        *,
        deadline: float | None = None,
    ) -> Path:
        result_url = self._validate_and_download_result_url(result_url)
        if deadline is None:
            deadline = self.monotonic() + self.config.timeout_seconds
        response = self._request_with_retry(
            "GET",
            result_url,
            headers={},
            json_body=None,
            body_file=None,
            deadline=deadline,
        )
        assert isinstance(response, HttpResponse)
        if not 200 <= response.status < 300:
            reason = _response_reason(response, self.config.token)
            if response.status in {401, 403} or _is_authentication_reason(reason):
                category = "authentication"
                fallback_allowed = False
            elif response.status == 429:
                category = "rate_limit"
                fallback_allowed = True
            elif 500 <= response.status < 600:
                category = "service"
                fallback_allowed = True
            else:
                category = "result"
                fallback_allowed = True
            suffix = f": {reason}" if reason else ""
            raise MineruError(
                category,
                f"MinerU result download failed{suffix}",
                fallback_allowed=fallback_allowed,
            )
        if not isinstance(response.body, bytes):
            raise MineruError(
                "result",
                "MinerU result download returned an invalid body",
                fallback_allowed=True,
                clean_retry=True,
            )
        if len(response.body) > MAX_ARCHIVE_COMPRESSED_BYTES:
            raise _archive_resource_error("MinerU result archive is too large")
        try:
            output_dir = Path(output_dir)
        except (TypeError, ValueError) as exc:
            raise MineruError(
                "local_io",
                "MinerU output directory is invalid",
                fallback_allowed=False,
            ) from exc
        try:
            output_dir.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise MineruError(
                "local_io",
                "unable to create the MinerU output directory",
                fallback_allowed=False,
            ) from exc
        try:
            staging_dir = output_dir.with_name(
                f".{output_dir.name}.staging-{uuid.uuid4().hex}"
            )
        except (TypeError, ValueError, OSError) as exc:
            raise MineruError(
                "local_io",
                "MinerU output directory has an invalid path shape",
                fallback_allowed=False,
            ) from exc
        try:
            try:
                staging_dir.mkdir()
            except Exception as exc:
                raise MineruError(
                    "local_io",
                    "unable to create MinerU staging output",
                    fallback_allowed=False,
                ) from exc
            try:
                with ZipFile(BytesIO(response.body)) as archive:
                    members = archive.infolist()
                    if len(members) > MAX_ARCHIVE_MEMBERS:
                        raise _archive_resource_error(
                            "MinerU result archive contains too many members"
                        )
                    seen: set[str] = set()
                    total_declared = 0
                    markdown_found = False
                    try:
                        staging_root = staging_dir.resolve()
                    except Exception as exc:
                        raise MineruError(
                            "local_io",
                            "unable to resolve MinerU staging output",
                            fallback_allowed=False,
                        ) from exc
                    for member in members:
                        relative = _archive_member_relative_path(member.filename)
                        key = relative.as_posix()
                        if key in seen:
                            raise _archive_resource_error(
                                "MinerU result archive contains duplicate members"
                            )
                        seen.add(key)
                        try:
                            destination = (staging_dir / relative).resolve()
                        except Exception as exc:
                            raise MineruError(
                                "local_io",
                                "unable to resolve MinerU output path",
                                fallback_allowed=False,
                            ) from exc
                        if not destination.is_relative_to(staging_root):
                            raise MineruError(
                                "result",
                                "MinerU result archive contains an unsafe path",
                                fallback_allowed=True,
                            )
                        file_mode = (member.external_attr >> 16) & 0o170000
                        if file_mode == 0o120000:
                            raise MineruError(
                                "result",
                                "MinerU result archive contains an unsafe link",
                                fallback_allowed=True,
                            )
                        if member.file_size < 0 or member.compress_size < 0:
                            raise _archive_resource_error(
                                "MinerU result archive contains invalid sizes"
                            )
                        if member.file_size > MAX_ARCHIVE_MEMBER_BYTES:
                            raise _archive_resource_error(
                                "MinerU result archive contains an oversized member"
                            )
                        total_declared += member.file_size
                        if total_declared > MAX_ARCHIVE_TOTAL_BYTES:
                            raise _archive_resource_error(
                                "MinerU result archive is too large when decompressed"
                            )
                        if member.file_size and (
                            member.compress_size == 0
                            or member.file_size / member.compress_size
                            > MAX_ARCHIVE_COMPRESSION_RATIO
                        ):
                            raise _archive_resource_error(
                                "MinerU result archive has an excessive compression ratio"
                            )
                        if not member.is_dir() and relative.suffix.lower() == ".md":
                            markdown_found = True
                    if not markdown_found:
                        raise MineruError(
                            "result",
                            "MinerU result archive contains no Markdown file",
                            fallback_allowed=True,
                            clean_retry=True,
                        )
                    written_total = 0
                    for member in members:
                        relative = _archive_member_relative_path(member.filename)
                        destination = staging_dir / relative
                        if member.is_dir():
                            try:
                                destination.mkdir(parents=True, exist_ok=True)
                            except Exception as exc:
                                raise MineruError(
                                    "local_io",
                                    "unable to create a directory in MinerU output",
                                    fallback_allowed=False,
                                ) from exc
                            continue
                        written_total = _extract_archive_member(
                            archive, member, destination, written_total
                        )
            except MineruError:
                raise
            except Exception as exc:
                raise _archive_corruption_error(exc) from exc
            try:
                _replace_directory(staging_dir, output_dir)
            except MineruError:
                raise
            except Exception as exc:
                raise MineruError(
                    "local_io",
                    "unable to publish MinerU extraction output",
                    fallback_allowed=False,
                ) from exc
        finally:
            _cleanup_path(staging_dir)
        return output_dir

    def _submission_options(
        self, *, ocr: bool, language: str, include_ocr: bool = True
    ) -> dict[str, object]:
        options: dict[str, object] = {
            "model_version": "vlm",
            "enable_formula": True,
            "enable_table": True,
            "language": language,
        }
        if include_ocr:
            options["is_ocr"] = ocr
        return options

    def _task_failure(self, data: Mapping[str, object], *, default: str = "task") -> MineruError:
        reason = _safe_reason(_reason_from_mapping(data), self.config.token)
        if _is_authentication_code(data.get("code")):
            category = "authentication"
        else:
            category = _classify_reason(reason, default)
        suffix = f": {reason}" if reason else ""
        return MineruError(
            category,
            f"MinerU task failed{suffix}",
            fallback_allowed=category != "authentication",
        )

    def _poll_sleep(self, deadline: float) -> None:
        self._sleep_bounded(self.config.poll_interval_seconds, deadline)

    def _extract_local(
        self,
        source: Path,
        output_dir: Path,
        *,
        ocr: bool,
        language: str,
        deadline: float,
    ) -> Path:
        payload = self._submission_options(ocr=ocr, language=language, include_ocr=False)
        payload["files"] = [
            {"name": source.name, "data_id": uuid.uuid4().hex, "is_ocr": ocr}
        ]
        data = self._api_request(
            "POST", "/api/v4/file-urls/batch", json_body=payload, deadline=deadline
        )
        batch_id = data.get("batch_id")
        file_urls = data.get("file_urls")
        if not isinstance(batch_id, str) or not batch_id or not isinstance(file_urls, list):
            raise MineruError(
                "service",
                "MinerU upload response is invalid",
                fallback_allowed=True,
            )
        upload_url: str | None = None
        for item in file_urls:
            if isinstance(item, str) and item:
                upload_url = item
                break
            if isinstance(item, Mapping) and item.get("name") == source.name:
                candidate = item.get("url")
                if isinstance(candidate, str) and candidate:
                    upload_url = candidate
                    break
        if upload_url is None:
            raise MineruError(
                "service",
                "MinerU upload URL is missing",
                fallback_allowed=True,
            )
        upload_url = _validate_url(upload_url, require_https=True, purpose="signed upload")
        upload_response = self._request_with_retry(
            "PUT",
            upload_url,
            headers={},
            json_body=None,
            body_file=source,
            deadline=deadline,
        )
        assert isinstance(upload_response, HttpResponse)
        if not 200 <= upload_response.status < 300:
            reason = _response_reason(upload_response, self.config.token)
            if upload_response.status in {401, 403} or _is_authentication_reason(reason):
                category = "authentication"
                fallback_allowed = False
            elif upload_response.status == 429:
                category = "rate_limit"
                fallback_allowed = True
            else:
                category = "service"
                fallback_allowed = True
            suffix = f": {reason}" if reason else ""
            raise MineruError(
                category,
                f"MinerU upload failed{suffix}",
                fallback_allowed=fallback_allowed,
            )
        while True:
            data = self._api_request(
                "GET",
                f"/api/v4/extract-results/batch/{batch_id}",
                deadline=deadline,
            )
            results = data.get("extract_result")
            matching_result = (
                next(
                    (
                        item
                        for item in results
                        if isinstance(item, dict) and item.get("file_name") == source.name
                    ),
                    None,
                )
                if isinstance(results, list)
                else None
            )
            if not isinstance(matching_result, dict):
                raise MineruError(
                    "task",
                    "MinerU batch result is invalid",
                    fallback_allowed=True,
                )
            state = matching_result.get("state")
            if state == "done":
                result_url = matching_result.get("full_zip_url")
                if not isinstance(result_url, str) or not result_url:
                    raise MineruError(
                        "result",
                        "MinerU task completed without a result archive",
                        fallback_allowed=True,
                        clean_retry=True,
                    )
                return self._download_result(result_url, output_dir, deadline=deadline)
            if state == "failed":
                raise self._task_failure(matching_result)
            if state not in {"waiting-file", "pending", "running", "converting"}:
                raise self._task_failure(matching_result)
            self._poll_sleep(deadline)

    def _extract_remote(
        self,
        source: str,
        output_dir: Path,
        *,
        ocr: bool,
        language: str,
        deadline: float,
    ) -> Path:
        payload = self._submission_options(ocr=ocr, language=language)
        payload["url"] = source
        data = self._api_request(
            "POST", "/api/v4/extract/task", json_body=payload, deadline=deadline
        )
        task_id = data.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            raise MineruError(
                "task",
                "MinerU task ID is invalid",
                fallback_allowed=True,
            )
        while True:
            result = self._api_request(
                "GET", f"/api/v4/extract/task/{task_id}", deadline=deadline
            )
            state = result.get("state")
            if state == "done":
                result_url = result.get("full_zip_url")
                if not isinstance(result_url, str) or not result_url:
                    raise MineruError(
                        "result",
                        "MinerU task completed without a result archive",
                        fallback_allowed=True,
                        clean_retry=True,
                    )
                return self._download_result(result_url, output_dir, deadline=deadline)
            if state == "failed":
                raise self._task_failure(result)
            if state not in {"pending", "running", "converting"}:
                raise self._task_failure(result)
            self._poll_sleep(deadline)

    def _extract_once(
        self,
        source: str,
        output_dir: Path,
        *,
        ocr: bool,
        language: str,
        deadline: float,
    ) -> Path:
        try:
            source_path = Path(source)
            output_path = Path(output_dir)
        except (TypeError, ValueError) as exc:
            raise MineruError(
                "local_io",
                "MinerU source or output path is invalid",
                fallback_allowed=False,
            ) from exc
        try:
            is_file = source_path.is_file()
        except OSError as exc:
            raise MineruError(
                "local_io",
                "unable to inspect the local PDF source",
                fallback_allowed=False,
            ) from exc
        if is_file:
            return self._extract_local(
                source_path,
                output_path,
                ocr=ocr,
                language=language,
                deadline=deadline,
            )
        if not isinstance(source, str):
            raise MineruError(
                "security",
                "MinerU source URL is invalid",
                fallback_allowed=False,
            )
        try:
            parsed = urlsplit(source)
        except ValueError as exc:
            raise MineruError(
                "security",
                "MinerU source URL is invalid",
                fallback_allowed=False,
            ) from exc
        if not parsed.scheme:
            raise MineruError(
                "local_io",
                "local PDF source does not exist",
                fallback_allowed=False,
            )
        _validate_url(source, require_https=False, purpose="source")
        return self._extract_remote(
            source,
            output_path,
            ocr=ocr,
            language=language,
            deadline=deadline,
        )

    def extract(
        self,
        source: str,
        output_dir: Path,
        *,
        ocr: bool = False,
        language: str = "en",
    ) -> Path:
        """Extract once, with one clean precise retry for corrupt results."""

        try:
            started = self.monotonic()
            if not math.isfinite(started):
                raise ValueError
            deadline = started + self.config.timeout_seconds
        except (TypeError, ValueError, OverflowError) as exc:
            raise MineruError(
                "network",
                "MinerU operation deadline is invalid",
                fallback_allowed=True,
            ) from exc
        retried_cleanly = False
        while True:
            try:
                return self._extract_once(
                    source,
                    output_dir,
                    ocr=ocr,
                    language=language,
                    deadline=deadline,
                )
            except MineruError as error:
                if error.clean_retry and not retried_cleanly and error.fallback_allowed:
                    # The next request uses the same shared deadline; the retry
                    # cannot extend the overall timeout.
                    self._remaining(deadline)
                    retried_cleanly = True
                    continue
                raise


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
    return _safe_reason(str(error), config.token if config is not None else None)


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
