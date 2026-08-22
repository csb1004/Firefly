from __future__ import annotations

import asyncio
from collections import defaultdict

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        self.connections: dict[int, set[WebSocket]] = defaultdict(set)
        self.disconnect_tasks: dict[int, asyncio.Task] = {}

    async def connect(self, user_id: int, websocket: WebSocket) -> bool:
        task = self.disconnect_tasks.pop(user_id, None)
        if task:
            task.cancel()
        was_offline = not self.connections[user_id]
        await websocket.accept()
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
        dead = []
        for websocket in tuple(self.connections.get(user_id, ())):
            try:
                await websocket.send_json(message)
            except Exception:
                dead.append(websocket)
        for websocket in dead:
            self.disconnect(user_id, websocket)

    async def send_many(self, user_ids: list[int], message: dict) -> None:
        await asyncio.gather(*(self.send(user_id, message) for user_id in set(user_ids)))


manager = ConnectionManager()
