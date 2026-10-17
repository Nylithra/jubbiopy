"""Kanal yapıları."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Iterable, List, Mapping, Optional, Union

from .._utils import CamelCaseCompat
from ..enums import ChannelType
from ._options import MessageOptions, first_file, parse_message_options
from .collection import Collection
from .message import Message

if TYPE_CHECKING:
    from ..client import Client

# Discord ile uyumlu epoch (bulk_delete 14 gün filtresi JS ile aynı)
_DISCORD_EPOCH_MS = 1420070400000


class BaseChannel(CamelCaseCompat):
    """Tüm kanalların temel sınıfı."""

    def __init__(self, client: "Client", data: Mapping[str, Any]) -> None:
        self.client = client
        self.id: str = str(data.get("id"))
        raw_type = data.get("type", 0)
        try:
            self.type: Union[ChannelType, int] = ChannelType(raw_type)
        except ValueError:
            self.type = raw_type

    def is_text_based(self) -> bool:
        return self.type in (ChannelType.GuildText, ChannelType.DM, ChannelType.GroupDM, ChannelType.GuildAnnouncement)

    def is_voice_based(self) -> bool:
        return self.type in (ChannelType.GuildVoice, ChannelType.GuildStageVoice)

    @property
    def mention(self) -> str:
        return f"<#{self.id}>"

    def __str__(self) -> str:
        return self.mention

    def __repr__(self) -> str:
        return f"<{type(self).__name__} id={self.id}>"


class TextChannel(BaseChannel):
    """Metin kanalı."""

    def __init__(self, client: "Client", data: Mapping[str, Any]) -> None:
        super().__init__(client, data)
        guild_id = data.get("guild_id")
        self.guild_id: Optional[str] = str(guild_id) if guild_id else None
        self.name: Optional[str] = data.get("name")
        self.topic: Optional[str] = data.get("topic")
        self.position: Optional[int] = data.get("position")
        parent = data.get("parent_id")
        self.parent_id: Optional[str] = str(parent) if parent is not None else None

    async def send(self, content: MessageOptions = None, **kwargs: Any) -> Message:
        """Bu kanala mesaj gönderir. ``files`` verilirse dosya yüklenir (şimdilik tek dosya)."""
        opts = parse_message_options(content, kwargs)
        file = first_file(opts)
        if file is not None and self.guild_id:
            data = await self.client.rest.create_message_with_file(self.guild_id, self.id, {
                "content": opts.get("content"),
                "embeds": opts.get("embeds"),
                "components": opts.get("components"),
                "file": file,
            })
            return Message(self.client, data)
        data = await self.client.rest.create_message(self.guild_id or "", self.id, {
            "content": opts.get("content"),
            "embeds": opts.get("embeds"),
            "components": opts.get("components"),
            "flags": opts.get("flags"),
        })
        return Message(self.client, data)

    def create_message_collector(self, **options: Any):
        from ..utils.collector import MessageCollector

        return MessageCollector(self.client, self.id, **options)

    async def await_messages(self, **options: Any) -> Collection:
        """Bu kanalda mesaj bekler. ``errors=["time"]`` verilirse o sebeple bitince hata fırlatır."""
        from ..errors import CollectorEnded

        errors = options.pop("errors", None) or []
        collector = self.create_message_collector(**options)
        collected, reason = await collector.wait()
        if reason in errors:
            raise CollectorEnded(reason, collected)
        return collected

    async def bulk_delete(self, messages: Union[int, Iterable[str], Collection], filter_old: bool = True) -> Collection:
        """Toplu mesaj siler. Sayı verilirse önce o kadar mesaj çekilir."""
        if isinstance(messages, int):
            fetched = await self.client.rest.get_messages(self.guild_id or "", self.id, {"limit": messages})
            message_ids: List[str] = [str(m.get("id")) for m in fetched]
        elif isinstance(messages, Collection):
            message_ids = [str(k) for k in messages.keys()]
        else:
            message_ids = [str(getattr(m, "id", m)) for m in messages]

        if filter_old:
            two_weeks_ago = time.time() * 1000 - 14 * 24 * 60 * 60 * 1000

            def recent(snowflake: str) -> bool:
                try:
                    return (int(snowflake) >> 22) + _DISCORD_EPOCH_MS > two_weeks_ago
                except ValueError:
                    return True

            message_ids = [m for m in message_ids if recent(m)]

        if len(message_ids) == 1:
            await self.client.rest.delete_message(self.guild_id or "", self.id, message_ids[0])
        elif message_ids:
            await self.client.rest.bulk_delete_messages(self.guild_id or "", self.id, message_ids)
        return Collection()


class VoiceChannel(BaseChannel):
    """Ses kanalı."""

    def __init__(self, client: "Client", data: Mapping[str, Any]) -> None:
        super().__init__(client, data)
        guild_id = data.get("guild_id")
        self.guild_id: Optional[str] = str(guild_id) if guild_id else None
        self.name: Optional[str] = data.get("name")
        self.position: Optional[int] = data.get("position")
        parent = data.get("parent_id")
        self.parent_id: Optional[str] = str(parent) if parent is not None else None
        self.user_limit: Optional[int] = data.get("user_limit")
        self.bitrate: Optional[int] = data.get("bitrate")

    @property
    def joinable(self) -> bool:
        """Bot'un bu ses kanalına katılıp katılamayacağı."""
        if not self.guild_id or self.client.user is None:
            return False
        guild = self.client.guilds.get(self.guild_id)
        if guild is None:
            return False
        me = guild.members.get(str(self.client.user.id))
        if me is None:
            return True  # Önbellekte yoksa iyimser davran; sunucu izin vermezse reddeder
        return me.permissions.has("Connect")


class DMChannel(BaseChannel):
    """Doğrudan mesaj kanalı."""

    def __init__(self, client: "Client", data: Mapping[str, Any]) -> None:
        super().__init__(client, data)
        self.recipient_id: Optional[str] = data.get("recipient_id")

    async def send(self, content: MessageOptions = None, **kwargs: Any) -> Message:
        opts = parse_message_options(content, kwargs)
        data = await self.client.rest.create_dm_message_to_channel(self.id, {
            "content": opts.get("content"),
            "embeds": opts.get("embeds"),
            "components": opts.get("components"),
        })
        return Message(self.client, data)


def create_channel(client: "Client", data: Mapping[str, Any]) -> BaseChannel:
    """Kanal tipine göre uygun sınıfı oluşturur."""
    channel_type = data.get("type")
    if channel_type in (ChannelType.GuildText, ChannelType.GuildAnnouncement):
        return TextChannel(client, data)
    if channel_type in (ChannelType.GuildVoice, ChannelType.GuildStageVoice):
        return VoiceChannel(client, data)
    if channel_type == ChannelType.DM:
        return DMChannel(client, data)
    return BaseChannel(client, data)
