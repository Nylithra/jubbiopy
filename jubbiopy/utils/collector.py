"""Mesaj, tepki ve etkileşim collector'ları (Discord.js API uyumlu).

Süreler (``time``, ``idle``) **saniye** cinsindendir.
"""

from __future__ import annotations

import asyncio
import inspect
from typing import TYPE_CHECKING, Any, Callable, Iterable, Optional, Tuple, Union

from ..errors import CollectorEnded
from ..events import EventEmitter
from ..structures.collection import Collection

if TYPE_CHECKING:
    from ..client import Client

Filter = Callable[..., Any]


def _get(item: Any, *names: str) -> Any:
    for name in names:
        value = item.get(name) if isinstance(item, dict) else getattr(item, name, None)
        if value is not None:
            return value
    return None


class Collector(EventEmitter):
    """Collector temel sınıfı.

    Olaylar: ``collect(item)``, ``dispose(item)``, ``end(collected, reason)``.
    """

    def __init__(
        self,
        client: "Client",
        *,
        filter: Optional[Filter] = None,  # noqa: A002 - JS API ile aynı isim
        time: Optional[float] = None,
        idle: Optional[float] = None,
        max: Optional[int] = None,  # noqa: A002
        max_processed: Optional[int] = None,
        dispose: bool = False,
    ) -> None:
        super().__init__()
        self.client = client
        self.filter: Filter = filter or (lambda *_: True)
        self.time = time
        self.idle = idle
        self.max = max
        self.max_processed = max_processed
        self.dispose_enabled = dispose
        self.collected: Collection[Any, Any] = Collection()
        self.ended = False
        self.end_reason: Optional[str] = None
        self._processed = 0
        self._loop = asyncio.get_running_loop()
        self._end_future: asyncio.Future = self._loop.create_future()
        self._timeout: Optional[asyncio.TimerHandle] = None
        self._idle_timeout: Optional[asyncio.TimerHandle] = None
        self._start_timers(time, idle)

    def _start_timers(self, time: Optional[float], idle: Optional[float]) -> None:
        if time:
            self._timeout = self._loop.call_later(time, self.stop, "time")
        if idle:
            self._idle_timeout = self._loop.call_later(idle, self.stop, "idle")

    def _clear_timers(self) -> None:
        for handle in (self._timeout, self._idle_timeout):
            if handle is not None:
                handle.cancel()
        self._timeout = self._idle_timeout = None

    # Alt sınıflar uygular: öğenin anahtarını döndürür
    def collect(self, item: Any) -> Any:  # pragma: no cover - soyut
        raise NotImplementedError

    def dispose(self, item: Any) -> Any:
        return self.collect(item)

    async def handle_collect(self, item: Any) -> None:
        if self.ended:
            return
        self._processed += 1
        result = self.filter(item, self.collected)
        if inspect.isawaitable(result):
            result = await result
        if not result or self.ended:
            return
        key = self.collect(item)
        if key is None:
            return
        self.collected[key] = item
        self.emit("collect", item)

        if self._idle_timeout is not None:
            self._idle_timeout.cancel()
            self._idle_timeout = self._loop.call_later(self.idle, self.stop, "idle")  # type: ignore[arg-type]
        if self.max and len(self.collected) >= self.max:
            self.stop("limit")
        elif self.max_processed and self._processed >= self.max_processed:
            self.stop("processedLimit")

    def handle_dispose(self, item: Any) -> None:
        if not self.dispose_enabled:
            return
        key = self.dispose(item)
        if key is not None and key in self.collected:
            del self.collected[key]
            self.emit("dispose", item)

    def _schedule(self, item: Any) -> None:
        task = self._loop.create_task(self.handle_collect(item))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def stop(self, reason: str = "user") -> None:
        """Collector'ı durdurur ve ``end`` olayını yayınlar."""
        if self.ended:
            return
        self.ended = True
        self.end_reason = reason
        self._clear_timers()
        self._cleanup()
        self.emit("end", self.collected, reason)
        if not self._end_future.done():
            self._end_future.set_result((self.collected, reason))

    def _cleanup(self) -> None:
        """Alt sınıflar client dinleyicilerini burada kaldırır."""

    def reset_timer(self, *, time: Optional[float] = None, idle: Optional[float] = None) -> None:
        self._clear_timers()
        self._start_timers(time or self.time, idle or self.idle)

    def check_end(self) -> bool:
        if self.end_reason:
            self.stop(self.end_reason)
            return True
        return False

    async def wait(self) -> Tuple[Collection, Optional[str]]:
        """Collector bitene kadar bekler ve ``(collected, reason)`` döndürür."""
        return await asyncio.shield(self._end_future)

    async def next(self) -> Any:
        """Bir sonraki toplanan öğeyi bekler."""
        if self.ended:
            raise CollectorEnded("Collector sona erdi", self.collected)
        item_future: asyncio.Future = self._loop.create_future()

        def on_collect(item: Any) -> None:
            if not item_future.done():
                item_future.set_result(item)

        def on_end(collected: Any, reason: str) -> None:
            if not item_future.done():
                item_future.set_exception(CollectorEnded(reason, collected))

        self.on("collect", on_collect)
        self.on("end", on_end)
        try:
            return await item_future
        finally:
            self.off("collect", on_collect)
            self.off("end", on_end)

    def __aiter__(self):
        return self

    async def __anext__(self) -> Any:
        try:
            return await self.next()
        except CollectorEnded:
            raise StopAsyncIteration from None


