"""CodeXRay API — WebSocket fan-out (PRD §13, §14 real-time transport)."""

from __future__ import annotations

from collections import defaultdict

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        self._rooms: dict[str, set[WebSocket]] = defaultdict(set)

    async def connect(self, project_id: str, ws: WebSocket) -> None:
        # The route owns the handshake (it negotiates the subprotocol) —
        # this only registers an already-accepted socket for fan-out.
        self._rooms[project_id].add(ws)

    def disconnect(self, project_id: str, ws: WebSocket) -> None:
        self._rooms[project_id].discard(ws)

    async def broadcast(self, project_id: str, message: dict) -> None:
        dead: list[WebSocket] = []
        for ws in list(self._rooms.get(project_id, ())):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(project_id, ws)


manager = ConnectionManager()
