"""asyncio uyumlu, Node.js EventEmitter benzeri olay yayıcı."""

from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any, Callable, Dict, List, Optional, Set

from ._utils import snake_to_camel

log = logging.getLogger("jubbio")

Listener = Callable[..., Any]


def _normalize_event(name: str) -> str:
    """``on_message_create`` / ``message_create`` / ``messageCreate`` aynı olaydır."""
    if name.startswith("on_"):
        name = name[3:]
    return snake_to_camel(name)


class EventEmitter:
    """Senkron veya ``async`` dinleyicileri destekleyen olay yayıcı.

    Olay isimleri JS kütüphanesiyle aynıdır (``messageCreate``). Python
    tarzı ``message_create`` ya da ``on_message_create`` de kabul edilir.
    """

    def __init__(self) -> None:
        self._listeners: Dict[str, List[Listener]] = {}
        self._once: Set[int] = set()
        self._tasks: Set[asyncio.Task] = set()

    # ------------------------------------------------------------------ kayıt
    def on(self, event: str, listener: Optional[Listener] = None):
        """Dinleyici ekler. Dekoratör olarak da kullanılabilir::

            @client.on("messageCreate")
            async def handler(message): ...
        """
        if listener is None:
            def decorator(fn: Listener) -> Listener:
                self.on(event, fn)
                return fn
            return decorator
        self._listeners.setdefault(_normalize_event(event), []).append(listener)
        return self

    add_listener = on

    def once(self, event: str, listener: Optional[Listener] = None):
        """Sadece bir kez çalışacak dinleyici ekler."""
        if listener is None:
            def decorator(fn: Listener) -> Listener:
                self.once(event, fn)
                return fn
            return decorator
        self.on(event, listener)
        self._once.add(id(listener))
        return self

    def event(self, fn: Listener) -> Listener:
        """discord.py tarzı dekoratör: fonksiyon adı olay adını belirler.

        ``on_ready`` -> ``ready``, ``on_message_create`` -> ``messageCreate``.
        """
        self.on(fn.__name__, fn)
        return fn

    def off(self, event: str, listener: Listener):
        listeners = self._listeners.get(_normalize_event(event))
        if listeners and listener in listeners:
            listeners.remove(listener)
            self._once.discard(id(listener))
        return self

    remove_listener = off

    def remove_all_listeners(self, event: Optional[str] = None):
        if event is None:
            self._listeners.clear()
            self._once.clear()
        else:
            self._listeners.pop(_normalize_event(event), None)
        return self

    def listener_count(self, event: str) -> int:
        return len(self._listeners.get(_normalize_event(event), []))

    # ------------------------------------------------------------------ yayın
    def emit(self, event: str, *args: Any) -> bool:
        """Olayı yayınlar. ``async`` dinleyiciler arka planda görev olarak çalışır."""
        listeners = list(self._listeners.get(_normalize_event(event), []))
        for listener in listeners:
            if id(listener) in self._once:
                self.off(event, listener)
            try:
                result = listener(*args)
            except Exception:  # noqa: BLE001 - dinleyici hatası yayıcıyı düşürmemeli
                log.exception("%r olayı dinleyicisinde hata", event)
                continue
            if inspect.isawaitable(result):
                self._spawn(result, event)
        if not listeners and _normalize_event(event) == "error" and args:
            log.error("İşlenmeyen 'error' olayı: %s", args[0])
        return bool(listeners)

    def _spawn(self, awaitable: Any, event: str) -> None:
        async def runner() -> None:
            try:
                await awaitable
            except Exception:  # noqa: BLE001
                log.exception("%r olayı dinleyicisinde hata", event)

        try:
            task = asyncio.get_running_loop().create_task(runner())
        except RuntimeError:
            # Çalışan event loop yoksa senkron çalıştır
            asyncio.run(runner())
            return
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def wait_for(
        self,
        event: str,
        check: Optional[Callable[..., bool]] = None,
        timeout: Optional[float] = None,
    ) -> Any:
        """Belirtilen olay gerçekleşene kadar bekler (discord.py ``wait_for`` benzeri)."""
        future: asyncio.Future = asyncio.get_running_loop().create_future()

        def listener(*args: Any) -> None:
            if future.done():
                return
            try:
                if check is not None and not check(*args):
                    return
            except Exception as exc:  # noqa: BLE001
                future.set_exception(exc)
                return
            future.set_result(args[0] if len(args) == 1 else args)

        self.on(event, listener)
        try:
            return await asyncio.wait_for(future, timeout)
        finally:
            self.off(event, listener)
