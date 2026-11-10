"""HTTP adapter for the INETER events page with retries and rate control."""

from __future__ import annotations

import asyncio
import logging
import ssl
from pathlib import Path

import certifi
import httpx

from app.core.config import Settings
from app.core.errors import (
    ConfigurationError,
    IneterResponseTooLargeError,
    IneterUnavailableError,
)

logger = logging.getLogger(__name__)

_USER_AGENT = "INETER-Seismic-Events-Backend/1.0"
_PROJECT_ROOT = Path(__file__).resolve().parents[3]


class IneterHttpClient:
    """Fetch the INETER page using a bounded, retrying HTTP client.

    The polling interval itself is enforced by the sync worker. This adapter
    adds conservative retries, timeouts and a maximum response size so a
    source outage cannot exhaust API memory or block the event loop.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings
        verify = _build_verify_option(settings)
        self._client = httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(settings.ineter_timeout_seconds),
            follow_redirects=True,
            verify=verify,
            headers={
                "User-Agent": _USER_AGENT,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "es-NI,es;q=0.9,en;q=0.5",
            },
        )

    async def fetch(self) -> str:
        """Return the page body, retrying transient failures."""
        if not self._settings.ineter_verify_tls:
            logger.warning(
                "ineter tls verification is disabled",
                extra={"event": "ineter_tls_verification_disabled"},
            )

        last_error: Exception | None = None
        attempts = self._settings.ineter_retries

        for attempt in range(1, attempts + 1):
            try:
                response = await self._client.get(self._settings.ineter_url)
                if response.status_code == 429:
                    raise _RetryableStatusError(response, "HTTP 429")
                if response.status_code >= 500:
                    raise _RetryableStatusError(
                        response, f"HTTP {response.status_code}"
                    )
                response.raise_for_status()
                _enforce_size_limit(response, self._settings.ineter_max_response_bytes)
                return response.text

            except IneterResponseTooLargeError:
                raise
            except _RetryableStatusError as exc:
                last_error = exc
                if attempt < attempts:
                    delay = _retry_after_seconds(exc.response) or _backoff(
                        self._settings, attempt
                    )
                    logger.warning(
                        "ineter request failed with retryable status",
                        extra={
                            "event": "ineter_retry",
                            "attempt": attempt,
                            "status_code": exc.response.status_code,
                            "retry_in_seconds": delay,
                        },
                    )
                    await asyncio.sleep(delay)
                    continue
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code
                if 400 <= status_code < 500 and status_code != 429:
                    raise IneterUnavailableError(
                        f"INETER returned HTTP {status_code}"
                    ) from exc
                last_error = exc
                if attempt < attempts:
                    delay = _backoff(self._settings, attempt)
                    logger.warning(
                        "ineter request returned a retryable HTTP error",
                        extra={
                            "event": "ineter_retry",
                            "attempt": attempt,
                            "status_code": status_code,
                            "retry_in_seconds": delay,
                        },
                    )
                    await asyncio.sleep(delay)
                    continue
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
                if attempt < attempts:
                    delay = _backoff(self._settings, attempt)
                    logger.warning(
                        "ineter request failed with a transport error",
                        extra={
                            "event": "ineter_retry",
                            "attempt": attempt,
                            "error_type": type(exc).__name__,
                            "retry_in_seconds": delay,
                        },
                    )
                    await asyncio.sleep(delay)
                    continue
            except httpx.HTTPError as exc:
                raise IneterUnavailableError(
                    "Unexpected HTTP error while contacting INETER"
                ) from exc

        raise IneterUnavailableError(
            f"INETER is unavailable after {attempts} attempts"
        ) from last_error

    async def aclose(self) -> None:
        await self._client.aclose()


class _RetryableStatusError(Exception):
    def __init__(self, response: httpx.Response, message: str) -> None:
        self.response = response
        super().__init__(message)


def _build_verify_option(settings: Settings) -> bool | ssl.SSLContext:
    """Build the TLS verification option for the INETER HTTP client.

    INETER serves an incomplete certificate chain: it sends only the leaf
    certificate and omits the Sectigo intermediate CA. Browsers hide this by
    fetching the missing intermediate through the certificate AIA extension,
    but OpenSSL-based clients do not. ``INETER_CA_BUNDLE`` lets operators add
    that intermediate to the default certifi trust store without disabling
    verification.
    """
    if not settings.ineter_verify_tls:
        return False

    if not settings.ineter_ca_bundle:
        return True

    bundle_path = Path(settings.ineter_ca_bundle)
    if not bundle_path.is_absolute():
        bundle_path = _PROJECT_ROOT / bundle_path
    if not bundle_path.is_file():
        raise ConfigurationError(
            f"INETER CA bundle '{bundle_path}' does not exist"
        )

    context = ssl.create_default_context(cafile=certifi.where())
    context.load_verify_locations(cafile=str(bundle_path))
    logger.info(
        "loaded additional INETER CA certificates",
        extra={
            "event": "ineter_ca_bundle_loaded",
            "path": str(bundle_path),
        },
    )
    return context


def _retry_after_seconds(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After")
    if value is None:
        return None
    try:
        return min(max(float(value), 0.0), 30.0)
    except ValueError:
        return None


def _backoff(settings: Settings, attempt: int) -> float:
    return min(settings.ineter_retry_backoff_seconds * (2 ** (attempt - 1)), 30.0)


def _enforce_size_limit(response: httpx.Response, max_bytes: int) -> None:
    content_length = response.headers.get("Content-Length")
    if content_length is not None:
        try:
            declared_size = int(content_length)
        except ValueError:
            declared_size = None
        if declared_size is not None and declared_size > max_bytes:
            raise IneterResponseTooLargeError(
                f"INETER response declares {declared_size} bytes, limit is {max_bytes}"
            )

    actual_size = len(response.content)
    if actual_size > max_bytes:
        raise IneterResponseTooLargeError(
            f"INETER response has {actual_size} bytes, limit is {max_bytes}"
        )
