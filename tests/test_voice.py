"""Ses testleri: sahte LiveKit modülü + gerçek FFmpeg ile çözme."""

from __future__ import annotations

import asyncio
import math
import shutil
import struct
import types
import wave

import pytest

from jubbiopy.voice import (
    AudioPlayerStatus,
    VoiceConnectionStatus,
    create_audio_player,
    create_audio_resource,
    enters_state,
    get_voice_connection,
    join_voice_channel,
)
from jubbiopy.voice import player as player_module
from jubbiopy.voice.player import FRAME_SIZE, _apply_volume

from .conftest import until


class FakeRoom:
    def __init__(self):
        self.handlers = {}
        self.connected_with = None
        self.local_participant = types.SimpleNamespace(published=[])

        async def publish_track(track, options):
            self.local_participant.published.append((track, options))

        self.local_participant.publish_track = publish_track

    def on(self, event, fn=None):
        if fn is None:
            def deco(f):
                self.handlers[event] = f
                return f
            return deco
        self.handlers[event] = fn

    async def connect(self, url, token):
        self.connected_with = (url, token)

    async def disconnect(self):
        self.connected_with = None


class FakeAudioSource:
    instances = []

    def __init__(self, rate, channels):
        self.frames = []
        FakeAudioSource.instances.append(self)

    async def capture_frame(self, frame):
        self.frames.append(frame)
        await asyncio.sleep(0)

    def clear_queue(self):
        pass


def fake_rtc():
    return types.SimpleNamespace(
        Room=FakeRoom,
        AudioSource=FakeAudioSource,
        AudioFrame=lambda data, rate, ch, spc: {"data": data, "rate": rate, "channels": ch, "samples": spc},
        LocalAudioTrack=types.SimpleNamespace(create_audio_track=lambda name, src: ("track", name, src)),
        TrackPublishOptions=lambda source: {"source": source},
        TrackSource=types.SimpleNamespace(SOURCE_MICROPHONE=2),
    )


@pytest.fixture(autouse=True)
def patch_rtc(monkeypatch):
    FakeAudioSource.instances.clear()
    monkeypatch.setattr(player_module, "_import_rtc", fake_rtc)


