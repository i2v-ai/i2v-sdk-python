"""Server-side Python client for the i2v.ai image and video API."""

from .client import DEFAULT_BASE_URL, I2VClient, Result
from .errors import (
    I2VError,
    I2VHttpError,
    I2VNetworkError,
    I2VSubmissionUnknownError,
    I2VWaitTimeoutError,
)
from .webhook import verify_webhook

__all__ = [
    "DEFAULT_BASE_URL",
    "I2VClient",
    "I2VError",
    "I2VHttpError",
    "I2VNetworkError",
    "I2VSubmissionUnknownError",
    "I2VWaitTimeoutError",
    "Result",
    "verify_webhook",
]

__version__ = "0.1.0"
