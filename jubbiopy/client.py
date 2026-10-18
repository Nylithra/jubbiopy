"""Ana ``Client`` sınıfı: gateway (WebSocket) bağlantısı, olaylar ve önbellek."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Sequence, Tuple, Union

import aiohttp

from ._utils import CamelCaseCompat
from .enums import GatewayIntentBits, GatewayOpcodes
from .errors import GatewayError
from .events import EventEmitter
from .managers.application_commands import ApplicationCommandManager
from .rest import REST
from .structures.collection import Collection
from .structures.guild import Guild
from .structures.guild_member import GuildMember
from .structures.interaction import _StubGuild, create_interaction
from .structures.message import Message
from .structures.user import User

log = logging.getLogger("jubbiopy.client")

DEFAULT_GATEWAY_URL = "wss://realtime.jubbio.com/ws/bot"

#: Gateway kapanma kodları: (açıklama, yeniden bağlanılabilir mi)
CLOSE_CODES: Dict[int, Tuple[str, bool]] = {
    4000: ("Bilinmeyen hata (Unknown error)", True),
    4001: ("Bilinmeyen opcode gönderildi (Unknown opcode)", True),
    4002: ("Geçersiz payload gönderildi (Decode error)", True),
    4003: ("Henüz kimlik doğrulaması yapılmadı (Not authenticated)", True),
    4004: ("Geçersiz bot token'ı (Authentication failed)", False),
    4005: ("Zaten kimlik doğrulaması yapılmış (Already authenticated)", True),
    4007: ("Geçersiz sequence numarası (Invalid seq)", True),
    4008: ("Rate limit aşıldı (Rate limited)", True),
    4009: ("Oturum zaman aşımına uğradı (Session timed out)", True),
    4010: ("Geçersiz shard yapılandırması (Invalid shard)", False),
    4011: ("Sharding gerekli (Sharding required)", False),
    4014: ("İzin verilmeyen intent'ler istendi (Disallowed intents)", False),
}

IntentsLike = Union[int, Iterable[Union[int, GatewayIntentBits]]]


class VoiceAdapter:
    """``jubbiopy.voice`` ile gateway arasındaki köprü (adaptör uygulaması)."""

    def __init__(self, client: "Client", guild_id: str) -> None:
        self._client = client
        self._guild_id = guild_id

    @property
    def user_id(self) -> Optional[str]:
        """Bot'un kullanıcı ID'si (ses bağlantısı sadece kendi ses durumunu dinler)."""
        return self._client.user.id if self._client.user else None

    def send_payload(self, payload: Mapping[str, Any]) -> bool:
        return self._client._send_nowait(payload)

    def destroy(self) -> None:
        self._client._voice_state_handlers.pop(self._guild_id, None)
        self._client._voice_server_handlers.pop(self._guild_id, None)

    sendPayload = send_payload


def _make_adapter_creator(client: "Client", guild_id: str) -> Callable[[Any], VoiceAdapter]:
    def adapter_creator(methods: Any) -> VoiceAdapter:
        def method(*names: str) -> Callable[..., Any]:
            for name in names:
                fn = methods.get(name) if isinstance(methods, Mapping) else getattr(methods, name, None)
                if fn is not None:
                    return fn
            raise AttributeError(names[0])

        client._voice_state_handlers[guild_id] = method("on_voice_state_update", "onVoiceStateUpdate")
        client._voice_server_handlers[guild_id] = method("on_voice_server_update", "onVoiceServerUpdate")
        return VoiceAdapter(client, guild_id)

    return adapter_creator


@dataclass
class ClientVoice:
    """Ses adaptörleri: ``client.voice.adapters[guild_id]``."""

    adapters: Dict[str, Callable[[Any], VoiceAdapter]]


@dataclass
class ClientApplication:
    id: Optional[str]
    commands: ApplicationCommandManager


class Client(EventEmitter, CamelCaseCompat):
    """Jubbio bot istemcisi.

    Örnek::

        client = Client(intents=[GatewayIntentBits.Guilds, GatewayIntentBits.GuildMessages,
                                 GatewayIntentBits.MessageContent])

        @client.on("ready")
        async def on_ready(c):
            print(f"✅ {client.user.username} çevrimiçi!")

        @client.on("messageCreate")
        async def on_message(message):
            if message.content == "!ping":
                await message.reply("🏓 Pong!")

        client.run(os.environ["BOT_TOKEN"])
    """

    def __init__(
        self,
        intents: IntentsLike = 0,
        *,
        shards: Optional[Sequence[int]] = None,
        gateway_url: Optional[str] = None,
        api_url: Optional[str] = None,
        max_reconnect_attempts: int = 5,
        ready_timeout: float = 30.0,
        **options: Any,
    ) -> None:
        super().__init__()
        # JS tarzı camelCase seçenekler (gatewayUrl, apiUrl)
        gateway_url = gateway_url or options.pop("gatewayUrl", None)
        api_url = api_url or options.pop("apiUrl", None)
        if options:
            raise TypeError(f"Bilinmeyen Client seçenekleri: {', '.join(options)}")

        self.intents = intents
        self.shards = list(shards) if shards is not None else self._shards_from_env()
        self.gateway_url = gateway_url or DEFAULT_GATEWAY_URL
        self.rest = REST(api_url)
        self.user: Optional[User] = None
        self.application_id: Optional[str] = None
        self.application: Optional[ClientApplication] = None
        self.guilds: Collection[str, Guild] = Collection()
        self.channels: Collection[str, Any] = Collection()
        self.users: Collection[str, User] = Collection()
        self.voice = ClientVoice(adapters={})
        #: WebSocket gecikmesi (ms). Henüz ölçülmediyse -1.
        self.ping: float = -1
        self.ready_at: Optional[datetime] = None
        self.shard = None
        if os.environ.get("JUBBIO_SHARD_IPC"):
            from .sharding.manager import ShardClientUtil

            self.shard = ShardClientUtil(self)

        self.max_reconnect_attempts = max_reconnect_attempts
        self.ready_timeout = ready_timeout
        self._token = ""
        self._session_id: Optional[str] = None
        self._sequence: Optional[int] = None
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._http: Optional[aiohttp.ClientSession] = None
        self._gateway_task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._last_heartbeat_sent = 0.0
        self._reconnect_attempts = 0
        self._reconnect_requested = False
        self._closed = False
        self._ready_future: Optional[asyncio.Future] = None
        self._closed_event: Optional[asyncio.Event] = None
        self._voice_state_handlers: Dict[str, Callable[[Any], Any]] = {}
        self._voice_server_handlers: Dict[str, Callable[[Any], Any]] = {}

    # ================================================================ yardımcı
    @staticmethod
    def _shards_from_env() -> Optional[list]:
        shard_id, shard_count = os.environ.get("SHARD_ID"), os.environ.get("SHARD_COUNT")
        if shard_id is not None and shard_count is not None:
            return [int(shard_id), int(shard_count)]
        return None

    def get_intents_value(self) -> int:
        if isinstance(self.intents, int):
            return int(self.intents)
        value = 0
        for intent in self.intents:
            value |= int(intent)
        return value

    def is_ready(self) -> bool:
        return self.ready_at is not None and self._ws is not None and not self._ws.closed

    @property
    def uptime(self) -> Optional[float]:
        """Hazır olduğundan beri geçen süre (saniye)."""
        if self.ready_at is None:
            return None
        return (datetime.now(timezone.utc) - self.ready_at).total_seconds()

    def _debug(self, message: str) -> None:
        log.debug(message)
        self.emit("debug", message)

    # ================================================================== yaşam
    async def login(self, token: str) -> str:
        """Gateway'e bağlanır ve ``READY`` olayı gelene kadar bekler.

        Bağlantı arka planda çalışmaya devam eder. Hata durumunda
        ``GatewayError`` fırlatılır.
        """
        if not token or not isinstance(token, str):
            raise ValueError("Geçerli bir bot token'ı sağlanmalıdır. Örnek: client.login(os.environ['BOT_TOKEN'])")
        self._token = re.sub(r"^Bot\s+", "", token, flags=re.IGNORECASE)
        self.rest.set_token(self._token)
        self._closed = False
        self._reconnect_attempts = 0
        loop = asyncio.get_running_loop()
        self._ready_future = loop.create_future()
        self._closed_event = asyncio.Event()
        self._gateway_task = loop.create_task(self._run_gateway())
        try:
            await asyncio.wait_for(asyncio.shield(self._ready_future), self.ready_timeout)
        except asyncio.TimeoutError:
            raise GatewayError(
                f"Gateway'e bağlanılamadı: {self.ready_timeout:g} saniye içinde READY event'i alınamadı. "
                "Olası sebepler: gateway sunucusu erişilemez, token geçersiz veya ağ sorunu."
            ) from None
        return self._token

    async def start(self, token: str) -> None:
        """Giriş yapar ve istemci kapanana kadar çalışır."""
        await self.login(token)
        await self.wait_until_closed()

    async def wait_until_closed(self) -> None:
        if self._closed_event is not None:
            await self._closed_event.wait()

    async def wait_until_ready(self) -> None:
        if self._ready_future is None:
            raise RuntimeError("Önce login() çağrılmalı")
        await asyncio.shield(self._ready_future)

    def run(self, token: str, *, log_level: Optional[int] = logging.INFO) -> None:
        """Bot'u başlatır ve Ctrl+C'ye kadar çalıştırır (senkron giriş noktası)."""
        if log_level is not None and not logging.getLogger().handlers:
            logging.basicConfig(level=log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

        async def runner() -> None:
            try:
                await self.start(token)
            finally:
                await self.destroy()

        try:
            asyncio.run(runner())
        except KeyboardInterrupt:
            pass

    async def destroy(self) -> None:
        """Bağlantıyı kapatır ve kaynakları serbest bırakır."""
        self._closed = True
        self.ready_at = None
        self._stop_heartbeat()
        if self._ws is not None and not self._ws.closed:
            await self._ws.close(code=1000)
        self._ws = None
        if self._gateway_task is not None and self._gateway_task is not asyncio.current_task():
            self._gateway_task.cancel()
            try:
                await self._gateway_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._gateway_task = None
        if self._http is not None and not self._http.closed:
            await self._http.close()
        self._http = None
        await self.rest.close()
        if self.shard is not None:
            await self.shard.close()
        if self._closed_event is not None:
            self._closed_event.set()
        self.remove_all_listeners()

    # =============================================================== gateway
    def _fail(self, error: Exception) -> None:
        if self._ready_future is not None and not self._ready_future.done():
            self._ready_future.set_exception(error)
            self._ready_future.exception()  # "Future exception was never retrieved" uyarısını engelle
        self.emit("error", error)

    async def _run_gateway(self) -> None:
        if self._http is None or self._http.closed:
            self._http = aiohttp.ClientSession()
        try:
            while not self._closed:
                code: Optional[int] = None
                reason = ""
                try:
                    self._ws = await self._http.ws_connect(self.gateway_url, max_msg_size=0, autoping=True)
                except (aiohttp.ClientError, OSError) as exc:
                    self._debug(f"WebSocket hatası: {exc}")
                    code = 1006
                else:
                    self._debug("WebSocket bağlantısı açıldı")
                    self._reconnect_attempts = 0
                    await self._read_loop(self._ws)
                    code = self._ws.close_code
                    exc = self._ws.exception()
                    reason = str(exc) if exc else ""
                self._stop_heartbeat()
                if self._closed:
                    break

                info = CLOSE_CODES.get(code or 0)
                if info:
                    self._debug(f"Gateway bağlantısı kapandı [{code}]: {info[0]}{' - ' + reason if reason else ''}")
                else:
                    self._debug(f"WebSocket kapandı: {code} - {reason}")
                self.emit("gatewayClose", code, reason)

                if info and not info[1]:
                    self._debug(f"Kod {code} yeniden bağlanılamaz, bağlantı sonlandırılıyor.")
                    self._fail(GatewayError(
                        f"Gateway bağlantısı reddedildi [{code}]: {info[0]}{' - ' + reason if reason else ''}", code
                    ))
                    break

                if self._reconnect_requested:
                    self._reconnect_requested = False
                    await asyncio.sleep(1)
                    continue

                if code == 1000:
                    break

                self._reconnect_attempts += 1
                if self._reconnect_attempts > self.max_reconnect_attempts:
                    self._debug(f"Maksimum yeniden bağlanma denemesi aşıldı ({self.max_reconnect_attempts})")
                    self._fail(GatewayError(
                        f"Gateway bağlantısı {self.max_reconnect_attempts} denemeden sonra kurulamadı. "
                        f"Son kapanma kodu: {code}", code
                    ))
                    break
                delay = min(2 ** (self._reconnect_attempts - 1), 30)
                self._debug(
                    f"Yeniden bağlanılıyor (deneme {self._reconnect_attempts}/{self.max_reconnect_attempts}), {delay} sn sonra..."
                )
                await asyncio.sleep(delay)
        finally:
            self._stop_heartbeat()
            if self._closed_event is not None:
                self._closed_event.set()

    async def _read_loop(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                self._handle_message(msg.data)
            elif msg.type == aiohttp.WSMsgType.BINARY:
                self._handle_message(msg.data.decode("utf-8", errors="replace"))
            elif msg.type == aiohttp.WSMsgType.ERROR:
                self._debug(f"WebSocket hatası: {ws.exception()}")
                break

    def _handle_message(self, data: str) -> None:
        # Tek frame içinde birden fazla mesaj gelebilir
        for line in data.split("\n"):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except ValueError:
                self._debug(f"Mesaj ayrıştırılamadı: {line}")
                continue
            try:
                self._handle_payload(payload)
            except Exception:  # noqa: BLE001 - tek bir olay gateway döngüsünü düşürmemeli
                log.exception("Gateway payload işlenirken hata: %s", payload.get("t"))

    def _handle_payload(self, payload: Mapping[str, Any]) -> None:
        if payload.get("s"):
            self._sequence = payload["s"]
        op = payload.get("op")
        data = payload.get("d")

        if op == GatewayOpcodes.Hello:
            interval = (data or {}).get("heartbeat_interval", 41250)
            self._debug(f"Hello alındı, heartbeat aralığı: {interval}ms")
            self._start_heartbeat(interval / 1000)
            self._identify()
        elif op == GatewayOpcodes.Dispatch:
            self._handle_dispatch(payload.get("t") or "", data)
        elif op == GatewayOpcodes.HeartbeatAck:
            if self._last_heartbeat_sent > 0:
                self.ping = round((time.monotonic() - self._last_heartbeat_sent) * 1000)
            self._debug(f"Heartbeat onaylandı (ping: {self.ping}ms)")
        elif op == GatewayOpcodes.InvalidSession:
            self._debug("Geçersiz oturum, yeniden kimlik doğrulanıyor...")
            if isinstance(data, Mapping) and data.get("code") and data.get("message"):
                self._debug(f"Sunucu hatası [{data['code']}]: {data['message']}")
                info = CLOSE_CODES.get(int(data["code"]))
                if info and not info[1]:
                    self._fail(GatewayError(f"Gateway hatası [{data['code']}]: {info[0]}", int(data["code"])))
                    return
            asyncio.get_running_loop().call_later(5, self._identify)
        elif op == GatewayOpcodes.Reconnect:
            self._debug("Yeniden bağlanma istendi")
            self._reconnect_requested = True
            if self._ws is not None:
                asyncio.get_running_loop().create_task(self._ws.close())

    def _identify(self) -> None:
        self._send_nowait({
            "op": int(GatewayOpcodes.Identify),
            "d": {
                "token": f"Bot {self._token}",
                "intents": self.get_intents_value(),
                "shard": list(self.shards) if self.shards else [0, 1],
            },
        })

    def _start_heartbeat(self, interval: float) -> None:
        self._stop_heartbeat()

        async def beat() -> None:
            while True:
                await asyncio.sleep(interval)
                self._last_heartbeat_sent = time.monotonic()
                await self.send({"op": int(GatewayOpcodes.Heartbeat), "d": self._sequence})

        self._heartbeat_task = asyncio.get_running_loop().create_task(beat())

    def _stop_heartbeat(self) -> None:
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            self._heartbeat_task = None

    async def send(self, payload: Mapping[str, Any]) -> bool:
        """Gateway'e ham payload gönderir."""
        ws = self._ws
        if ws is None or ws.closed:
            return False
        try:
            await ws.send_str(json.dumps(payload, default=str))
        except (ConnectionError, RuntimeError, aiohttp.ClientError) as exc:
            self._debug(f"Gateway'e gönderilemedi: {exc}")
            return False
        return True

    def _send_nowait(self, payload: Mapping[str, Any]) -> bool:
        if self._ws is None or self._ws.closed:
            return False
        task = asyncio.get_running_loop().create_task(self.send(payload))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return True

    # =============================================================== olaylar
    _SIMPLE_EVENTS = {
        "MESSAGE_UPDATE": "messageUpdate",
        "MESSAGE_DELETE": "messageDelete",
        "MESSAGE_DELETE_BULK": "messageDeleteBulk",
        "MESSAGE_REACTION_ADD": "messageReactionAdd",
        "MESSAGE_REACTION_REMOVE": "messageReactionRemove",
        "GUILD_ROLE_CREATE": "roleCreate",
        "GUILD_ROLE_UPDATE": "roleUpdate",
        "GUILD_ROLE_DELETE": "roleDelete",
        "GUILD_BAN_ADD": "guildBanAdd",
        "GUILD_BAN_REMOVE": "guildBanRemove",
        "INVITE_CREATE": "inviteCreate",
        "INVITE_DELETE": "inviteDelete",
        "TYPING_START": "typingStart",
    }

    def _handle_dispatch(self, event: str, data: Any) -> None:
        self._debug(f"Dispatch: {event}")
        data = data if data is not None else {}
        handler = getattr(self, f"_on_{event.lower()}", None)
        if handler is not None:
            handler(data)
        elif event in self._SIMPLE_EVENTS:
            self.emit(self._SIMPLE_EVENTS[event], data)
        else:
            # İşlenmeyen olaylar ham olarak yayınlanır
            self.emit("raw", {"t": event, "d": data})

    def _on_ready(self, data: Mapping[str, Any]) -> None:
        self._session_id = data.get("session_id")
        self.user = User(data.get("user") or {}, self)
        app_id = (data.get("application") or {}).get("id")
        self.application_id = str(app_id) if app_id else None
        if self.application_id:
            self.rest.set_application_id(self.application_id)
        self.application = ClientApplication(self.application_id, ApplicationCommandManager(self.rest))
        for guild_data in data.get("guilds") or []:
            guild = Guild(self, guild_data)
            self.guilds[guild.id] = guild
        for guild_id in self.guilds:
            self._create_voice_adapter(guild_id)
        self.ready_at = datetime.now(timezone.utc)
        log.info("✅ Bot hazır! User: %s (%s), App: %s", self.user.username, self.user.id, self.application_id)
        if self._ready_future is not None and not self._ready_future.done():
            self._ready_future.set_result(self)
        self.emit("ready", self)
        if self.shard is not None:
            self.shard.ready()

    def _create_voice_adapter(self, guild_id: str) -> None:
        self.voice.adapters[guild_id] = _make_adapter_creator(self, guild_id)

    def _on_guild_create(self, data: Mapping[str, Any]) -> None:
        guild_id = str(data.get("id"))
        guild = self.guilds.get(guild_id)
        if guild is not None:
            guild._patch(data)
        else:
            guild = Guild(self, data)
            self.guilds[guild_id] = guild
            self._create_voice_adapter(guild_id)
        self.emit("guildCreate", guild)

    def _on_guild_update(self, data: Mapping[str, Any]) -> None:
        guild = self.guilds.get(str(data.get("id")))
        if guild is not None:
            guild._patch(data)
            self.emit("guildUpdate", guild)

    def _on_guild_delete(self, data: Mapping[str, Any]) -> None:
        guild_id = str(data.get("id"))
        guild = self.guilds.pop(guild_id, None)
        if guild is not None:
            self.voice.adapters.pop(guild_id, None)
            self.emit("guildDelete", guild)

    def _update_channel_cache(self, data: Mapping[str, Any], delete: bool = False) -> None:
        guild_id = data.get("guild_id")
        channel_id = data.get("id") or data.get("channel_id")
        if guild_id and channel_id:
            guild = self.guilds.get(str(guild_id))
            if guild is not None:
                if delete:
                    guild.channels.pop(str(channel_id), None)
                else:
                    guild.channels[str(channel_id)] = dict(data)

    def _on_channel_create(self, data: Mapping[str, Any]) -> None:
        self._update_channel_cache(data)
        self.emit("channelCreate", data)

    def _on_channel_update(self, data: Mapping[str, Any]) -> None:
        self._update_channel_cache(data)
        self.emit("channelUpdate", data)

    def _on_channel_delete(self, data: Mapping[str, Any]) -> None:
        self._update_channel_cache(data, delete=True)
        self.emit("channelDelete", data)

    def _on_guild_member_add(self, data: Mapping[str, Any]) -> None:
        guild = self.guilds.get(str(data.get("guild_id")))
        if guild is not None and data.get("user"):
            self.emit("guildMemberAdd", guild._add_member(data))
        else:
            self.emit("guildMemberAdd", data)

    @staticmethod
    def _member_user_id(data: Mapping[str, Any]) -> Optional[str]:
        raw = (data.get("user") or {}).get("id") or data.get("user_id")
        return str(raw) if raw else None

    def _on_guild_member_update(self, data: Mapping[str, Any]) -> None:
        guild = self.guilds.get(str(data.get("guild_id")))
        user_id = self._member_user_id(data)
        existing = guild.members.get(user_id) if guild is not None and user_id else None
        if existing is not None:
            existing._patch(data)
            self.emit("guildMemberUpdate", existing)
        else:
            self.emit("guildMemberUpdate", data)

    def _on_guild_member_remove(self, data: Mapping[str, Any]) -> None:
        guild = self.guilds.get(str(data.get("guild_id")))
        user_id = self._member_user_id(data)
        if guild is not None and user_id:
            member = guild.members.pop(user_id, None)
            self.emit("guildMemberRemove", member or data)
        else:
            self.emit("guildMemberRemove", data)

    def _on_presence_update(self, data: Mapping[str, Any]) -> None:
        guild = self.guilds.get(str(data.get("guild_id"))) if data.get("guild_id") else None
        if guild is not None:
            status = data.get("status")
            if status == "offline":
                guild.online_count = max(0, guild.online_count - 1)
            elif status in ("online", "idle", "dnd"):
                guild.online_count += 1
        self.emit("presenceUpdate", data)

    def _on_message_create(self, data: Dict[str, Any]) -> None:
        # Backend user_id'yi ayrı gönderiyor; uyumluluk için author.id'ye eşle
        author = data.get("author")
        if data.get("user_id") and isinstance(author, dict) and not author.get("id"):
            author["id"] = data["user_id"]
        if author:
            user = User(author, self)
            self.users[user.id] = user
            self.rest.cache_user(author)

        message = Message(self, data)
        if self.user is not None and message.author.id == self.user.id:
            message.author.bot = True

        if message.guild_id:
            guild = self.guilds.get(message.guild_id)
            member_data = data.get("member")
            if member_data:
                member_data = {**member_data, "user": author}
                if guild is not None:
                    # _add_member önbellekteki ses durumunu korur
                    message.member = guild._add_member(member_data)
                else:
                    message.member = GuildMember(self, _StubGuild(message.guild_id), member_data)  # type: ignore[arg-type]
            elif guild is not None:
                message.member = guild.members.get(message.author.id)

        self.emit("messageCreate", message)

    def _on_interaction_create(self, data: Mapping[str, Any]) -> None:
        user_data = (data.get("member") or {}).get("user") or data.get("user")
        if user_data:
            user = User(user_data, self)
            self.users[user.id] = user
            self.rest.cache_user(user_data)
        interaction = create_interaction(self, data)
        self._debug(f"Etkileşim: {type(interaction).__name__} custom_id={getattr(interaction, 'custom_id', None)}")
        self.emit("interactionCreate", interaction)

    def _on_voice_state_update(self, data: Mapping[str, Any]) -> None:
        guild_id = data.get("guild_id")
        user_id = data.get("user_id")
        if guild_id and user_id:
            guild = self.guilds.get(str(guild_id))
            if guild is not None:
                member = guild.members.get(str(user_id))
                if member is None and data.get("user"):
                    # Üye henüz önbellekte yok — ses durumundan minimal kayıt oluştur
                    member = guild._add_member({
                        "user": data["user"],
                        "roles": [],
                        "joined_at": datetime.now(timezone.utc).isoformat(),
                    })
                if member is not None:
                    from .structures.guild_member import voice_state_from

                    member.voice = voice_state_from(data)
        handler = self._voice_state_handlers.get(str(guild_id))
        if handler is not None:
            handler(data)
        self.emit("voiceStateUpdate", data)

    def _on_voice_server_update(self, data: Mapping[str, Any]) -> None:
        handler = self._voice_server_handlers.get(str(data.get("guild_id")))
        if handler is not None:
            handler({"token": data.get("token"), "endpoint": data.get("endpoint"), "room": data.get("room")})
        self.emit("voiceServerUpdate", data)

    # =========================================================== kolaylıklar
    async def fetch_user(self, user_id: str) -> User:
        user = User(await self.rest.get_user(str(user_id)), self)
        self.users[user.id] = user
        return user

    async def fetch_guild(self, guild_id: str) -> Guild:
        guild = self.guilds.get(str(guild_id))
        if guild is None:
            guild = Guild(self, await self.rest.get_guild(str(guild_id)))
            self.guilds[guild.id] = guild
            return guild
        return await guild.fetch()

    def get_channel(self, channel_id: str):
        """Önbellekteki sunucularda kanalı arar."""
        for guild in self.guilds.values():
            channel = guild.get_channel(str(channel_id))
            if channel is not None:
                return channel
        return None

    def __repr__(self) -> str:
        return f"<Client user={self.user!r} guilds={len(self.guilds)}>"


__all__ = ["Client", "GatewayIntentBits", "CLOSE_CODES"]
