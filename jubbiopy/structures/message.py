"""Mesaj yapısı."""

from __future__ import annotations

import time
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Optional

from .._utils import CamelCaseCompat, ms_to_datetime, parse_timestamp
from ._options import MessageOptions, parse_message_options
from .user import User

if TYPE_CHECKING:
    from ..client import Client
    from .guild import Guild
    from .guild_member import GuildMember


def _normalize_embed(embed: Mapping[str, Any]) -> Dict[str, Any]:
    """Backend'den gelen (düz) embed'i iç içe API formatına çevirir."""
    normalized = {key: embed.get(key) for key in ("title", "description", "url", "timestamp", "color", "fields", "author", "footer")}
    for key in ("thumbnail", "image"):
        value = embed.get(key)
        if isinstance(value, str):
            normalized[key] = {"url": value}
        elif isinstance(value, Mapping):
            normalized[key] = dict(value)
    return {k: v for k, v in normalized.items() if v is not None}


class Message(CamelCaseCompat):
    """Bir kanal mesajı."""

    def __init__(self, client: "Client", data: Mapping[str, Any]) -> None:
        self.client = client
        self.id: str = str(data.get("id")) if data.get("id") is not None else ""
        self.channel_id: str = str(data.get("channel_id")) if data.get("channel_id") is not None else ""
        guild_id = data.get("guild_id")
        self.guild_id: Optional[str] = str(guild_id) if guild_id else None
        author = data.get("author")
        self.author = User(author, client) if author else User({"id": "0", "username": "Unknown"}, client)
        self.content: str = data.get("content") or ""
        created = parse_timestamp(data.get("timestamp") or data.get("created_at"))
        self.created_timestamp: float = created if created is not None else time.time() * 1000
        self.edited_timestamp: Optional[float] = parse_timestamp(data.get("edited_timestamp") or data.get("updated_at"))
        self.attachments: List[Dict[str, Any]] = list(data.get("attachments") or [])
        self.embeds: List[Dict[str, Any]] = [_normalize_embed(e) for e in data.get("embeds") or []]
        self.components: List[Dict[str, Any]] = list(data.get("components") or [])
        self.mentions: Dict[str, Any] = dict(data.get("mentions") or {})
        self.user_id = data.get("user_id")
        self.application_id = data.get("application_id")
        self.member: Optional["GuildMember"] = None

    # ----------------------------------------------------------- özellikler
    @property
    def channel(self):
        """Mesajın gönderildiği kanal (``TextChannel``)."""
        from .channel import TextChannel

        cached: Mapping[str, Any] = {}
        if self.guild_id:
            guild = self.client.guilds.get(self.guild_id)
            if guild is not None:
                cached = guild.channels.get(self.channel_id) or {}
        return TextChannel(self.client, {
            "id": self.channel_id,
            "guild_id": self.guild_id,
            "type": 0,
            "name": cached.get("name"),
            "topic": cached.get("topic"),
            "position": cached.get("position"),
            "parent_id": cached.get("parent_id"),
        })

    @property
    def guild(self) -> Optional["Guild"]:
        if not self.guild_id:
            return None
        return self.client.guilds.get(self.guild_id)

    @property
    def created_at(self) -> datetime:
        return ms_to_datetime(self.created_timestamp)  # type: ignore[return-value]

    @property
    def edited_at(self) -> Optional[datetime]:
        return ms_to_datetime(self.edited_timestamp)

    def __str__(self) -> str:
        return self.content

    def __repr__(self) -> str:
        return f"<Message id={self.id} channel_id={self.channel_id} author={self.author!r}>"

    # ------------------------------------------------------------- eylemler
    async def reply(self, content: MessageOptions = None, **kwargs: Any) -> "Message":
        """Bu mesajı yanıtlar.

        Örnek::

            await message.reply("Pong!")
            await message.reply(embeds=[embed], components=[row])
        """
        opts = parse_message_options(content, kwargs)
        data = await self.client.rest.create_message(self.guild_id or "", self.channel_id, {
            "content": opts.get("content"),
            "embeds": opts.get("embeds"),
            "components": opts.get("components"),
            "flags": opts.get("flags"),
            "message_reference": {"message_id": self.id},
        })
        return Message(self.client, data)

    async def edit(self, content: MessageOptions = None, **kwargs: Any) -> "Message":
        """Mesajı düzenler (sadece bot'un kendi mesajları)."""
        opts = parse_message_options(content, kwargs)
        data = await self.client.rest.edit_message(self.guild_id or "", self.channel_id, self.id, {
            "content": opts.get("content"),
            "embeds": opts.get("embeds"),
            "components": opts.get("components"),
        })
        return Message(self.client, data)

    async def delete(self) -> None:
        await self.client.rest.delete_message(self.guild_id or "", self.channel_id, self.id)

    async def react(self, emoji: str) -> None:
        """Tepki ekler. Emoji formatı: ``:isim:``, ``<:isim:id>`` veya ``<a:isim:id>``."""
        await self.client.rest.add_reaction(self.guild_id or "", self.channel_id, self.id, emoji)

    async def pin(self) -> None:
        await self.client.rest.pin_message(self.guild_id or "", self.channel_id, self.id)

    async def unpin(self) -> None:
        await self.client.rest.unpin_message(self.guild_id or "", self.channel_id, self.id)

    def create_message_component_collector(self, **options: Any):
        """Bu mesajdaki buton/menü etkileşimlerini toplayan collector oluşturur."""
        from ..utils.collector import InteractionCollector

        return InteractionCollector(
            self.client, message_id=self.id, channel_id=self.channel_id, guild_id=self.guild_id, **options
        )

    async def await_message_component(self, **options: Any):
        """Bu mesajda tek bir bileşen etkileşimi bekler."""
        from ..errors import CollectorEnded

        options["max"] = 1
        collector = self.create_message_component_collector(**options)
        collected, reason = await collector.wait()
        first = collected.first()
        if first is None:
            raise CollectorEnded(reason or "Etkileşim alınamadı", collected)
        return first
