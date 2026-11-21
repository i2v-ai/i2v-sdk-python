<p align="center">
  <a href="https://i2v.ai">
    <img src="https://i2v.ai/brand/folded-rabbit-light.png" alt="i2v.ai" width="96">
  </a>
</p>

<h1 align="center">i2v.ai Python SDK</h1>

<p align="center">
  Server-side Python client for i2v.ai image and video generation: catalog, quotes, uploads, tasks, recovery and signed webhooks.<br>
  Python 3.10 or newer · no runtime dependencies · quote before submit.
</p>

<p align="center">
  <a href="https://pypi.org/project/i2v-ai/"><img alt="PyPI" src="https://img.shields.io/pypi/v/i2v-ai?style=flat-square"></a>
  <a href="https://pypi.org/project/i2v-ai/"><img alt="Python" src="https://img.shields.io/pypi/pyversions/i2v-ai?style=flat-square"></a>
  <a href="https://i2v.ai/docs/integration"><img alt="Docs" src="https://img.shields.io/badge/docs-i2v.ai%2Fdocs%2Fintegration-6366f1?style=flat-square"></a>
  <a href="./LICENSE"><img alt="License" src="https://img.shields.io/badge/license-MIT-22c55e?style=flat-square"></a>
</p>

<br>

## Install

```bash
pip install i2v-ai
```

## Quick start

```python
import os
from i2v import I2VClient

client = I2VClient(api_key=os.environ["I2V_API_KEY"])
models = client.list_models().data["data"]        # public catalog, no key needed

quote = client.quote("gpt-image-2", {"prompt": "A ceramic mug"}).data
receipt = client.create_task(
    "gpt-image-2",
    {"prompt": "A ceramic mug"},
    max_cost_usd="0.20",
    expected_revision=quote["expectedRevision"],
    idempotency_key="order-1234-image",
).data
result = client.wait_for_task(receipt["taskId"], timeout=900).data
print(result["status"], result.get("output"))
```

## Error model

| Exception | Meaning |
| --- | --- |
| `I2VHttpError` | Non-2xx response. Carries `status`, `code`, `reason`, `request_id`, `retry_after_ms`. |
| `I2VSubmissionUnknownError` | The submission may be accepted (5xx, network failure, or HTTP 409 with `submission_pending`). Recover with `recover_submission(key)`. |
| `I2VWaitTimeoutError` | The wait ended before the task reached a terminal state. |

`verify_webhook(raw_body, headers, get_secret)` checks the timestamp window, the HMAC over `timestamp.body` and the event ID in the body.

## Development

```bash
python -m unittest discover -s tests -v
```

Releases publish from a `python-vX.Y.Z` tag through GitHub OIDC (see `.github/workflows/publish-pypi.yml`).

## For AI agents

- Agent index: <https://i2v.ai/llms.txt>
- Full documentation: <https://i2v.ai/llms-full.txt>
- Remote MCP server: <https://i2v.ai/api/mcp>

## Related repositories

| Repository | Purpose |
| --- | --- |
| [i2v-sdk-js](https://github.com/i2v-ai/i2v-sdk-js) | TypeScript SDK |
| [i2v-cli](https://github.com/i2v-ai/i2v-cli) | Command-line tools |
| [i2v-skills](https://github.com/i2v-ai/i2v-skills) | Agent Skills |
| [i2v-mcp](https://github.com/i2v-ai/i2v-mcp) | Remote MCP metadata |
| [generate-action](https://github.com/i2v-ai/generate-action) | GitHub Action |
| [i2v-api-examples](https://github.com/i2v-ai/i2v-api-examples) | Runnable examples |
| [i2v-agent-tools](https://github.com/i2v-ai/i2v-agent-tools) | Ecosystem hub |

## License

MIT. See [LICENSE](./LICENSE).
