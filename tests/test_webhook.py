"""Tests for webhook verification."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from i2v import verify_webhook  # noqa: E402

SECRET = b"whsec_test"
KEY_ID = "key_1"
EVENT = {"eventId": "evt_1", "type": "task.completed", "data": {"taskId": "task-1"}}


def _sign(raw: bytes, timestamp: int, secret: bytes = SECRET) -> str:
    digest = hmac.new(secret, digestmod=hashlib.sha256)
    digest.update(str(timestamp).encode())
    digest.update(b".")
    digest.update(raw)
    return "v1=" + digest.hexdigest()


def _headers(raw: bytes, timestamp: int, signature: str | None = None) -> dict:
    return {
        "X-I2V-Event-ID": EVENT["eventId"],
        "X-I2V-Key-ID": KEY_ID,
        "X-I2V-Timestamp": str(timestamp),
        "X-I2V-Signature": signature if signature is not None else _sign(raw, timestamp),
    }


class WebhookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.raw = json.dumps(EVENT).encode()
        self.now = 1_800_000_000_000

    def test_valid_delivery(self):
        verified = verify_webhook(
            self.raw, _headers(self.raw, self.now // 1000), lambda key: SECRET, now=self.now
        )
        self.assertIsNotNone(verified)
        self.assertEqual(verified["eventId"], "evt_1")
        self.assertEqual(verified["body"]["type"], "task.completed")

    def test_tampered_body_is_rejected(self):
        headers = _headers(self.raw, self.now // 1000)
        tampered = self.raw.replace(b"task-1", b"task-2")
        self.assertIsNone(verify_webhook(tampered, headers, lambda key: SECRET, now=self.now))

    def test_stale_timestamp_is_rejected(self):
        old = self.now // 1000 - 3_600
        headers = _headers(self.raw, old)
        self.assertIsNone(verify_webhook(self.raw, headers, lambda key: SECRET, now=self.now))

    def test_unknown_key_is_rejected(self):
        headers = _headers(self.raw, self.now // 1000)
        self.assertIsNone(verify_webhook(self.raw, headers, lambda key: None, now=self.now))

    def test_event_id_mismatch_is_rejected(self):
        body = dict(EVENT)
        body["eventId"] = "evt_other"
        raw = json.dumps(body).encode()
        headers = _headers(raw, self.now // 1000)
        self.assertIsNone(verify_webhook(raw, headers, lambda key: SECRET, now=self.now))

    def test_malformed_headers_are_rejected(self):
        self.assertIsNone(verify_webhook(self.raw, {}, lambda key: SECRET, now=self.now))


if __name__ == "__main__":
    unittest.main()
