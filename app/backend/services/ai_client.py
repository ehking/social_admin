"""Client utilities for interacting with external AI video services."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Mapping

from ..http_logging import log_request_failure, log_request_start, log_request_success

try:  # pragma: no cover - optional dependency in some environments
    import requests
except Exception:  # pragma: no cover - gracefully degrade when requests missing
    requests = None  # type: ignore[assignment]


LOGGER = logging.getLogger(__name__)
_ENDPOINT_ENV_VAR = "AI_SERVICE_ENDPOINT"


class AIServiceError(RuntimeError):
    """Base class for AI service related failures."""


class AIServiceConfigurationError(AIServiceError):
    """Raised when dispatch configuration is missing or invalid."""


class AIServiceDispatchError(AIServiceError):
    """Raised when an outbound request to the AI service fails."""


@dataclass(frozen=True, slots=True)
class DispatchResult:
    """Structured response data for a dispatched AI job."""

    job_token: str | None
    response_payload: Mapping[str, object] | None


def get_ai_service_endpoint() -> str | None:
    """Return the configured AI service endpoint, if available."""

    endpoint = os.getenv(_ENDPOINT_ENV_VAR)
    if not endpoint:
        return None

    endpoint = endpoint.strip()
    return endpoint or None


def dispatch_manual_video_job(
    job_id: int,
    payload: Mapping[str, object],
    *,
    endpoint: str | None = None,
    timeout: float = 15.0,
) -> DispatchResult:
    """Send a manual video job definition to the external AI service."""

    url = endpoint or get_ai_service_endpoint()
    if not url:
        raise AIServiceConfigurationError(
            f"Missing AI service endpoint. Set {_ENDPOINT_ENV_VAR} or provide 'endpoint'."
        )

    if requests is None:
        raise AIServiceDispatchError("The requests library is unavailable.")

    request_payload = dict(payload)
    started_at = log_request_start(
        "POST",
        url,
        job_id=job_id,
        service="ai_generation",
    )

    try:
        response = requests.post(url, json=request_payload, timeout=timeout)
        response.raise_for_status()
    except Exception as exc:  # pragma: no cover - defensive network error handling
        log_request_failure(
            "POST",
            url,
            started_at=started_at,
            error=exc,
            job_id=job_id,
            service="ai_generation",
        )
        raise AIServiceDispatchError("Failed to dispatch manual video job to AI service") from exc

    log_request_success(
        "POST",
        url,
        status=getattr(response, "status_code", 0),
        started_at=started_at,
        job_id=job_id,
        service="ai_generation",
    )

    response_payload: Mapping[str, object] | None = None
    job_token: str | None = None

    parsed = None
    try:
        if hasattr(response, "json"):
            parsed = response.json()
    except ValueError:
        LOGGER.warning(
            "AI service response did not contain valid JSON",
            extra={"job_id": job_id},
        )
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            close()

    if isinstance(parsed, Mapping):
        response_payload = dict(parsed)
        token_value = (
            response_payload.get("job_id")
            or response_payload.get("id")
            or response_payload.get("token")
            or response_payload.get("job_token")
        )
        if token_value is not None:
            job_token = str(token_value)

    LOGGER.info(
        "Dispatched manual video job to AI service",
        extra={"job_id": job_id, "ai_job_token": job_token},
    )

    return DispatchResult(job_token=job_token, response_payload=response_payload)


__all__ = [
    "DispatchResult",
    "AIServiceError",
    "AIServiceConfigurationError",
    "AIServiceDispatchError",
    "dispatch_manual_video_job",
    "get_ai_service_endpoint",
]