@pytest.fixture
def wav_file(tmp_path):
    path = tmp_path / "ton.wav"
    with wave.open(str(path), "wb") as out:
        out.setnchannels(2)
        out.setsampwidth(2)
        out.setframerate(48000)
        samples = (int(8000 * math.sin(2 * math.pi * 440 * i / 48000)) for i in range(48000 // 2))
        out.writeframes(b"".join(struct.pack("<hh", s, s) for s in samples))
    return path


async def _connect(client, server):
    await client.login("t")
    connection = join_voice_channel(channel_id="301", guild_id="200", adapter_creator=client.voice.adapters["200"])
    await until(lambda: any(p["op"] == 4 for p in server.received))
    join = next(p for p in server.received if p["op"] == 4)
    assert join["d"] == {"guild_id": "200", "channel_id": "301", "self_mute": False, "self_deaf": False}
    await server.dispatch("VOICE_SERVER_UPDATE", {"guild_id": "200", "token": "lk", "endpoint": "wss://lk", "room": "r"})
    await enters_state(connection, VoiceConnectionStatus.Ready, 3)
    assert connection.get_room().connected_with == ("wss://lk", "lk")
    return connection


async def test_join_and_disconnect(client, server):
    connection = await _connect(client, server)
    assert get_voice_connection("200") is connection

    # Başka bir kullanıcının ayrılması bağlantıyı etkilememeli
    await server.dispatch("VOICE_STATE_UPDATE", {"guild_id": "200", "user_id": "7", "channel_id": None})
    await asyncio.sleep(0.1)
    assert connection.state.status == VoiceConnectionStatus.Ready

    await server.dispatch("VOICE_STATE_UPDATE", {"guild_id": "200", "user_id": "1000", "channel_id": None})
    await enters_state(connection, VoiceConnectionStatus.Disconnected, 3)

    connection.destroy()
    assert connection.state.status == VoiceConnectionStatus.Destroyed
    assert get_voice_connection("200") is None
    await until(lambda: [p for p in server.received if p["op"] == 4][-1]["d"]["channel_id"] is None)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg kurulu değil")
async def test_play_file_until_idle(client, server, wav_file):
    connection = await _connect(client, server)
    player = create_audio_player()
    states = []
    player.on("stateChange", lambda old, new: states.append(new.status))
    connection.subscribe(player)
    resource = create_audio_resource(str(wav_file), metadata={"title": "Ton"})
    player.play(resource)

    await enters_state(player, AudioPlayerStatus.Playing, 10)
    await enters_state(player, AudioPlayerStatus.Idle, 10)
    source = FakeAudioSource.instances[0]
    assert len(source.frames) == 25  # 0.5 sn / 20 ms
    assert all(len(f["data"]) == FRAME_SIZE and f["samples"] == 960 for f in source.frames)
    assert states == [AudioPlayerStatus.Buffering, AudioPlayerStatus.Playing, AudioPlayerStatus.Idle]
    assert connection.get_room().local_participant.published
    assert resource.ended and resource.playback_duration == pytest.approx(0.5)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg kurulu değil")
async def test_pause_and_bad_input(client, server, wav_file, tmp_path):
    connection = await _connect(client, server)
    player = create_audio_player()
    connection.subscribe(player)
    player.play(create_audio_resource(str(wav_file)))
    await enters_state(player, AudioPlayerStatus.Playing, 10)
    assert player.pause() and player.state.status == AudioPlayerStatus.Paused
    assert not player.pause()
    assert player.unpause()
    assert player.stop() and player.state.status == AudioPlayerStatus.Idle

    errors = []
    player.on("error", errors.append)
    bad = tmp_path / "bozuk.mp3"
    bad.write_bytes(b"bu bir ses dosyasi degil")
    player.play(create_audio_resource(str(bad)))
    await until(lambda: errors, timeout=10)
    assert "FFmpeg" in errors[0].message and player.state.status == AudioPlayerStatus.Idle


def test_volume_scaling():
    frame = struct.pack("<hhhh", 1000, -1000, 30000, -30000)
    assert struct.unpack("<hhhh", _apply_volume(frame, 0.5)) == (500, -500, 15000, -15000)
    assert struct.unpack("<hhhh", _apply_volume(frame, 2.0))[2:] == (32767, -32768)


def test_yt_dlp_command_resolution(monkeypatch):
    import importlib.util
    import sys

    from jubbiopy.voice import resource

    monkeypatch.delenv("YTDLP_PATH", raising=False)
    monkeypatch.setattr(resource.shutil, "which", lambda name: None)
    monkeypatch.setattr(resource, "_find_in_scripts", lambda name: None)
    monkeypatch.setattr(resource.os.path, "expanduser", lambda p: "/yok/" + p)

    # pip paketi kuruluysa "python -m yt_dlp" kullanılır (Windows Store Python senaryosu)
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object() if name == "yt_dlp" else None)
    assert resource.yt_dlp_command() == [sys.executable, "-m", "yt_dlp"]

    # Hiçbiri yoksa açıklayıcı hata
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    with pytest.raises(FileNotFoundError, match="pip install yt-dlp"):
        resource.yt_dlp_command()

    # Elle verilen yol her zaman önceliklidir
    monkeypatch.setenv("YTDLP_PATH", r"C:\araclar\yt-dlp.exe")
    assert resource.yt_dlp_command() == ["/yok/" + r"C:\araclar\yt-dlp.exe"]


def test_ffmpeg_missing_message(monkeypatch):
    from jubbiopy.voice import resource

    monkeypatch.delenv("FFMPEG_PATH", raising=False)
    monkeypatch.setattr(resource.shutil, "which", lambda name: None)
    monkeypatch.setattr(resource, "_find_in_scripts", lambda name: None)
    with pytest.raises(FileNotFoundError, match="FFmpeg bulunamadı"):
        resource.find_ffmpeg()


@pytest.mark.skipif(player_module._import_av() is None, reason="PyAV kurulu değil")
async def test_pyav_backend_without_ffmpeg(client, server, wav_file, tmp_path, monkeypatch):
    """FFmpeg programı yokken 'auto' mod PyAV'a geçer ve aynı sonucu üretir."""
    def missing(*_a, **_k):
        raise FileNotFoundError("yok")

    monkeypatch.setattr(player_module, "find_ffmpeg", missing)
    connection = await _connect(client, server)
    player = create_audio_player()
    assert player._select_backend() == "pyav"
    connection.subscribe(player)
    player.play(create_audio_resource(str(wav_file)))
    await enters_state(player, AudioPlayerStatus.Playing, 10)
    await enters_state(player, AudioPlayerStatus.Idle, 10)
    source = FakeAudioSource.instances[0]
    assert len(source.frames) == 25
    assert all(len(f["data"]) == FRAME_SIZE for f in source.frames)
    # Ses verisi gerçekten çözülmüş (sessizlik değil)
    assert any(any(f["data"][i] for i in range(0, FRAME_SIZE, 97)) for f in source.frames)

    errors = []
    player.on("error", errors.append)
    bad = tmp_path / "bozuk.mp3"
    bad.write_bytes(b"bu bir ses dosyasi degil")
    player.play(create_audio_resource(str(bad)))
    await until(lambda: errors, timeout=10)
    assert "PyAV" in errors[0].message and player.state.status == AudioPlayerStatus.Idle


def test_no_decoder_message(monkeypatch):
    def missing(*_a, **_k):
        raise FileNotFoundError("yok")

    monkeypatch.setattr(player_module, "find_ffmpeg", missing)
    monkeypatch.setattr(player_module, "_import_av", lambda: None)
    with pytest.raises(RuntimeError, match="pip install av"):
        create_audio_player()._select_backend()
