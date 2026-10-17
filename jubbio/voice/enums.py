"""Ses sabitleri (``@jubbio/voice`` enums ile birebir)."""

from __future__ import annotations

from enum import Enum


class VoiceConnectionStatus(str, Enum):
    Connecting = "connecting"
    Ready = "ready"
    Disconnected = "disconnected"
    Destroyed = "destroyed"
    Signalling = "signalling"


class AudioPlayerStatus(str, Enum):
    Idle = "idle"
    Buffering = "buffering"
    Playing = "playing"
    Paused = "paused"
    AutoPaused = "autopaused"


class StreamType(str, Enum):
    Arbitrary = "arbitrary"
    Raw = "raw"
    Opus = "opus"
    OggOpus = "ogg/opus"
    WebmOpus = "webm/opus"


class NoSubscriberBehavior(str, Enum):
    Pause = "pause"
    Play = "play"
    Stop = "stop"
