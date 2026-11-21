"""Server-side client for the i2v.ai image and video API.

The client mirrors the TypeScript SDK: quote before submitting, keep the
idempotency key stable, and distinguish a pending submission from a
definitive conflict.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple, Union

from .errors import (
    I2VError,
    I2VHttpError,
    I2VNetworkError,
    I2VSubmissionUnknownError,
    I2VWaitTimeoutError,
)

DEFAULT_BASE_URL = "https://api.i2v.ai"
DEFAULT_TIMEOUT_SECONDS = 20.0
DEFAULT_WAIT_SECONDS = 900.0
USER_AGENT = "i2v-ai-python/0.1.0"

_IDEMPOTENCY_KEY = re.compile(r"^[\x21-\x7e]{1,200}$")
_USD_AMOUNT = re.compile(r"^(0|[1-9][0-9]*)(\.[0-9]{1,8})?$")
_ERROR_IDENTIFIER = re.compile(r"^[a-zA-Z0-9_-]{1,100}$")
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


@dataclass
class Result:
    """A successful API response with transport metadata."""

    data: Any
    request_id: Optional[str] = None
    retry_after_ms: Optional[int] = None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Reject redirects so credentials never follow an unexpected location."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        raise urllib.error.HTTPError(newurl, code, msg, headers, fp)


def _parse_retry_after(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        seconds = int(value)
        return seconds * 1000 if seconds <= 2_147_483 else None
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(0, int((when - datetime.now(timezone.utc)).total_seconds() * 1000))


def _error_identifiers(body: Any) -> Tuple[Optional[str], Optional[str]]:
    if not isinstance(body, dict):
        return None, None
    detail = body.get("error")
    nested = detail.get("code") if isinstance(detail, dict) else None
    candidates = [nested, body.get("code"), body.get("reason")]
    identifiers = [c for c in candidates if isinstance(c, str) and _ERROR_IDENTIFIER.match(c)]
    code = identifiers[0] if identifiers else None
    reason = body.get("reason") if isinstance(body.get("reason"), str) else None
    return code, reason


def _require_idempotency_key(key: str) -> str:
    if not isinstance(key, str) or not _IDEMPOTENCY_KEY.match(key):
        raise TypeError(
            "Use a stable idempotency key of up to 200 visible ASCII characters."
        )
    return key


class I2VClient:
    """Minimal, dependency-free client for https://api.i2v.ai."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        parsed = urllib.parse.urlsplit(base_url)
        is_loopback = parsed.hostname in _LOOPBACK_HOSTS
        if parsed.scheme != "https" and not (is_loopback and parsed.scheme == "http"):
            raise TypeError("base_url must be an HTTPS origin or a local HTTP test origin.")
        if parsed.path not in ("", "/") or parsed.query or parsed.fragment or parsed.username:
            raise TypeError("base_url must be an origin without a path, query or credentials.")
        if not isinstance(timeout, (int, float)) or timeout <= 0:
            raise ValueError("timeout must be a positive number of seconds.")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = float(timeout)
        self._opener = urllib.request.build_opener(_NoRedirect())

    # -- transport ---------------------------------------------------------

    def _request(
        self,
        path: str,
        *,
        method: str = "GET",
        body: Optional[Mapping[str, Any]] = None,
        headers: Optional[Mapping[str, str]] = None,
        public: bool = False,
    ) -> Result:
        url = self.base_url + path
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(url, data=data, method=method)
        request.add_header("Accept", "application/json")
        request.add_header("User-Agent", USER_AGENT)
        if not public:
            if not self.api_key:
                raise TypeError("An i2v.ai API key is required.")
            request.add_header("Authorization", f"Bearer {self.api_key}")
        if data is not None:
            request.add_header("Content-Type", "application/json")
        for name, value in (headers or {}).items():
            request.add_header(name, value)

        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                raw = response.read()
                return Result(
                    data=json.loads(raw) if raw else None,
                    request_id=response.headers.get("X-Request-ID"),
                    retry_after_ms=_parse_retry_after(response.headers.get("Retry-After")),
                )
        except urllib.error.HTTPError as error:
            raw = error.read()
            parsed: Any = None
            try:
                parsed = json.loads(raw) if raw else None
            except ValueError:
                parsed = None
            code, reason = _error_identifiers(parsed)
            raise I2VHttpError(
                status=error.code,
                code=code,
                request_id=error.headers.get("X-Request-ID") if error.headers else None,
                retry_after_ms=_parse_retry_after(
                    error.headers.get("Retry-After") if error.headers else None
                ),
                reason=reason,
                body=parsed,
            ) from None
        except urllib.error.URLError as error:
            raise I2VNetworkError(f"The request to i2v.ai failed: {error.reason}") from error

    # -- catalog -----------------------------------------------------------

    def list_models(self) -> Result:
        """Read the public image and video model catalog."""
        return self._request("/api/v1/generation-models", public=True)

    def get_model(self, model: str) -> Optional[Dict[str, Any]]:
        for item in self.list_models().data.get("data", []):
            if item.get("id") == model:
                return item
        return None

    # -- generation --------------------------------------------------------

    def quote(self, model: str, inputs: Mapping[str, Any]) -> Result:
        """Quote exact inputs and return the maximum USD reservation."""
        return self._request(
            "/api/v1/jobs/quote", method="POST", body={"model": model, "inputs": dict(inputs)}
        )

    def create_task(
        self,
        model: str,
        inputs: Mapping[str, Any],
        *,
        max_cost_usd: str,
        expected_revision: int,
        idempotency_key: str,
        callback_url: Optional[str] = None,
    ) -> Result:
        """Submit a paid task inside an explicit USD ceiling."""
        _require_idempotency_key(idempotency_key)
        if not isinstance(max_cost_usd, str) or not _USD_AMOUNT.match(max_cost_usd):
            raise TypeError("Use a USD decimal string with at most eight decimal places.")
        if not isinstance(expected_revision, int) or expected_revision < 0:
            raise TypeError("Use the expectedRevision returned by the quote.")
        payload: Dict[str, Any] = {
            "model": model,
            "inputs": dict(inputs),
            "maxCostUsd": max_cost_usd,
            "expectedRevision": expected_revision,
        }
        if callback_url:
            payload["callBackUrl"] = callback_url
        try:
            result = self._request(
                "/api/v1/jobs/createTask",
                method="POST",
                body=payload,
                headers={"Idempotency-Key": idempotency_key},
            )
        except I2VHttpError as error:
            definitive = error.status < 500 and not (
                error.status == 409 and error.reason == "submission_pending"
            )
            if definitive:
                raise
            raise I2VSubmissionUnknownError(idempotency_key, error) from error
        except I2VNetworkError as error:
            raise I2VSubmissionUnknownError(idempotency_key, error) from error
        task_id = (result.data or {}).get("taskId")
        if not isinstance(task_id, str) or not task_id:
            raise I2VError("The API returned an invalid task ID.")
        return result

    def recover_submission(self, idempotency_key: str) -> Result:
        """Look up the receipt of an original submission by its key."""
        _require_idempotency_key(idempotency_key)
        return self._request(
            "/api/v1/jobs/submission",
            method="POST",
            body={},
            headers={"Idempotency-Key": idempotency_key},
        )

    def get_task(self, task_id: str) -> Result:
        query = urllib.parse.urlencode({"taskId": task_id})
        return self._request(f"/api/v1/jobs/recordInfo?{query}")

    def cancel_task(self, task_id: str) -> Result:
        return self._request(
            "/api/v1/jobs/cancel", method="POST", body={"taskId": task_id}
        )

    # -- account -----------------------------------------------------------

    def get_account(self) -> Result:
        return self._request("/api/v1/account")

    def get_usage(self, range: str = "30d") -> Result:
        query = urllib.parse.urlencode({"range": range})
        return self._request(f"/api/v1/account/usage?{query}")

    # -- uploads -----------------------------------------------------------

    def upload_asset(
        self, path: str, content_type: str = "application/octet-stream"
    ) -> Result:
        """Request a signed ticket, upload the file, and confirm it."""
        import os

        file_name = os.path.basename(path)
        file_size = os.path.getsize(path)
        ticket = self._request(
            "/api/v1/assets",
            method="POST",
            body={"fileName": file_name, "fileSize": file_size, "contentType": content_type},
        ).data
        upload_url = ticket.get("uploadUrl") if isinstance(ticket, dict) else None
        if not isinstance(upload_url, str):
            raise I2VError("The upload ticket is missing a storage URL.")
        parsed = urllib.parse.urlsplit(upload_url)
        loopback_storage = parsed.hostname in _LOOPBACK_HOSTS and parsed.scheme == "http"
        if (parsed.scheme != "https" and not loopback_storage) or parsed.username or parsed.password:
            raise TypeError("The upload ticket must contain an HTTPS storage URL.")
        with open(path, "rb") as handle:
            payload = handle.read()
        put = urllib.request.Request(upload_url, data=payload, method="PUT")
        put.add_header("Content-Type", ticket.get("contentType") or content_type)
        try:
            with self._opener.open(put, timeout=self.timeout):
                pass
        except urllib.error.HTTPError as error:
            raise I2VHttpError(status=error.code, code="asset_upload_failed") from None
        asset_id = urllib.parse.quote(str(ticket.get("assetId")), safe="")
        return self._request(
            f"/api/v1/assets/{asset_id}/complete", method="POST", body={}
        )

    # -- polling -----------------------------------------------------------

    def wait_for_task(
        self,
        task_id: str,
        *,
        timeout: float = DEFAULT_WAIT_SECONDS,
        poll_interval: float = 2.0,
    ) -> Result:
        """Poll until the task succeeds or fails, honoring Retry-After."""
        if timeout <= 0:
            raise ValueError("timeout must be positive.")
        deadline = time.monotonic() + timeout
        delay = poll_interval
        while True:
            suggested = 0.0
            try:
                result = self.get_task(task_id)
                task = result.data or {}
                if task.get("status") in ("success", "fail"):
                    return result
                lifecycle = task.get("lifecycle") or {}
                suggested = float(lifecycle.get("pollAfterSeconds") or 0)
            except I2VHttpError as error:
                if error.status != 429 and error.status < 500:
                    raise
                suggested = (error.retry_after_ms or 0) / 1000
            if time.monotonic() + delay >= deadline:
                raise I2VWaitTimeoutError(task_id)
            time.sleep(max(delay, suggested))
            delay = min(30.0, delay * 1.5)
