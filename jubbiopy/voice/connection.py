"""``VoiceConnection``: ses kanalına katılım ve LiveKit oda bağlantısı."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Dict, Mapping, Optional, Union

from .._utils import CamelCaseCompat
from ..events import EventEmitter
from .enums import VoiceConnectionStatus

if TYPE_CHECKING:
    from .player import AudioPlayer

log = logging.getLogger("jubbiopy.voice")

AdapterCreator = Callable[[Any], Any]


@dataclass
class VoiceConnectionState:
    status: VoiceConnectionStatus


class _AdapterMethods:
    """Gateway olaylarını bağlantıya ileten metotlar (adaptöre verilir)."""

    def __init__(self, connection: "VoiceConnection") -> None:
        self._connection = connection

    def on_voice_server_update(self, data: Mapping[str, Any]) -> None:
        self._connection._handle_voice_server_update(data)

    def on_voice_state_update(self, data: Mapping[str, Any]) -> None:
        self._connection._handle_voice_state_update(data)

    def destroy(self) -> None:
        self._connection.destroy()

    onVoiceServerUpdate = on_voice_server_update
    onVoiceStateUpdate = on_voice_state_update


class VoiceConnection(EventEmitter, CamelCaseCompat):
    """Bir ses kanalı bağlantısı. Olaylar: ``stateChange(old, new)``, ``error(exc)``."""

    def __init__(
        self,
        *,
        channel_id: str,
        guild_id: str,
        adapter_creator: AdapterCreator,
        self_mute: bool = False,
        self_deaf: bool = False,
    ) -> None:
        super().__init__()
        if adapter_creator is None:
            raise ValueError(
                "adapter_creator gerekli. client.voice.adapters.get(guild_id) veya guild.voice_adapter_creator kullanın."
            )
        self.state = VoiceConnectionState(VoiceConnectionStatus.Connecting)
        self.channel_id = str(channel_id)
        self.guild_id = str(guild_id)
        self.self_mute = self_mute
        self.self_deaf = self_deaf
        self.room: Any = None
        self.livekit_endpoint: Optional[str] = None
        self.livekit_token: Optional[str] = None
        self.livekit_room_name: Optional[str] = None
        self.subscribed_player: Optional["AudioPlayer"] = None
        self._adapter_methods = _AdapterMethods(self)
        self._adapter = adapter_creator(self._adapter_methods)
        self._connect_task: Optional[asyncio.Task] = None
        self._send_voice_state_update(self.channel_id, self_mute, self_deaf)

    # ============================================================ abonelik
    def subscribe(self, player: "AudioPlayer") -> "AudioPlayer":
        """Bir ``AudioPlayer``'ı bu bağlantıya bağlar."""
        if self.subscribed_player is not None and self.subscribed_player is not player:
            self.subscribed_player.unsubscribe(self)
        self.subscribed_player = player
        player.subscribe(self)
        if self.room is not None:
            player.on_connection_ready(self)
        return player

    def unsubscribe(self) -> None:
        if self.subscribed_player is not None:
            self.subscribed_player.unsubscribe(self)
            self.subscribed_player = None

    def get_room(self) -> Any:
        return self.room

    # ============================================================== kontrol
    def disconnect(self) -> bool:
        """Ses kanalından ayrılır (bağlantı nesnesi tekrar ``rejoin`` edilebilir)."""
        return self._send_voice_state_update(None)

    def rejoin(self, *, channel_id: Optional[str] = None, self_mute: Optional[bool] = None,
               self_deaf: Optional[bool] = None) -> bool:
        if channel_id is not None:
            self.channel_id = str(channel_id)
        if self_mute is not None:
            self.self_mute = self_mute
        if self_deaf is not None:
            self.self_deaf = self_deaf
        return self._send_voice_state_update(self.channel_id, self.self_mute, self.self_deaf)

    def destroy(self, adapter_available: bool = True) -> None:
        """Bağlantıyı tamamen kapatır ve kanaldan ayrılır."""
        if self.state.status == VoiceConnectionStatus.Destroyed:
            return
        if adapter_available:
            self._send_voice_state_update(None)
        self.unsubscribe()
        self._schedule(self._disconnect_from_livekit())
        if self._adapter is not None:
            self._adapter.destroy()
        if _connections.get(self.guild_id) is self:
            del _connections[self.guild_id]
        self._set_state(VoiceConnectionStatus.Destroyed)

    # ============================================================== gateway
    def _send_voice_state_update(self, channel_id: Optional[str], self_mute: bool = False, self_deaf: bool = False) -> bool:
        if self._adapter is None:
            return False
        send = getattr(self._adapter, "send_payload", None) or getattr(self._adapter, "sendPayload")
        return bool(send({
            "op": 4,  # VOICE_STATE_UPDATE
            "d": {"guild_id": self.guild_id, "channel_id": channel_id, "self_mute": self_mute, "self_deaf": self_deaf},
        }))

    def _handle_voice_server_update(self, data: Mapping[str, Any]) -> None:
        self.livekit_endpoint = data.get("endpoint")
        self.livekit_token = data.get("token")
        self.livekit_room_name = data.get("room")
        self._set_state(VoiceConnectionStatus.Signalling)
        if self._connect_task is not None and not self._connect_task.done():
            self._connect_task.cancel()
        self._connect_task = self._schedule(self._connect_to_livekit())

    def _handle_voice_state_update(self, data: Mapping[str, Any]) -> None:
        # Sadece bot'un kendi ses durumu bu bağlantıyı etkiler
        bot_id = getattr(self._adapter, "user_id", None)
        if bot_id and data.get("user_id") is not None and str(data["user_id"]) != str(bot_id):
            return
        if data.get("channel_id") is None:
            self._schedule(self._disconnect_from_livekit())
            if self.state.status != VoiceConnectionStatus.Destroyed:
                self._set_state(VoiceConnectionStatus.Disconnected)
        else:
            self.channel_id = str(data["channel_id"])

    # ============================================================== LiveKit
    async def _connect_to_livekit(self) -> None:
        if not self.livekit_endpoint or not self.livekit_token:
            self.emit("error", RuntimeError("LiveKit bağlantı bilgisi eksik"))
            return
        try:
            from .player import _import_rtc

            rtc = _import_rtc()
            await self._disconnect_from_livekit()
            room = rtc.Room()

            @room.on("disconnected")
            def _on_disconnected(*_: Any) -> None:
                if self.room is room and self.state.status != VoiceConnectionStatus.Destroyed:
                    self.room = None
                    self._set_state(VoiceConnectionStatus.Disconnected)

            await room.connect(self.livekit_endpoint, self.livekit_token)
            if self.state.status == VoiceConnectionStatus.Destroyed:
                await room.disconnect()
                return
            self.room = room
            self._set_state(VoiceConnectionStatus.Ready)
            if self.subscribed_player is not None:
                self.subscribed_player.on_connection_ready(self)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            self.emit("error", exc)
            if self.state.status != VoiceConnectionStatus.Destroyed:
                self._set_state(VoiceConnectionStatus.Disconnected)

    async def _disconnect_from_livekit(self) -> None:
        room, self.room = self.room, None
        if room is not None:
            try:
                await room.disconnect()
            except Exception:  # noqa: BLE001 - kapatma hataları yok sayılır
                pass

    # ============================================================ yardımcı
    def _schedule(self, coro: Any) -> Optional[asyncio.Task]:
        try:
            task = asyncio.get_running_loop().create_task(coro)
        except RuntimeError:
            coro.close()
            return None
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    def _set_state(self, status: VoiceConnectionStatus) -> None:
        old_state, self.state = self.state, VoiceConnectionState(status)
        self.emit("stateChange", old_state, self.state)


