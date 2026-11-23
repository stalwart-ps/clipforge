import asyncio
from typing import Dict, List
from fastapi import WebSocket


class ConnectionManager:
    """Manages active WebSockets and broadcasts live progress updates per project."""

    def __init__(self):
        self._connections: Dict[str, List[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, project_id: str, websocket: WebSocket):
        await websocket.accept()
        async with self._lock:
            if project_id not in self._connections:
                self._connections[project_id] = []
            self._connections[project_id].append(websocket)

    async def disconnect(self, project_id: str, websocket: WebSocket):
        async with self._lock:
            if project_id in self._connections:
                if websocket in self._connections[project_id]:
                    self._connections[project_id].remove(websocket)
                if not self._connections[project_id]:
                    del self._connections[project_id]

    async def broadcast(self, project_id: str, message: dict):
        async with self._lock:
            sockets = list(self._connections.get(project_id, []))

        for ws in sockets:
            try:
                await ws.send_json(message)
            except Exception:
                pass


ws_manager = ConnectionManager()
