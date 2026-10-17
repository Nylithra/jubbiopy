"""Slash komutlarını yöneten ``ApplicationCommandManager``."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Iterable, Optional

from .._utils import CamelCaseCompat, to_json
from ..structures.collection import Collection

if TYPE_CHECKING:
    from ..rest import REST


class ApplicationCommandManager(CamelCaseCompat):
    """Global (``client.application.commands``) veya sunucuya özel
    (``guild.commands``) slash komutlarını yönetir."""

    def __init__(self, rest: "REST", guild_id: Optional[str] = None) -> None:
        self.rest = rest
        self.guild_id = guild_id
        self.cache: Collection[str, Dict[str, Any]] = Collection()

    def _store(self, commands: Optional[Iterable[Dict[str, Any]]]) -> Collection:
        self.cache.clear()
        for cmd in commands or []:
            if isinstance(cmd, dict):
                entry = {**cmd, "id": str(cmd.get("id") or cmd.get("name"))}
                self.cache[entry["id"]] = entry
        return self.cache

    async def set(self, commands: Iterable[Any]) -> Collection:
        """Tüm komutları verilen listeyle değiştirir (toplu üzerine yazma)."""
        resolved = [to_json(c) for c in commands]
        if self.guild_id:
            result = await self.rest.bulk_overwrite_guild_commands(self.guild_id, resolved)
        else:
            result = await self.rest.bulk_overwrite_global_commands(resolved)
        return self._store(result if isinstance(result, list) else [])

    async def create(self, command: Any) -> Dict[str, Any]:
        """Tek bir komut oluşturur."""
        resolved = to_json(command)
        if self.guild_id:
            await self.rest.register_guild_commands(self.guild_id, [resolved])
        else:
            await self.rest.register_global_commands([resolved])
        await self.fetch()
        return self.cache.find(lambda c: c.get("name") == resolved.get("name")) or resolved

    async def fetch(self, command_id: Optional[str] = None) -> Any:
        """Tek bir komutu veya tüm komutları getirir."""
        if command_id:
            if self.guild_id:
                cmd = await self.rest.get_guild_command(self.guild_id, command_id)
            else:
                cmd = await self.rest.get_global_command(command_id)
            entry = {**cmd, "id": str(cmd.get("id") or command_id)}
            self.cache[entry["id"]] = entry
            return entry
        if self.guild_id:
            commands = await self.rest.list_guild_commands(self.guild_id)
        else:
            commands = await self.rest.list_global_commands()
        return self._store(commands if isinstance(commands, list) else [])

    async def delete(self, command_id: str) -> None:
        if self.guild_id:
            await self.rest.delete_guild_command(self.guild_id, command_id)
        else:
            await self.rest.delete_global_command(command_id)
        self.cache.pop(str(command_id), None)

    async def edit(self, command_id: str, data: Any) -> Dict[str, Any]:
        if self.guild_id:
            result = await self.rest.update_guild_command(self.guild_id, command_id, to_json(data))
        else:
            result = await self.rest.update_global_command(command_id, to_json(data))
        entry = {**(result or {}), "id": str((result or {}).get("id") or command_id)}
        self.cache[entry["id"]] = entry
        return entry
