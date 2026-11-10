import ssl
from pathlib import Path

import httpx
import pytest

from app.core.errors import (
    ConfigurationError,
    IneterResponseTooLargeError,
    IneterUnavailableError,
)
from app.seismic.infrastructure.ineter_client import (
    IneterHttpClient,
    _build_verify_option,
)
from tests.conftest import make_settings

HTML = "<html><body>ok</body></html>"


@pytest.mark.asyncio
async def test_retries_server_errors_then_succeeds() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return httpx.Response(503, text="unavailable")
        return httpx.Response(200, text=HTML, headers={"content-type": "text/html"})

    client = IneterHttpClient(
        make_settings(),
        transport=httpx.MockTransport(handler),
    )
    try:
        body = await client.fetch()
    finally:
        await client.aclose()

    assert body == HTML
    assert attempts == 3


@pytest.mark.asyncio
async def test_client_error_is_not_retried() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(404, text="not found")

    client = IneterHttpClient(
        make_settings(),
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(IneterUnavailableError):
            await client.fetch()
    finally:
        await client.aclose()

    assert attempts == 1


@pytest.mark.asyncio
async def test_transport_errors_are_retried() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ConnectError("connection refused", request=request)

    client = IneterHttpClient(
        make_settings(ineter_retries=2),
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(IneterUnavailableError):
            await client.fetch()
    finally:
        await client.aclose()

    assert attempts == 2


@pytest.mark.asyncio
async def test_oversized_response_is_rejected() -> None:
    client = IneterHttpClient(
        make_settings(ineter_max_response_bytes=10_000),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=b"x" * 10_001)
        ),
    )
    try:
        with pytest.raises(IneterResponseTooLargeError):
            await client.fetch()
    finally:
        await client.aclose()


def test_extra_ca_bundle_is_loaded_into_verification_context() -> None:
    bundle = (
        Path(__file__).parents[1]
        / "certs"
        / "sectigo-public-server-authentication-ca-ov-r36.pem"
    )

    option = _build_verify_option(make_settings(ineter_ca_bundle=str(bundle)))

    assert isinstance(option, ssl.SSLContext)


def test_missing_ca_bundle_fails_fast() -> None:
    with pytest.raises(ConfigurationError, match="does not exist"):
        _build_verify_option(make_settings(ineter_ca_bundle="missing-bundle.pem"))


def test_tls_verification_can_be_disabled_explicitly() -> None:
    assert _build_verify_option(make_settings(ineter_verify_tls=False)) is False


@pytest.mark.asyncio
async def test_rate_limit_retry_after_is_honored() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, text=HTML)

    client = IneterHttpClient(
        make_settings(),
        transport=httpx.MockTransport(handler),
    )
    try:
        body = await client.fetch()
    finally:
        await client.aclose()

    assert body == HTML
    assert attempts == 2
