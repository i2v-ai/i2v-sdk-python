"""Verify signed i2v.ai webhook deliveries."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from typing import Any, Callable, Mapping, Optional, Union

_SIGNATURE = re.compile(r"^v1=([a-f0-9]{64})$")
_TIMESTAMP = re.compile(r"^[0-9]{1,13}$")


def _header(headers: Union[Mapping[str, str], Any], name: str) -> Optional[str]:
    if headers is None:
        return None
    getter = getattr(headers, "get", None)
    if callable(getter):
        value = getter(name)
        if value is not None:
            return str(value)
        lowered = name.lower()
        try:
            for key, candidate in dict(headers).items():  # type: ignore[arg-type]
                if str(key).lower() == lowered:
                    return str(candidate)
        except (TypeError, ValueError):
            return None
    return None


def _clock(now: Optional[float]) -> int:
    if now is None:
        return int(time.time())
    return int(now / 1000) if now > 10_000_000_000 else int(now)


def verify_webhook(
    raw_body: Union[str, bytes],
    headers: Union[Mapping[str, str], Any],
    get_secret: Callable[[str], Optional[Union[str, bytes]]],
    *,
    now: Optional[float] = None,
    max_age_seconds: int = 300,
) -> Optional[dict]:
    """Return the verified event, or None when the delivery is not trusted.

    Pass the exact bytes received. The signature covers the timestamp, a
    literal dot, and those bytes.
    """
    event_id = _header(headers, "X-I2V-Event-ID")
    key_id = _header(headers, "X-I2V-Key-ID")
    timestamp_header = _header(headers, "X-I2V-Timestamp")
    signature = _header(headers, "X-I2V-Signature")
    if not event_id or not key_id or not timestamp_header or not signature:
        return None
    if not _TIMESTAMP.match(timestamp_header):
        return None
    match = _SIGNATURE.match(signature)
    if not match:
        return None

    timestamp = int(timestamp_header)
    if abs(_clock(now) - timestamp) > max_age_seconds:
        return None

    secret = get_secret(key_id)
    if not secret:
        return None
    secret_bytes = secret.encode("utf-8") if isinstance(secret, str) else secret
    body_bytes = raw_body.encode("utf-8") if isinstance(raw_body, str) else raw_body
    expected = hmac.new(secret_bytes, digestmod=hashlib.sha256)
    expected.update(timestamp_header.encode("utf-8"))
    expected.update(b".")
    expected.update(body_bytes)
    if not hmac.compare_digest(expected.hexdigest(), match.group(1)):
        return None

    try:
        body = json.loads(body_bytes)
    except ValueError:
        return None
    if not isinstance(body, dict) or body.get("eventId") != event_id:
        return None
    return {
        "eventId": event_id,
        "keyId": key_id,
        "timestamp": timestamp,
        "body": body,
    }
