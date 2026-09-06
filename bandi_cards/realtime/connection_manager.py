from __future__ import annotations

import asyncio
from collections import defaultdict

from fastapi import WebSocket


class WebSocketAcceptTimeout(RuntimeError):
    """Raised when a websocket cannot finish its handshake promptly."""


class ConnectionManager:
    def __init__(self):
        self.connections: dict[int, set[WebSocket]] = defaultdict(set)
        self.disconnect_tasks: dict[int, asyncio.Task] = {}
        self.accept_timeout_seconds = 3.0
        self.send_timeout_seconds = 2.0

    async def connect(self, user_id: int, websocket: WebSocket) -> bool:
        try:
            await asyncio.wait_for(websocket.accept(), timeout=self.accept_timeout_seconds)
        except TimeoutError as exc:
            raise WebSocketAcceptTimeout from exc
        task = self.disconnect_tasks.pop(user_id, None)
        if task:
            task.cancel()
        was_offline = not self.connections.get(user_id)
        self.connections[user_id].add(websocket)
        return was_offline

    def disconnect(self, user_id: int, websocket: WebSocket) -> bool:
        sockets = self.connections.get(user_id)
        if sockets:
            sockets.discard(websocket)
            if not sockets:
                self.connections.pop(user_id, None)
        return not self.is_online(user_id)

    def is_online(self, user_id: int) -> bool:
        return bool(self.connections.get(user_id))

    async def send(self, user_id: int, message: dict) -> None:
        async def send_one(websocket: WebSocket) -> WebSocket | None:
            try:
                await asyncio.wait_for(
                    websocket.send_json(message),
                    timeout=self.send_timeout_seconds,
                )
            except Exception:
                return websocket
            return None

        sockets = tuple(self.connections.get(user_id, ()))
        dead = await asyncio.gather(*(send_one(websocket) for websocket in sockets))
        for websocket in dead:
            if websocket is not None:
                self.disconnect(user_id, websocket)

    async def send_many(self, user_ids: list[int], message: dict) -> None:
        await asyncio.gather(*(self.send(user_id, message) for user_id in set(user_ids)))

    async def broadcast_all(self, message: dict) -> None:
        await self.send_many(list(self.connections), message)


manager = ConnectionManager()
