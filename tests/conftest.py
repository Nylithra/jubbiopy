"""Test altyapısı: sahte Jubbio gateway (WebSocket) + REST sunucusu."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional

import pytest
from aiohttp import WSMsgType, web

BOT_USER = {"id": "1000", "username": "testbot", "bot": True}
APP_ID = "5000"
GUILD = {
    "id": "200",
    "name": "Test Sunucusu",
    "owner_id": "1",
    "member_count": 3,
    "channels": [
        {"id": "300", "type": 0, "name": "genel", "guild_id": "200"},
        {"id": "301", "type": 2, "name": "ses", "guild_id": "200"},
    ],
}


class FakeJubbio:
    """Gateway ve REST API'yi taklit eden sunucu."""

    def __init__(self) -> None:
        self.requests: List[Dict[str, Any]] = []
        self.received: List[Dict[str, Any]] = []
        self.sockets: List[web.WebSocketResponse] = []
        self.connections = 0
        self.identified = asyncio.Event()
        self.ready_payload: Dict[str, Any] = {
            "v": 1, "user": BOT_USER, "guilds": [GUILD], "session_id": "sess", "application": {"id": int(APP_ID)},
        }
        self.close_on_identify: Optional[int] = None
        self.send_ready = True
        self.responses: Dict[str, Any] = {}
        self.runner: Optional[web.AppRunner] = None
        self.port = 0

    @property
    def gateway_url(self) -> str:
        return f"ws://127.0.0.1:{self.port}/ws/bot"

    @property
    def api_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/api/v1"

    async def start(self) -> None:
        app = web.Application()
        app.router.add_get("/ws/bot", self.ws_handler)
        app.router.add_route("*", "/api/v1/{tail:.*}", self.rest_handler)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        self.port = site._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]

    async def stop(self) -> None:
        for ws in self.sockets:
            await ws.close()
        if self.runner:
            await self.runner.cleanup()

    # --------------------------------------------------------------- gateway
    async def ws_handler(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.connections += 1
        self.sockets.append(ws)
        await ws.send_str(json.dumps({"op": 10, "d": {"heartbeat_interval": 100}}))
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            payload = json.loads(msg.data)
            self.received.append(payload)
            if payload["op"] == 2:
                self.identified.set()
                if self.close_on_identify:
                    await ws.close(code=self.close_on_identify, message=b"reddedildi")
                    break
                if self.send_ready:
                    await self.dispatch("READY", self.ready_payload, ws)
            elif payload["op"] == 1:
                await ws.send_str(json.dumps({"op": 11}))
        return ws

    async def dispatch(self, event: str, data: Any, ws: Optional[web.WebSocketResponse] = None) -> None:
        ws = ws or self.sockets[-1]
        await ws.send_str(json.dumps({"op": 0, "t": event, "s": len(self.received) + 1, "d": data}))

    # ------------------------------------------------------------------ REST
    async def rest_handler(self, request: web.Request) -> web.Response:
        path = "/" + request.match_info["tail"]
        entry: Dict[str, Any] = {
            "method": request.method,
            "path": path,
            "query": dict(request.query),
            "headers": dict(request.headers),
        }
        if request.content_type == "multipart/form-data":
            form = await request.post()
            entry["form"] = {k: (v.filename, v.file.read()) if hasattr(v, "filename") else v for k, v in form.items()}
        else:
            text = await request.text()
            entry["json"] = json.loads(text) if text else None
        self.requests.append(entry)
        key = f"{request.method} {path}"
        if key in self.responses:
            return web.json_response(self.responses[key])
        if request.method == "POST" and path.endswith("/messages"):
            body = entry.get("json") or {}
            return web.json_response({
                "id": "999", "channel_id": path.split("/")[-2], "content": body.get("content"),
                "author": BOT_USER, "timestamp": "2026-01-01T00:00:00.000Z",
            })
        if request.method == "GET" and path.startswith("/bot/users/"):
            return web.json_response({"id": path.rsplit("/", 1)[-1], "username": "fetched"})
        return web.Response(status=204)

    def find(self, method: str, path_part: str) -> List[Dict[str, Any]]:
        return [r for r in self.requests if r["method"] == method and path_part in r["path"]]


@pytest.fixture
async def server():
    fake = FakeJubbio()
    await fake.start()
    yield fake
    await fake.stop()


@pytest.fixture
async def client(server):
    from jubbiopy import Client, GatewayIntentBits

    bot = Client(
        intents=[GatewayIntentBits.Guilds, GatewayIntentBits.GuildMessages, GatewayIntentBits.MessageContent],
        gateway_url=server.gateway_url,
        api_url=server.api_url,
        ready_timeout=5,
    )
    yield bot
    await bot.destroy()


async def until(predicate, timeout: float = 3.0) -> None:
    """Koşul sağlanana kadar bekler (testler için)."""
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while not predicate():
        if loop.time() > end:
            raise AssertionError("Koşul zaman aşımına uğradı")
        await asyncio.sleep(0.01)
