"""Tests for the i2v.ai Python client."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from i2v import (  # noqa: E402
    I2VClient,
    I2VHttpError,
    I2VSubmissionUnknownError,
    I2VWaitTimeoutError,
)


class _Server:
    def __init__(self) -> None:
        self.routes = {}
        self.requests = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()

    @property
    def base_url(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}"

    def _handler(self):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # silence test output
                pass

            def _handle(self):
                parsed = urllib.parse.urlsplit(self.path)
                length = int(self.headers.get("content-length") or 0)
                body = self.rfile.read(length) if length else b""
                outer.requests.append(
                    {
                        "method": self.command,
                        "path": parsed.path,
                        "query": urllib.parse.parse_qs(parsed.query),
                        "headers": {k.lower(): v for k, v in self.headers.items()},
                        "body": body,
                    }
                )
                route = outer.routes.get((self.command, parsed.path))
                if route is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                status, payload = route
                raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            do_GET = _handle
            do_POST = _handle
            do_PUT = _handle

        return Handler


class ClientTests(unittest.TestCase):
    def test_list_models_is_public(self):
        with _Server() as server:
            server.routes[("GET", "/api/v1/generation-models")] = (
                200,
                {"data": [{"id": "gpt-image-2", "mediaType": "image"}]},
            )
            client = I2VClient(base_url=server.base_url)
            result = client.list_models()
        self.assertEqual(result.data["data"][0]["id"], "gpt-image-2")
        self.assertNotIn("authorization", server.requests[0]["headers"])

    def test_quote_sends_key_and_inputs(self):
        with _Server() as server:
            server.routes[("POST", "/api/v1/jobs/quote")] = (
                200,
                {"maximum": {"currency": "USD", "amount": "0.07000000"}, "expectedRevision": 1},
            )
            client = I2VClient(api_key="key-123", base_url=server.base_url)
            quote = client.quote("gpt-image-2", {"prompt": "a mug"})
        self.assertEqual(quote.data["expectedRevision"], 1)
        sent = server.requests[0]
        self.assertEqual(sent["headers"]["authorization"], "Bearer key-123")
        self.assertEqual(json.loads(sent["body"]), {"model": "gpt-image-2", "inputs": {"prompt": "a mug"}})

    def test_create_task_pending_conflict_is_unknown(self):
        with _Server() as server:
            server.routes[("POST", "/api/v1/jobs/createTask")] = (
                409,
                {"reason": "submission_pending", "error": {"code": "submission_pending"}},
            )
            client = I2VClient(api_key="key-123", base_url=server.base_url)
            with self.assertRaises(I2VSubmissionUnknownError) as ctx:
                client.create_task(
                    "gpt-image-2",
                    {"prompt": "a mug"},
                    max_cost_usd="0.2",
                    expected_revision=1,
                    idempotency_key="op-1",
                )
        self.assertEqual(ctx.exception.idempotency_key, "op-1")
        self.assertEqual(ctx.exception.cause.status, 409)
        self.assertEqual(ctx.exception.cause.reason, "submission_pending")

    def test_create_task_server_error_is_unknown(self):
        with _Server() as server:
            server.routes[("POST", "/api/v1/jobs/createTask")] = (503, {"error": "unavailable"})
            client = I2VClient(api_key="key-123", base_url=server.base_url)
            with self.assertRaises(I2VSubmissionUnknownError) as ctx:
                client.create_task(
                    "gpt-image-2",
                    {"prompt": "a mug"},
                    max_cost_usd="0.2",
                    expected_revision=1,
                    idempotency_key="op-2",
                )
        self.assertEqual(ctx.exception.idempotency_key, "op-2")

    def test_create_task_client_error_raises(self):
        with _Server() as server:
            server.routes[("POST", "/api/v1/jobs/createTask")] = (400, {"error": "invalid_params"})
            client = I2VClient(api_key="key-123", base_url=server.base_url)
            with self.assertRaises(I2VHttpError):
                client.create_task(
                    "gpt-image-2",
                    {"prompt": "a mug"},
                    max_cost_usd="0.2",
                    expected_revision=1,
                    idempotency_key="op-3",
                )

    def test_create_task_validates_inputs(self):
        client = I2VClient(api_key="key-123")
        with self.assertRaises(TypeError):
            client.create_task("m", {}, max_cost_usd="1", expected_revision=0, idempotency_key="bad key")
        with self.assertRaises(TypeError):
            client.create_task("m", {}, max_cost_usd="1.123456789", expected_revision=0, idempotency_key="ok")
        with self.assertRaises(TypeError):
            client.create_task("m", {}, max_cost_usd="1", expected_revision=-1, idempotency_key="ok")

    def test_get_task_builds_query(self):
        with _Server() as server:
            server.routes[("GET", "/api/v1/jobs/recordInfo")] = (200, {"status": "success"})
            client = I2VClient(api_key="key-123", base_url=server.base_url)
            result = client.get_task("task-9")
        self.assertEqual(result.data["status"], "success")
        self.assertEqual(server.requests[0]["query"]["taskId"], ["task-9"])

    def test_wait_for_task_returns_terminal_state(self):
        with _Server() as server:
            server.routes[("GET", "/api/v1/jobs/recordInfo")] = (200, {"status": "success"})
            client = I2VClient(api_key="key-123", base_url=server.base_url)
            result = client.wait_for_task("task-1", timeout=5)
        self.assertEqual(result.data["status"], "success")

    def test_wait_for_task_times_out(self):
        with _Server() as server:
            server.routes[("GET", "/api/v1/jobs/recordInfo")] = (200, {"status": "processing"})
            client = I2VClient(api_key="key-123", base_url=server.base_url)
            with self.assertRaises(I2VWaitTimeoutError):
                client.wait_for_task("task-2", timeout=0.4, poll_interval=0.1)

    def test_upload_asset_flow(self):
        with _Server() as storage, _Server() as api:
            api.routes[("POST", "/api/v1/assets")] = (
                200,
                {
                    "assetId": "asset-1",
                    "uploadUrl": storage.base_url + "/put/asset-1",
                    "contentType": "image/png",
                },
            )
            api.routes[("POST", "/api/v1/assets/asset-1/complete")] = (
                200,
                {"assetId": "asset-1", "url": "https://cdn.example/asset-1.png"},
            )
            storage.routes[("PUT", "/put/asset-1")] = (200, b"")
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
                handle.write(b"png-bytes")
                path = handle.name
            try:
                client = I2VClient(api_key="key-123", base_url=api.base_url)
                completed = client.upload_asset(path, content_type="image/png")
            finally:
                os.unlink(path)
        self.assertEqual(completed.data["url"], "https://cdn.example/asset-1.png")
        put = storage.requests[0]
        self.assertEqual(put["body"], b"png-bytes")
        self.assertEqual(put["headers"]["content-type"], "image/png")

    def test_rejects_insecure_base_url(self):
        with self.assertRaises(TypeError):
            I2VClient(base_url="http://api.i2v.ai")
        with self.assertRaises(TypeError):
            I2VClient(base_url="https://api.i2v.ai/v1")

    def test_requires_key_for_private_routes(self):
        client = I2VClient()
        with self.assertRaises(TypeError):
            client.get_account()


if __name__ == "__main__":
    unittest.main()
