"""Errors raised by the i2v.ai client."""

from __future__ import annotations

from typing import Any, Optional


class I2VError(Exception):
    """Base class for every i2v.ai client error."""


class I2VNetworkError(I2VError):
    """The request did not produce an HTTP response."""


class I2VHttpError(I2VError):
    """The API answered with a non-2xx status."""

    def __init__(
        self,
        status: int,
        code: Optional[str] = None,
        request_id: Optional[str] = None,
        retry_after_ms: Optional[int] = None,
        reason: Optional[str] = None,
        body: Any = None,
    ) -> None:
        suffix = f": {code}" if code else ""
        super().__init__(f"i2v.ai request failed (HTTP {status}){suffix}")
        self.status = status
        self.code = code
        self.request_id = request_id
        self.retry_after_ms = retry_after_ms
        self.reason = reason
        self.body = body


class I2VSubmissionUnknownError(I2VError):
    """The submission may have been accepted, but its result is unknown."""

    def __init__(self, idempotency_key: str, cause: Optional[BaseException] = None) -> None:
        super().__init__(
            "Submission could not be confirmed. Look up the original receipt with "
            "the same idempotency key and credential."
        )
        self.idempotency_key = idempotency_key
        self.cause = cause


class I2VWaitTimeoutError(I2VError):
    """The wait ended before the task reached a terminal state."""

    def __init__(self, task_id: str) -> None:
        super().__init__("The wait ended before the task reached a terminal state.")
        self.task_id = task_id