class MessageCollector(Collector):
    """Bir kanaldaki mesajları toplar (bot'un kendi mesajları hariç)."""

    def __init__(self, client: "Client", channel_id: str, **options: Any) -> None:
        super().__init__(client, **options)
        self.channel_id = str(channel_id)
        bot_id = client.user.id if client.user else None

        def handler(message: Any) -> None:
            if str(_get(message, "channel_id", "channelId")) != self.channel_id:
                return
            author = _get(message, "author")
            author_id = _get(author, "id") if author is not None else _get(message, "author_id")
            if bot_id and str(author_id) == str(bot_id):
                return
            if _get(message, "application_id", "applicationId"):
                return
            self._schedule(message)

        self._handler = handler
        client.on("messageCreate", handler)

    def _cleanup(self) -> None:
        self.client.off("messageCreate", self._handler)

    def collect(self, message: Any) -> Any:
        return _get(message, "id")


class InteractionCollector(Collector):
    """Etkileşimleri (buton, seçim menüsü vb.) toplar."""

    def __init__(
        self,
        client: "Client",
        *,
        channel_id: Optional[str] = None,
        guild_id: Optional[str] = None,
        message_id: Optional[str] = None,
        interaction_type: Union[int, Iterable[int], None] = None,
        component_type: Union[int, Iterable[int], None] = None,
        **options: Any,
    ) -> None:
        super().__init__(client, **options)
        self.channel_id = channel_id
        self.guild_id = guild_id
        self.message_id = message_id
        self.interaction_types = self._as_set(interaction_type)
        self.component_types = self._as_set(component_type)

        def handler(interaction: Any) -> None:
            if self.channel_id and interaction.channel_id != str(self.channel_id):
                return
            if self.guild_id and interaction.guild_id != str(self.guild_id):
                return
            message = getattr(interaction, "message", None)
            if self.message_id and (message is None or message.id != str(self.message_id)):
                return
            if self.interaction_types and int(interaction.type) not in self.interaction_types:
                return
            ctype = getattr(interaction, "component_type", None)
            if self.component_types and ctype and int(ctype) not in self.component_types:
                return
            self._schedule(interaction)

        self._handler = handler
        client.on("interactionCreate", handler)

    @staticmethod
    def _as_set(value: Union[int, Iterable[int], None]) -> Optional[set]:
        if value is None:
            return None
        if isinstance(value, int):
            return {int(value)}
        return {int(v) for v in value}

    def _cleanup(self) -> None:
        self.client.off("interactionCreate", self._handler)

    def collect(self, interaction: Any) -> Any:
        return interaction.id


class ReactionCollector(Collector):
    """Bir mesaja eklenen tepkileri toplar (``messageReactionAdd`` olayı)."""

    def __init__(self, client: "Client", message_id: str, **options: Any) -> None:
        super().__init__(client, **options)
        self.message_id = str(message_id)

        def handler(reaction: Any) -> None:
            if str(_get(reaction, "message_id", "messageId")) == self.message_id:
                self._schedule(reaction)

        def remove_handler(reaction: Any) -> None:
            if str(_get(reaction, "message_id", "messageId")) == self.message_id:
                self.handle_dispose(reaction)

        self._handler = handler
        self._remove_handler = remove_handler
        client.on("messageReactionAdd", handler)
        client.on("messageReactionRemove", remove_handler)

    def _cleanup(self) -> None:
        self.client.off("messageReactionAdd", self._handler)
        self.client.off("messageReactionRemove", self._remove_handler)

    def collect(self, reaction: Any) -> Any:
        emoji = _get(reaction, "emoji") or {}
        return _get(emoji, "id", "name")


async def await_messages(client: "Client", channel_id: str, **options: Any) -> Collection:
    """Kanalda mesaj bekler. ``max`` sayısına ulaşılamazsa ``CollectorEnded`` fırlatır."""
    collector = MessageCollector(client, channel_id, **options)
    collected, reason = await collector.wait()
    if options.get("max") and len(collected) < options["max"]:
        raise CollectorEnded(reason, collected)
    return collected


async def await_reactions(client: "Client", message_id: str, **options: Any) -> Collection:
    """Mesajda tepki bekler. ``max`` sayısına ulaşılamazsa ``CollectorEnded`` fırlatır."""
    collector = ReactionCollector(client, message_id, **options)
    collected, reason = await collector.wait()
    if options.get("max") and len(collected) < options["max"]:
        raise CollectorEnded(reason, collected)
    return collected
