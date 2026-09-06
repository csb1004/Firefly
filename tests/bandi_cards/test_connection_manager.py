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
