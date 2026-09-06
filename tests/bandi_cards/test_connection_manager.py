import asyncio

from bandi_cards.realtime.connection_manager import ConnectionManager


class FakeWebSocket:
    def __init__(self) -> None:
        self.accepted = 0
        self.sent: list[dict] = []

    async def accept(self) -> None:
        self.accepted += 1

    async def send_json(self, message: dict) -> None:
        self.sent.append(message)


class StalledWebSocket(FakeWebSocket):
    async def send_json(self, _message: dict) -> None:
        await asyncio.Event().wait()


def test_broadcast_all_sends_once_to_every_live_socket():
    async def scenario() -> None:
        manager = ConnectionManager()
        first = FakeWebSocket()
        second = FakeWebSocket()
        second_tab = FakeWebSocket()
        await manager.connect(1, first)
        await manager.connect(2, second)
        await manager.connect(2, second_tab)

        await manager.broadcast_all({"type": "season.reset"})

        assert first.sent == [{"type": "season.reset"}]
        assert second.sent == [{"type": "season.reset"}]
        assert second_tab.sent == [{"type": "season.reset"}]

    asyncio.run(scenario())


def test_broadcast_drops_stalled_socket_without_blocking_healthy_socket():
    async def scenario() -> None:
        manager = ConnectionManager()
        manager.send_timeout_seconds = 0.01
        stalled = StalledWebSocket()
        healthy = FakeWebSocket()
        await manager.connect(1, stalled)
        await manager.connect(2, healthy)

        await asyncio.wait_for(manager.broadcast_all({"type": "season.reset"}), timeout=0.2)

        assert manager.is_online(1) is False
        assert manager.is_online(2) is True
        assert healthy.sent == [{"type": "season.reset"}]

    asyncio.run(scenario())