# guild_id -> aktif bağlantı (bir sunucuda aynı anda tek ses bağlantısı)
_connections: Dict[str, VoiceConnection] = {}


def join_voice_channel(
    *,
    channel_id: str,
    guild_id: str,
    adapter_creator: AdapterCreator,
    self_mute: bool = False,
    self_deaf: bool = False,
    **kwargs: Any,
) -> VoiceConnection:
    """Bir ses kanalına katılır ve ``VoiceConnection`` döndürür.

    Örnek::

        connection = join_voice_channel(
            channel_id=voice_channel_id,
            guild_id=interaction.guild_id,
            adapter_creator=client.voice.adapters.get(interaction.guild_id),
        )
    """
    existing = _connections.get(str(guild_id))
    if existing is not None:
        existing.destroy(adapter_available=False)
    connection = VoiceConnection(
        channel_id=channel_id, guild_id=guild_id, adapter_creator=adapter_creator,
        self_mute=self_mute, self_deaf=self_deaf,
    )
    _connections[str(guild_id)] = connection
    return connection


def get_voice_connection(guild_id: str) -> Optional[VoiceConnection]:
    """Sunucudaki aktif ses bağlantısını döndürür."""
    return _connections.get(str(guild_id))


def get_voice_connections() -> Dict[str, VoiceConnection]:
    return dict(_connections)


async def enters_state(
    target: Union[VoiceConnection, "AudioPlayer"],
    status: Any,
    timeout: Optional[float] = None,
) -> Union[VoiceConnection, "AudioPlayer"]:
    """Bağlantı veya çalar belirtilen duruma geçene kadar bekler.

    Örnek: ``await enters_state(connection, VoiceConnectionStatus.Ready, 20)``
    """
    if target.state.status == status:
        return target
    await target.wait_for("stateChange", lambda _old, new: new.status == status, timeout=timeout)
    return target
