"""examples/muzik_bot/bot.py için uçtan uca test (sahte sunucu + sahte LiveKit + gerçek çözücü)."""

from __future__ import annotations

import importlib.util
import math
import os
import shutil
import struct
import sys
import wave

import pytest

from jubbiopy.voice import AudioPlayerStatus, enters_state
from jubbiopy.voice import player as player_module

from .conftest import APP_ID, until
from .test_voice import FakeAudioSource, fake_rtc

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None and player_module._import_av() is None, reason="Ses çözücü yok")


@pytest.fixture
def music_module(monkeypatch):
    monkeypatch.setattr(player_module, "_import_rtc", fake_rtc)
    FakeAudioSource.instances.clear()
    spec = importlib.util.spec_from_file_location("muzik_bot", os.path.join(ROOT, "examples", "muzik_bot", "bot.py"))
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "muzik_bot", module)
    spec.loader.exec_module(module)
    return module


def make_wav(path, seconds=0.4, freq=440):
    with wave.open(str(path), "wb") as out:
        out.setnchannels(2)
        out.setsampwidth(2)
        out.setframerate(48000)
        frames = (int(6000 * math.sin(2 * math.pi * freq * i / 48000)) for i in range(int(48000 * seconds)))
        out.writeframes(b"".join(struct.pack("<hh", s, s) for s in frames))
    return str(path)


USER = {"user": {"id": "7", "username": "ali"}, "roles": [], "joined_at": "2025-01-01T00:00:00Z"}
ADMIN = {"user": {"id": "1", "username": "sahip"}, "roles": [], "joined_at": "2025-01-01T00:00:00Z", "permissions": "8"}


def command(i, member, name, options=()):
    return {"id": str(i), "application_id": APP_ID, "guild_id": "200", "channel_id": "300", "token": f"t{i}",
            "member": member, "type": 2, "data": {"name": name, "options": list(options)}}


def button(i, member, action):
    return {"id": str(i), "application_id": APP_ID, "guild_id": "200", "channel_id": "300", "token": f"t{i}",
            "member": member, "type": 3, "data": {"custom_id": f"music:{action}", "component_type": 2},
            "message": {"id": "m", "channel_id": "300"}}


async def test_music_bot_flow(server, tmp_path, music_module):
    server.responses["PUT /applications/5000/commands"] = []
    bot = music_module.MusicBot(str(tmp_path / "m.json"), gateway_url=server.gateway_url,
                                api_url=server.api_url, ready_timeout=5)
    client = bot.client
    first, second = make_wav(tmp_path / "bir.wav"), make_wav(tmp_path / "iki.wav", freq=660)

    async def send(payload):
        path = f"/interactions/{payload['id']}/"
        await server.dispatch("INTERACTION_CREATE", payload)
        await until(lambda: server.find("POST", path), timeout=5)
        return server.find("POST", path)

    def channel_texts():
        out = []
        for r in server.find("POST", "/bot/guilds/200/channels/300/messages"):
            for e in (r["json"] or {}).get("embeds") or []:
                out.append((e.get("title") or "") + " " + (e.get("description") or ""))
        return out

    try:
        await client.login("t")
        await until(lambda: server.find("PUT", "/applications/5000/commands"))

        # Ses kanalında değilken çalamaz
        resp = await send(command(1, USER, "cal", [{"name": "sarki", "type": 3, "value": first}]))
        assert "ses kanalına katıl" in resp[0]["json"]["data"]["embeds"][0]["description"]

        # Kullanıcı ses kanalına girer
        await server.dispatch("VOICE_STATE_UPDATE", {"guild_id": "200", "user_id": "7", "channel_id": "301",
                                                     "user": {"id": "7", "username": "ali"}})
        await until(lambda: client.guilds.get("200").members.get("7") is not None)

        await send(command(2, USER, "cal", [{"name": "sarki", "type": 3, "value": first}]))
        await until(lambda: any(p["op"] == 4 for p in server.received))
        join = next(p for p in server.received if p["op"] == 4)
        assert join["d"]["channel_id"] == "301"
        await server.dispatch("VOICE_SERVER_UPDATE", {"guild_id": "200", "token": "lk", "endpoint": "wss://lk", "room": "r"})

        gm = bot.music["200"]
        await send(command(3, USER, "cal", [{"name": "sarki", "type": 3, "value": second}]))
        assert [t.title for t in gm.queue] == ["iki.wav"]

        await enters_state(gm.player, AudioPlayerStatus.Playing, 10)
        await send(command(4, USER, "ses", [{"name": "seviye", "type": 4, "value": 50}]))
        assert gm.resource.volume == 0.5 and bot.settings.get("200")["volume"] == 50

        resp = await send(command(5, USER, "sira"))
        assert "iki.wav" in resp[-1]["json"]["data"]["embeds"][0]["description"]

        # Döngü butonu: kapalı -> şarkı
        await send(button(6, USER, "loop"))
        assert gm.loop == "track"
        await send(button(7, USER, "loop"))
        await send(button(8, USER, "loop"))
        assert gm.loop == "off"

        # İlk şarkı biter -> ikinci otomatik başlar -> sıra biter
        await until(lambda: gm.current is not None and gm.current.title == "iki.wav", timeout=10)
        await until(lambda: any("Sıra bitti" in t for t in channel_texts()), timeout=10)
        assert [t.title for t in gm.history] == ["bir.wav", "iki.wav"]
        assert sum("Şimdi Çalıyor" in t for t in channel_texts()) == 2
        assert gm.idle_task is not None  # otomatik ayrılma zamanlandı

        # DJ rolü: yönetici ayarlar, normal kullanıcı kontrol edemez
        await send(command(9, ADMIN, "dj-rol", [{"name": "rol", "type": 8, "value": "900"}]))
        await send(command(10, USER, "cal", [{"name": "sarki", "type": 3, "value": first}]))
        await enters_state(gm.player, AudioPlayerStatus.Playing, 10)
        other = {"user": {"id": "8", "username": "veli"}, "roles": [], "joined_at": "2025-01-01T00:00:00Z"}
        resp = await send(command(11, other, "duraklat"))
        assert "DJ" in resp[0]["json"]["data"]["embeds"][0]["description"]
        # Şarkıyı isteyen kişi kendi şarkısını geçebilir
        await send(command(12, USER, "gec"))

        await send(command(13, ADMIN, "ayril"))
        assert gm.connection is None and gm.current is None
    finally:
        await client.destroy()
