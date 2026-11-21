# i2v-ai Python SDK

Server-side Python client for the [i2v.ai](https://i2v.ai) image and video API. It mirrors the TypeScript SDK: quote before submitting, keep a stable idempotency key, and tell a pending submission apart from a definitive conflict.

- Python 3.10 or newer, no runtime dependencies.
- Covers model discovery, account balance and usage, quotes, uploads, task creation, polling, recovery, cancellation, and signed webhook verification.

## Install

```bash
pip install ./packages/python-sdk
```

The package is not on PyPI yet; install it from this repository until it is.

## Quickstart

```python
import os
from i2v import I2VClient

client = I2VClient(api_key=os.environ["I2V_API_KEY"])

models = client.list_models().data["data"]
print([m["id"] for m in models if m["mediaType"] == "image"][:5])

quote = client.quote("gpt-image-2", {"prompt": "A ceramic mug on an oak table"}).data
print(quote["maximum"])          # maximum USD reservation for these inputs
print(quote["expectedRevision"]) # agree to this revision when submitting
```

`list_models` is public: it works without a key.

## Submit inside a budget

```python
receipt = client.create_task(
    "gpt-image-2",
    {"prompt": "A ceramic mug on an oak table"},
    max_cost_usd="0.20",
    expected_revision=quote["expectedRevision"],
    idempotency_key="order-1234-image",
).data
print(receipt["taskId"])

result = client.wait_for_task(receipt["taskId"], timeout=900).data
print(result["status"], result.get("result"))
```

`max_cost_usd` is a decimal string. If the quote exceeds it, the API rejects the request before a task exists.

## Recovery

A submission whose response was lost may still have been accepted. Look up the original receipt with the same key instead of sending a new request:

```python
try:
    task = client.create_task(..., idempotency_key="order-1234-image")
except I2VSubmissionUnknownError as error:
    receipt = client.recover_submission(error.idempotency_key).data
    # receipt["status"]: accepted | pending | retryable | missing
```

`I2VSubmissionUnknownError.cause` holds the original HTTP or network error, including `retry_after_ms` and `request_id` when the API sent them.

## Webhooks

```python
from i2v import verify_webhook

secrets = {"key_1": os.environ["I2V_WEBHOOK_SECRET"]}

verified = verify_webhook(
    request.body,            # exact raw bytes, before parsing
    request.headers,         # dict-like with the X-I2V-* headers
    secrets.get,
    max_age_seconds=300,
)
if verified is None:
    raise PermissionError("untrusted delivery")
event = verified["body"]     # eventId matches the header
```

The signature covers the timestamp, a dot, and the raw body, and the event ID in the body must match the header.

## Errors

| Exception | Meaning |
| --- | --- |
| `I2VHttpError` | Non-2xx response. Carries `status`, `code`, `reason`, `request_id`, `retry_after_ms`. |
| `I2VSubmissionUnknownError` | The submission may be accepted (5xx, network failure, or HTTP 409 with `submission_pending`). Use `recover_submission`. |
| `I2VWaitTimeoutError` | The wait ended before the task reached a terminal state. |
| `I2VNetworkError` | No HTTP response. |
| `TypeError` / `ValueError` | Invalid local arguments, such as a non-HTTPS origin or a malformed budget. |

## Tests

```bash
cd packages/python-sdk
python -m unittest discover -s tests -v
```

The tests run against a local HTTP server; they never call the real API and need no credentials.
