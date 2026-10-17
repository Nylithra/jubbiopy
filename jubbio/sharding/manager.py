"""Çoklu süreç (sharding) desteği.

``ShardingManager`` bot dosyasını her shard için ayrı bir Python sürecinde
çalıştırır. Süreçler, yerel bir TCP soketi üzerinden JSON satırlarıyla
haberleşir (Node.js ``fork`` + ``process.send`` karşılığı).

Örnek (``launcher.py``)::

    import asyncio
    from jubbio import ShardingManager

    async def main():
        manager = ShardingManager("bot.py", total_shards=2, token="...")
        manager.on("shardReady", lambda shard_id: print(f"Shard {shard_id} hazır"))
        await manager.spawn()
        await manager.wait()

    asyncio.run(main())

``bot.py`` içinde normal bir ``Client`` kullanılır; shard bilgisi
(``SHARD_ID``/``SHARD_COUNT``) ortam değişkenlerinden otomatik okunur ve
token ``JUBBIO_TOKEN`` ortam değişkeninde bulunur.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import sys
import uuid
from enum import IntEnum
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Union

from ..events import EventEmitter

if TYPE_CHECKING:
    from ..client import Client


class ShardStatus(IntEnum):
    Ready = 0
    Connecting = 1
    Reconnecting = 2
    Idle = 3
    Nearly = 4
    Disconnected = 5
    WaitingForGuilds = 6
    Identifying = 7
    Resuming = 8


def _encode(message: Any) -> bytes:
    return (json.dumps(message, default=str) + "\n").encode()


def _evaluate(client: "Client", script: str) -> Any:
    """Shard içinde bir ifadeyi değerlendirir. ``client`` ve ``this`` adları kullanılabilir.

    Güvenlik: Bu sadece yerel, kimliği doğrulanmış yönetici sürecinden gelen
    komutlar için kullanılır.
    """
    script = script.strip()
    if script.startswith("this."):
        script = "client." + script[5:]
    return eval(script, {"__builtins__": __builtins__}, {"client": client, "this": client})  # noqa: S307


class Shard(EventEmitter):
    """Tek bir shard süreci."""

    def __init__(self, manager: "ShardingManager", shard_id: int) -> None:
        super().__init__()
        self.manager = manager
        self.id = shard_id
        self.process: Optional[asyncio.subprocess.Process] = None
        self.ready = False
        self.status = ShardStatus.Idle
        self._writer: Optional[asyncio.StreamWriter] = None
        self._pending: Dict[str, asyncio.Future] = {}
        self._exit_task: Optional[asyncio.Task] = None
        self._killing = False

    @property
    def env(self) -> Dict[str, str]:
        return {
            "SHARD_ID": str(self.id),
            "SHARD_COUNT": str(self.manager.total_shards),
            "JUBBIO_TOKEN": self.manager.token or "",
            "JUBBIO_SHARD_IPC": f"127.0.0.1:{self.manager._port}",
            "JUBBIO_SHARD_AUTH": self.manager._auth,
        }

    async def spawn(self, timeout: float = 30.0) -> asyncio.subprocess.Process:
        """Shard sürecini başlatır ve hazır olmasını bekler."""
        if self.process is not None:
            raise RuntimeError(f"Shard {self.id} zaten bir sürece sahip")
        await self.manager._ensure_server()
        self.status = ShardStatus.Connecting
        self._killing = False
        self.process = await asyncio.create_subprocess_exec(
            self.manager.executable, *self.manager.exec_argv, self.manager.file, *self.manager.shard_args,
            env={**os.environ, **self.env},
        )
        self._exit_task = asyncio.get_running_loop().create_task(self._watch_exit(self.process))

        loop = asyncio.get_running_loop()
        result: asyncio.Future = loop.create_future()

        def on_ready() -> None:
            if not result.done():
                result.set_result(self.process)

        def on_death(*_: Any) -> None:
            if not result.done():
                result.set_exception(RuntimeError(f"Shard {self.id} hazır olmadan kapandı"))

        self.once("ready", on_ready)
        self.once("death", on_death)
        try:
            return await asyncio.wait_for(result, timeout)
        except asyncio.TimeoutError:
            raise TimeoutError(f"Shard {self.id} hazır olmak için çok uzun sürdü") from None
        finally:
            self.off("ready", on_ready)
            self.off("death", on_death)

    async def _watch_exit(self, process: asyncio.subprocess.Process) -> None:
        code = await process.wait()
        if process is not self.process:
            return
        self.ready = False
        self.status = ShardStatus.Disconnected
        self.process = None
        self._writer = None
        for future in self._pending.values():
            if not future.done():
                future.set_exception(RuntimeError(f"Shard {self.id} kapandı"))
        self._pending.clear()
        self.emit("death", {"code": code})
        self.manager.emit("shardDeath", self.id, {"code": code})
        if self.manager.respawn and not self._killing:
            try:
                await self.spawn()
            except Exception as exc:  # noqa: BLE001
                self.manager.emit("shardError", self.id, exc)

    def kill(self) -> None:
        self._killing = True
        if self.process is not None and self.process.returncode is None:
            self.process.kill()
        self.process = None
        self._writer = None
        self.status = ShardStatus.Disconnected
        self.ready = False

    async def respawn(self, *, delay: float = 0, timeout: float = 30.0) -> asyncio.subprocess.Process:
        self.kill()
        if delay:
            await asyncio.sleep(delay)
        return await self.spawn(timeout)

    async def send(self, message: Any) -> None:
        """Shard sürecine mesaj gönderir."""
        if self._writer is None:
            raise RuntimeError(f"Shard {self.id} sürecine bağlı değil")
        self._writer.write(_encode({"_message": message}))
        await self._writer.drain()

    async def eval(self, script: str) -> Any:
        """Shard içinde bir Python ifadesi değerlendirir (ör. ``"len(client.guilds)"``)."""
        if self._writer is None:
            raise RuntimeError(f"Shard {self.id} sürecine bağlı değil")
        eval_id = uuid.uuid4().hex
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[eval_id] = future
        self._writer.write(_encode({"_eval": script, "_evalId": eval_id}))
        await self._writer.drain()
        return await future

    async def fetch_client_value(self, prop: str) -> Any:
        return await self.eval(f"client.{prop}")

    async def _handle_message(self, message: Dict[str, Any]) -> None:
        if message.get("_ready"):
            self.ready = True
            self.status = ShardStatus.Ready
            self.emit("ready")
            self.manager.emit("shardReady", self.id)
        elif message.get("_disconnect"):
            self.ready = False
            self.status = ShardStatus.Disconnected
            self.emit("disconnect")
            self.manager.emit("shardDisconnect", self.id)
        elif message.get("_reconnecting"):
            self.ready = False
            self.status = ShardStatus.Reconnecting
            self.emit("reconnecting")
            self.manager.emit("shardReconnecting", self.id)
        elif "_evalId" in message:
            future = self._pending.pop(message["_evalId"], None)
            if future is not None and not future.done():
                if message.get("_error"):
                    future.set_exception(RuntimeError(message["_error"]))
                else:
                    future.set_result(message.get("_result"))
        elif "_broadcastEval" in message:
            # Bir shard tüm shard'larda değerlendirme istiyor. Ayrı görevde çalışmalı:
            # aksi halde bu shard'ın kendi eval yanıtını okuyan döngü kilitlenir.
            task = asyncio.get_running_loop().create_task(self._reply_broadcast_eval(message))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        else:
            payload = message.get("_message", message)
            self.emit("message", payload)
            self.manager.emit("message", self.id, payload)

    async def _reply_broadcast_eval(self, message: Dict[str, Any]) -> None:
        reply: Dict[str, Any] = {"_broadcastEvalId": message.get("_broadcastEvalId")}
        try:
            reply["_results"] = await self.manager.broadcast_eval(message["_broadcastEval"])
        except Exception as exc:  # noqa: BLE001
            reply["_error"] = str(exc)
        if self._writer is not None:
            self._writer.write(_encode(reply))
            await self._writer.drain()


class ShardingManager(EventEmitter):
    """Shard süreçlerini başlatan ve yöneten sınıf.

    Olaylar: ``shardReady``, ``shardDisconnect``, ``shardReconnecting``,
    ``shardDeath``, ``shardError``, ``message``.
    """

    def __init__(
        self,
        file: str,
        *,
        total_shards: Union[int, str] = "auto",
        shard_list: Union[Sequence[int], str, None] = None,
        respawn: bool = True,
        shard_args: Sequence[str] = (),
        exec_argv: Sequence[str] = (),
        token: Optional[str] = None,
        executable: Optional[str] = None,
    ) -> None:
        super().__init__()
        self.file = os.path.abspath(file)
        self.total_shards: Union[int, str] = total_shards
        self.shard_list: List[int] = [] if shard_list in (None, "auto") else list(shard_list)  # type: ignore[arg-type]
        self.mode = "process"
        self.respawn = respawn
        self.shard_args = list(shard_args)
        self.exec_argv = list(exec_argv)
        self.token = token or os.environ.get("JUBBIO_TOKEN")
        self.executable = executable or sys.executable
        self.shards: Dict[int, Shard] = {}
        self._server: Optional[asyncio.base_events.Server] = None
        self._port = 0
        self._auth = secrets.token_hex(16)

    async def _ensure_server(self) -> None:
        if self._server is not None:
            return
        self._server = await asyncio.start_server(self._on_connection, "127.0.0.1", 0)
        self._port = self._server.sockets[0].getsockname()[1]

    async def _on_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        shard: Optional[Shard] = None
        try:
            hello = json.loads(await reader.readline() or b"{}")
            if not secrets.compare_digest(str(hello.get("auth", "")), self._auth):
                writer.close()
                return
            shard = self.shards.get(int(hello.get("shard", -1)))
            if shard is None:
                writer.close()
                return
            shard._writer = writer
            while True:
                line = await reader.readline()
                if not line:
                    break
                try:
                    message = json.loads(line)
                except ValueError:
                    continue
                await shard._handle_message(message)
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            if shard is not None and shard._writer is writer:
                shard._writer = None
            writer.close()

    async def fetch_recommended_shards(self) -> int:
        # API henüz önerilen shard sayısını sunmuyor
        return 1

    def create_shard(self, shard_id: int) -> Shard:
        shard = Shard(self, shard_id)
        self.shards[shard_id] = shard
        return shard

    async def spawn(self, *, amount: Union[int, str, None] = None, delay: float = 5.5, timeout: float = 30.0) -> Dict[int, Shard]:
        """Tüm shard'ları sırayla başlatır (aralarında ``delay`` saniye bekler)."""
        if self.total_shards == "auto" or amount == "auto":
            self.total_shards = await self.fetch_recommended_shards()
        elif isinstance(amount, int):
            self.total_shards = amount
        if not self.shard_list:
            self.shard_list = list(range(int(self.total_shards)))
        for index, shard_id in enumerate(self.shard_list):
            shard = self.create_shard(shard_id)
            await shard.spawn(timeout)
            if index != len(self.shard_list) - 1:
                await asyncio.sleep(delay)
        return self.shards

    async def broadcast(self, message: Any) -> List[None]:
        return list(await asyncio.gather(*(s.send(message) for s in self.shards.values())))

    async def broadcast_eval(self, script: str) -> List[Any]:
        return list(await asyncio.gather(*(s.eval(script) for s in self.shards.values())))

    async def fetch_client_values(self, prop: str) -> List[Any]:
        return await self.broadcast_eval(f"client.{prop}")

    async def respawn_all(self, *, shard_delay: float = 5.5, respawn_delay: float = 0.5, timeout: float = 30.0) -> Dict[int, Shard]:
        for shard in list(self.shards.values()):
            await shard.respawn(delay=respawn_delay, timeout=timeout)
            if shard_delay:
                await asyncio.sleep(shard_delay)
        return self.shards

    async def wait(self) -> None:
        """Tüm shard süreçleri kapanana kadar bekler."""
        while any(s.process is not None for s in self.shards.values()):
            await asyncio.gather(*(s.process.wait() for s in self.shards.values() if s.process is not None))
            await asyncio.sleep(0.1)

    async def close(self) -> None:
        self.respawn = False
        for shard in self.shards.values():
            shard.kill()
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None


