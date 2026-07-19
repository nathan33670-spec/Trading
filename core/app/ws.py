"""Diffusion temps réel vers la PWA (positions, trades, signaux)."""
import asyncio
import json
import logging

from fastapi import WebSocket

log = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        self.connections: list[WebSocket] = []
        self.loop: asyncio.AbstractEventLoop | None = None

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.connections.append(ws)

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self.connections:
            self.connections.remove(ws)

    async def broadcast(self, message: dict) -> None:
        data = json.dumps(message, default=str)
        for ws in list(self.connections):
            try:
                await ws.send_text(data)
            except Exception:
                self.disconnect(ws)

    def broadcast_sync(self, message: dict) -> None:
        """Diffusion depuis un thread du scheduler (hors boucle asyncio)."""
        if self.loop is None or not self.connections:
            return
        try:
            asyncio.run_coroutine_threadsafe(self.broadcast(message), self.loop)
        except Exception as exc:
            log.debug("Broadcast WS impossible: %s", exc)


manager = ConnectionManager()
