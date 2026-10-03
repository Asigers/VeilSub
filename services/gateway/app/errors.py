"""Shared redaction for errors sent to clients or recorded in local logs."""

import re

from pydantic import ValidationError

from app.config import Settings


def safe_error_message(exc: Exception, settings: Settings | None = None) -> str:
    if isinstance(exc, ValidationError):
        # Default Pydantic messages include input values, possibly credentials.
        fields = sorted({".".join(map(str, error["loc"])) for error in exc.errors()})
        return "Invalid configuration or request fields: " + ", ".join(fields)
    message = str(exc) or "stream operation timed out"
    if settings is not None:
        for value in (
            settings.dashscope_api_key,
            settings.alibaba_cloud_access_key_id,
            settings.alibaba_cloud_access_key_secret,
            settings.aliyun_bailian_workspace_id,
        ):
            if value:
                message = message.replace(value, "<redacted>")
    message = re.sub(r"\bsk-[A-Za-z0-9_.-]+", "<redacted-api-key>", message)
    message = re.sub(r"\bLTAI[A-Za-z0-9]+", "<redacted-access-key>", message)
    message = re.sub(r"(?i)Bearer\s+[^\s\"',}]+", "Bearer <redacted>", message)
    return message[:2000]