class ShardClientUtil:
    """Shard sürecinin içinden yöneticiyle haberleşme yardımcısı (``client.shard``)."""

    def __init__(self, client: "Client") -> None:
        self.client = client
        self.id = int(os.environ.get("SHARD_ID", "0"))
        self.count = int(os.environ.get("SHARD_COUNT", "1"))
        self._address = os.environ.get("JUBBIO_SHARD_IPC", "")
        self._auth = os.environ.get("JUBBIO_SHARD_AUTH", "")
        self._writer: Optional[asyncio.StreamWriter] = None
        self._reader_task: Optional[asyncio.Task] = None
        self._pending: Dict[str, asyncio.Future] = {}
        self._lock: Optional[asyncio.Lock] = None

    @property
    def ids(self) -> List[int]:
        return [self.id]

    async def _connect(self) -> asyncio.StreamWriter:
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            if self._writer is not None:
                return self._writer
            host, _, port = self._address.rpartition(":")
            reader, writer = await asyncio.open_connection(host, int(port))
            writer.write(_encode({"auth": self._auth, "shard": self.id}))
            await writer.drain()
            self._writer = writer
            self._reader_task = asyncio.get_running_loop().create_task(self._read(reader))
            return writer

    async def _read(self, reader: asyncio.StreamReader) -> None:
        while True:
            line = await reader.readline()
            if not line:
                break
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if "_eval" in message:
                task = asyncio.get_running_loop().create_task(self._run_eval(message))
                self.client._tasks.add(task)
                task.add_done_callback(self.client._tasks.discard)
            elif "_broadcastEvalId" in message:
                future = self._pending.pop(message["_broadcastEvalId"], None)
                if future is not None and not future.done():
                    if message.get("_error"):
                        future.set_exception(RuntimeError(message["_error"]))
                    else:
                        future.set_result(message.get("_results"))
            else:
                self.client.emit("shardMessage", message.get("_message", message))

    async def _run_eval(self, message: Dict[str, Any]) -> None:
        reply: Dict[str, Any] = {"_evalId": message.get("_evalId")}
        try:
            result = _evaluate(self.client, message["_eval"])
            if asyncio.iscoroutine(result):
                result = await result
            reply["_result"] = json.loads(json.dumps(result, default=str))
        except Exception as exc:  # noqa: BLE001
            reply["_error"] = f"{type(exc).__name__}: {exc}"
        await self._write(reply)

    async def _write(self, message: Any) -> None:
        writer = await self._connect()
        writer.write(_encode(message))
        await writer.drain()

    async def send(self, message: Any) -> None:
        """Yönetici sürecine mesaj gönderir (yöneticide ``message`` olayı)."""
        await self._write({"_message": message})

    async def broadcast_eval(self, script: str) -> List[Any]:
        """Tüm shard'larda ifade değerlendirir."""
        eval_id = uuid.uuid4().hex
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[eval_id] = future
        await self._write({"_broadcastEval": script, "_broadcastEvalId": eval_id})
        return await future

    async def fetch_client_values(self, prop: str) -> List[Any]:
        return await self.broadcast_eval(f"client.{prop}")

    def ready(self) -> None:
        """Yöneticiye bu shard'ın hazır olduğunu bildirir (Client otomatik çağırır)."""
        task = asyncio.get_running_loop().create_task(self._write({"_ready": True}))
        self.client._tasks.add(task)
        task.add_done_callback(self.client._tasks.discard)

    async def close(self) -> None:
        if self._reader_task is not None:
            self._reader_task.cancel()
        if self._writer is not None:
            self._writer.close()
            self._writer = None

    @staticmethod
    def shard_id_for_guild_id(guild_id: Union[str, int], shard_count: int) -> int:
        return (int(guild_id) >> 22) % shard_count
