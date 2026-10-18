"""Sunucu (guild) yapısı."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Mapping, Optional

from .._utils import CamelCaseCompat
from .collection import Collection
from .guild_member import GuildMember

if TYPE_CHECKING:
    from ..client import Client


class Guild(CamelCaseCompat):
    """Bir Jubbio sunucusu."""

    def __init__(self, client: "Client", data: Mapping[str, Any]) -> None:
        from ..managers.application_commands import ApplicationCommandManager

        self.client = client
        self.id: str = str(data.get("id"))
        self.name: Optional[str] = data.get("name")
        self.icon: Optional[str] = data.get("icon")
        owner = data.get("owner_id")
        self.owner_id: Optional[str] = str(owner) if owner is not None else None
        self.member_count: int = data.get("member_count") or 0
        self.online_count: int = data.get("online_count") or 0
        self.unavailable: bool = bool(data.get("unavailable") or False)
        self.members: Collection[str, GuildMember] = Collection()
        #: Ham kanal verileri (kanal ID -> dict)
        self.channels: Collection[str, Dict[str, Any]] = Collection()
        self.commands = ApplicationCommandManager(client.rest, self.id)
        for channel in data.get("channels") or []:
            self.channels[str(channel.get("id"))] = channel

    def icon_url(self, **_: Any) -> Optional[str]:
        return self.icon or None

    @property
    def voice_adapter_creator(self):
        """``jubbiopy.voice.join_voice_channel`` için ses adaptörü."""
        return self.client.voice.adapters.get(self.id)

    def get_channel(self, channel_id: str):
        """Önbellekteki kanalı uygun kanal sınıfıyla döndürür."""
        from .channel import create_channel

        data = self.channels.get(str(channel_id))
        if data is None:
            return None
        return create_channel(self.client, {**data, "guild_id": data.get("guild_id") or self.id})

    async def fetch_member(self, user_id: str) -> GuildMember:
        """Üyeyi önce önbellekten, yoksa API'den getirir."""
        user_id = str(user_id)
        cached = self.members.get(user_id)
        if cached is not None:
            return cached
        data = await self.client.rest.get_member(self.id, user_id)
        if not data:
            raise LookupError(f"Üye {user_id}, {self.id} sunucusunda bulunamadı")
        return self._add_member(data)

    async def fetch_members(self, *, limit: Optional[int] = None, cursor: Optional[str] = None) -> Any:
        """Üye listesini sayfalı getirir ve önbelleğe alır."""
        data = await self.client.rest.get_members(self.id, {"limit": limit, "cursor": cursor})
        for member_data in (data or {}).get("members") or []:
            self._add_member(member_data)
        return data

    async def fetch(self) -> "Guild":
        """Güncel sunucu verisini API'den çeker (canlı member_count / online_count)."""
        self._patch(await self.client.rest.get_guild(self.id))
        return self

    def __str__(self) -> str:
        return self.name or ""

    def __repr__(self) -> str:
        return f"<Guild id={self.id} name={self.name!r}>"

    def _patch(self, data: Mapping[str, Any]) -> None:
        if "name" in data:
            self.name = data["name"]
        if "icon" in data:
            self.icon = data["icon"]
        if data.get("owner_id") is not None:
            self.owner_id = str(data["owner_id"])
        if data.get("member_count") is not None:
            self.member_count = data["member_count"]
        if data.get("online_count") is not None:
            self.online_count = data["online_count"]
        if data.get("unavailable") is not None:
            self.unavailable = bool(data["unavailable"])
        for channel in data.get("channels") or []:
            self.channels[str(channel.get("id"))] = channel

    def _add_member(self, data: Mapping[str, Any]) -> GuildMember:
        """Üyeyi önbelleğe ekler. Yeni veride ses durumu yoksa önbellektekini korur."""
        member = GuildMember(self.client, self, data)
        if not (data.get("voice") or {}).get("channel_id"):
            existing = self.members.get(member.id)
            if existing is not None and existing.voice.channel_id:
                member.voice = existing.voice.copy()
        self.members[member.id] = member
        return member
