import pytest

from app.realtime.application.connection_manager import (
    ConnectionLimitReachedError,
    ConnectionManager,
)


class DummyWebSocket:
    def __init__(self, *, fail_send: bool = False) -> None:
        self.fail_send = fail_send
        self.accepted = False
        self.closed_code: int | None = None
        self.sent: list[dict] = []
        self.client = None

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, payload: dict) -> None:
        if self.fail_send:
            raise RuntimeError("send failed")
        self.sent.append(payload)

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed_code = code


@pytest.mark.asyncio
async def test_capacity_is_enforced() -> None:
    manager = ConnectionManager(max_connections=1)
    first_socket = DummyWebSocket()
    second_socket = DummyWebSocket()

    await manager.connect(first_socket)
    with pytest.raises(ConnectionLimitReachedError):
        await manager.connect(second_socket)

    assert second_socket.closed_code == 1013
    assert await manager.connection_count() == 1


@pytest.mark.asyncio
async def test_failed_delivery_removes_only_that_client() -> None:
    manager = ConnectionManager(max_connections=10)
    healthy = DummyWebSocket()
    broken = DummyWebSocket(fail_send=True)

    healthy_connection = await manager.connect(healthy)
    await manager.connect(broken)

    result = await manager.broadcast({"type": "test"})

    assert result.sent == 1
    assert result.failed == 1
    assert await manager.connection_count() == 1
    assert healthy.sent == [{"type": "test"}]
    assert await manager.send_to(healthy_connection.id, {"type": "direct"}) is True
    assert await manager.send_to("missing", {"type": "direct"}) is False
