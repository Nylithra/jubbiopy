"""Etkileşim (slash komut, buton, menü, modal) yapıları."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Optional, Sequence

from .._utils import CamelCaseCompat, to_json
from ..enums import ApplicationCommandOptionType, InteractionResponseType, InteractionType, MessageFlags
from ._options import MessageOptions, parse_message_options
from .collection import Collection
from .guild_member import GuildMember
from .message import Message
from .user import User

if TYPE_CHECKING:
    from ..client import Client
    from .guild import Guild

_USER_ID_RE = re.compile(r"^<?@?!?(\d+)>?$")


class _StubGuild:
    """Önbellekte olmayan sunucular için minimal sunucu nesnesi."""

    def __init__(self, guild_id: str) -> None:
        self.id = guild_id
        self.owner_id = None
        self.members: Collection = Collection()
        self.channels: Collection = Collection()


class Interaction(CamelCaseCompat):
    """Tüm etkileşimlerin temel sınıfı."""

    component_type: Optional[int] = None

    def __init__(self, client: "Client", data: Mapping[str, Any]) -> None:
        self.client = client
        self.id: str = str(data.get("id"))
        self.application_id: str = str(data.get("application_id"))
        raw_type = data.get("type")
        try:
            self.type = InteractionType(raw_type)
        except ValueError:
            self.type = raw_type
        self.guild_id: Optional[str] = str(data["guild_id"]) if data.get("guild_id") else None
        self.channel_id: Optional[str] = str(data["channel_id"]) if data.get("channel_id") else None
        self.token: str = data.get("token") or ""
        self.raw: Mapping[str, Any] = data
        self.replied = False
        self.deferred = False

        member_data = data.get("member")
        user_data = (member_data or {}).get("user") or data.get("user")
        self.user = User(user_data, client) if user_data else User({"id": "0", "username": "Unknown"}, client)

        self.member: Optional[GuildMember] = None
        if member_data and self.guild_id:
            guild = client.guilds.get(self.guild_id)
            if guild is not None:
                self.member = GuildMember(client, guild, member_data)
                # Backend ses durumu göndermediyse önbellekten doldur
                if not (member_data.get("voice") or {}).get("channel_id"):
                    cached = guild.members.get(self.member.id)
                    if cached is not None and cached.voice.channel_id:
                        self.member.voice = cached.voice.copy()
            else:
                self.member = GuildMember(client, _StubGuild(self.guild_id), member_data)  # type: ignore[arg-type]

    @property
    def guild(self) -> Optional["Guild"]:
        if not self.guild_id:
            return None
        return self.client.guilds.get(self.guild_id)

    @property
    def channel(self):
        if not self.channel_id:
            return None
        from .channel import TextChannel

        return TextChannel(self.client, {"id": self.channel_id, "guild_id": self.guild_id, "type": 0})

    # ------------------------------------------------------------ tip kontrolleri
    def is_command(self) -> bool:
        return self.type == InteractionType.ApplicationCommand

    def is_chat_input_command(self) -> bool:
        return self.is_command()

    def is_autocomplete(self) -> bool:
        return self.type == InteractionType.ApplicationCommandAutocomplete

    def is_modal_submit(self) -> bool:
        return self.type == InteractionType.ModalSubmit

    def is_button(self) -> bool:
        return self.type == InteractionType.MessageComponent and self.component_type == 2

    def is_select_menu(self) -> bool:
        return self.type == InteractionType.MessageComponent and self.component_type == 3

    def is_string_select_menu(self) -> bool:
        return self.is_select_menu()

    def is_message_component(self) -> bool:
        return self.type == InteractionType.MessageComponent

    def is_repliable(self) -> bool:
        return self.type not in (InteractionType.Ping, InteractionType.ApplicationCommandAutocomplete)

    def __repr__(self) -> str:
        return f"<{type(self).__name__} id={self.id} user={self.user!r}>"

    # ------------------------------------------------------------- yanıtlar
    async def reply(self, content: MessageOptions = None, **kwargs: Any) -> None:
        """Etkileşimi yanıtlar. ``ephemeral=True`` sadece kullanıcıya görünür yapar."""
        if self.replied or self.deferred:
            raise RuntimeError("Etkileşim zaten yanıtlandı veya ertelendi")
        opts = parse_message_options(content, kwargs)
        flags = int(opts.get("flags") or 0) | (int(MessageFlags.Ephemeral) if opts.get("ephemeral") else 0)
        await self.client.rest.create_interaction_response(self.id, self.token, {
            "type": int(InteractionResponseType.ChannelMessageWithSource),
            "data": {
                "content": opts.get("content"),
                "embeds": opts.get("embeds"),
                "components": opts.get("components"),
                "flags": flags,
            },
        })
        self.replied = True

    async def defer_reply(self, *, ephemeral: bool = False) -> None:
        """Yanıtı erteler ("düşünüyor..." gösterir)."""
        if self.replied or self.deferred:
            raise RuntimeError("Etkileşim zaten yanıtlandı veya ertelendi")
        await self.client.rest.create_interaction_response(self.id, self.token, {
            "type": int(InteractionResponseType.DeferredChannelMessageWithSource),
            "data": {"flags": int(MessageFlags.Ephemeral)} if ephemeral else None,
        })
        self.deferred = True

    async def edit_reply(self, content: MessageOptions = None, **kwargs: Any) -> None:
        """Yanıtı düzenler (``defer_reply`` sonrası asıl yanıtı göndermek için de kullanılır)."""
        opts = parse_message_options(content, kwargs)
        await self.client.rest.edit_interaction_response(self.token, {
            "content": opts.get("content"),
            "embeds": opts.get("embeds"),
            "components": opts.get("components"),
            "files": opts.get("files"),
        }, self.guild_id, self.channel_id, self.id)

    async def delete_reply(self) -> None:
        await self.client.rest.delete_interaction_response(self.token)

    async def follow_up(self, content: MessageOptions = None, **kwargs: Any) -> None:
        """Takip mesajı gönderir."""
        opts = parse_message_options(content, kwargs)
        await self.client.rest.create_followup(self.token, {
            "content": opts.get("content"),
            "embeds": opts.get("embeds"),
            "components": opts.get("components"),
            "flags": int(MessageFlags.Ephemeral) if opts.get("ephemeral") else 0,
            "files": opts.get("files"),
        })

    followup = follow_up


class _ModalMixin:
    async def show_modal(self, modal: Any) -> None:
        """Kullanıcıya bir modal (form) gösterir."""
        await self.client.rest.create_interaction_response(self.id, self.token, {  # type: ignore[attr-defined]
            "type": int(InteractionResponseType.Modal),
            "data": to_json(modal),
        })


class CommandInteractionOptions(CamelCaseCompat):
    """Komut seçeneklerine erişim yardımcısı."""

    #: Kod enjeksiyonu girişimini işaret eden kalıplar
    DANGEROUS_PATTERNS = (
        "require(", "import(", "child_process", "eval(", "Function(",
        "exec(", "spawn(", "execSync(", "spawnSync(", "__proto__",
        "constructor[", "process.env", "process.exit",
        "fs.read", "fs.write", "fs.unlink",
        "os.exec", "os.system", "subprocess", "Runtime.getRuntime",
        # Python'a özgü
        "__import__", "importlib",
    )

    def __init__(self, client: "Client", options: Sequence[Mapping[str, Any]], resolved: Optional[Mapping[str, Any]] = None) -> None:
        self.client = client
        self.resolved: Mapping[str, Any] = resolved or {}
        self.data: List[Mapping[str, Any]] = list(options or [])
        self._subcommand: Optional[str] = None
        self._group: Optional[str] = None
        hoisted = self.data
        # Alt komut / alt komut grubu seçeneklerini düzleştir
        if hoisted and hoisted[0].get("type") == ApplicationCommandOptionType.SubcommandGroup:
            self._group = hoisted[0].get("name")
            hoisted = list(hoisted[0].get("options") or [])
        if hoisted and hoisted[0].get("type") == ApplicationCommandOptionType.Subcommand:
            self._subcommand = hoisted[0].get("name")
            hoisted = list(hoisted[0].get("options") or [])
        self._hoisted: List[Mapping[str, Any]] = hoisted

    @classmethod
    def sanitize(cls, value: str) -> str:
        lower = value.lower()
        for pattern in cls.DANGEROUS_PATTERNS:
            if pattern.lower() in lower:
                return ""
        return value

    def get(self, name: str, required: bool = False) -> Optional[Mapping[str, Any]]:
        option = next((o for o in self._hoisted if o.get("name") == name), None)
        if option is None and required:
            raise KeyError(f'Gerekli seçenek "{name}" bulunamadı')
        return option

    def _value(self, name: str, required: bool) -> Any:
        option = self.get(name, required)
        return None if option is None else option.get("value")

    def get_string(self, name: str, required: bool = False) -> Optional[str]:
        """String seçeneği (kod enjeksiyonuna karşı temizlenmiş)."""
        raw = self._value(name, required)
        if raw is None or raw == "":
            return None
        return self.sanitize(str(raw))

    def get_integer(self, name: str, required: bool = False) -> Optional[int]:
        value = self._value(name, required)
        return None if value is None else int(value)

    def get_number(self, name: str, required: bool = False) -> Optional[float]:
        value = self._value(name, required)
        return None if value is None else float(value)

    def get_boolean(self, name: str, required: bool = False) -> Optional[bool]:
        value = self._value(name, required)
        if isinstance(value, str):
            return value.lower() == "true"
        return None if value is None else bool(value)

    def get_user_id(self, name: str, required: bool = False) -> Optional[str]:
        option = self.get(name, required)
        if option is None:
            return None
        raw = str(option.get("value") or "")
        match = _USER_ID_RE.match(raw)
        return match.group(1) if match else raw

    def get_user(self, name: str, required: bool = False) -> Optional[User]:
        """Kullanıcı seçeneği. ``"123"``, ``"<@123>"`` veya ``"<@!123>"`` formatlarını çözer."""
        user_id = self.get_user_id(name, required)
        if not user_id:
            return None
        users = self.resolved.get("users") or {}
        if user_id in users:
            return User(users[user_id], self.client)
        if user_id.isdigit():
            return User({"id": user_id, "username": f"User_{user_id}"}, self.client)
        return None

    def get_member(self, name: str) -> Optional[Mapping[str, Any]]:
        user_id = self.get_user_id(name)
        return (self.resolved.get("members") or {}).get(user_id) if user_id else None

    def get_channel(self, name: str, required: bool = False) -> Any:
        value = self._value(name, required)
        if value is None:
            return None
        return (self.resolved.get("channels") or {}).get(str(value), value)

    def get_role(self, name: str, required: bool = False) -> Any:
        value = self._value(name, required)
        if value is None:
            return None
        return (self.resolved.get("roles") or {}).get(str(value), value)

    def get_mentionable(self, name: str, required: bool = False) -> Any:
        return self._value(name, required)

    def get_attachment(self, name: str, required: bool = False) -> Any:
        value = self._value(name, required)
        if value is None:
            return None
        return (self.resolved.get("attachments") or {}).get(str(value), value)

    def get_subcommand(self, required: bool = False) -> Optional[str]:
        if self._subcommand is None and required:
            raise KeyError("Gerekli alt komut bulunamadı")
        return self._subcommand

    def get_subcommand_group(self, required: bool = False) -> Optional[str]:
        if self._group is None and required:
            raise KeyError("Gerekli alt komut grubu bulunamadı")
        return self._group

    def get_focused(self, full: bool = True) -> Any:
        """Otomatik tamamlamada odaktaki seçenek: ``{"name": ..., "value": ...}``."""
        option = next((o for o in self._hoisted if o.get("focused")), None)
        if option is None:
            return None
        return {"name": option.get("name"), "value": option.get("value")} if full else option.get("value")

    def __iter__(self):
        return iter(self._hoisted)

    def __len__(self) -> int:
        return len(self._hoisted)


class CommandInteraction(_ModalMixin, Interaction):
    """Slash komut etkileşimi."""

    def __init__(self, client: "Client", data: Mapping[str, Any]) -> None:
        super().__init__(client, data)
        inner = data.get("data") or {}
        self.command_name: str = inner.get("name") or ""
        self.command_id: Optional[str] = str(inner["id"]) if inner.get("id") else None
        self.options = CommandInteractionOptions(client, inner.get("options") or [], inner.get("resolved"))


ChatInputCommandInteraction = CommandInteraction


class AutocompleteInteraction(Interaction):
    """Otomatik tamamlama etkileşimi."""

    def __init__(self, client: "Client", data: Mapping[str, Any]) -> None:
        super().__init__(client, data)
        inner = data.get("data") or {}
        self.command_name: str = inner.get("name") or ""
        self.options = CommandInteractionOptions(client, inner.get("options") or [], inner.get("resolved"))

    async def respond(self, choices: Sequence[Mapping[str, Any]]) -> None:
        """Otomatik tamamlama seçeneklerini döndürür: ``[{"name": ..., "value": ...}]``."""
        await self.client.rest.create_interaction_response(self.id, self.token, {
            "type": int(InteractionResponseType.ApplicationCommandAutocompleteResult),
            "data": {"choices": [dict(c) for c in choices]},
        })


class _ComponentInteraction(_ModalMixin, Interaction):
    def __init__(self, client: "Client", data: Mapping[str, Any]) -> None:
        super().__init__(client, data)
        inner = data.get("data") or {}
        self.custom_id: str = inner.get("custom_id") or ""
        self.message: Optional[Message] = None
        if data.get("message"):
            # Backend minimal mesaj gönderdiği için guild_id etkileşimden eklenir
            self.message = Message(client, {**data["message"], "guild_id": data.get("guild_id")})

    async def update(self, content: MessageOptions = None, **kwargs: Any) -> None:
        """Bileşenin bağlı olduğu mesajı günceller."""
        opts = parse_message_options(content, kwargs)
        await self.client.rest.create_interaction_response(self.id, self.token, {
            "type": int(InteractionResponseType.UpdateMessage),
            "data": {
                "content": opts.get("content"),
                "embeds": opts.get("embeds"),
                "components": opts.get("components"),
            },
        })
        self.replied = True

    async def defer_update(self) -> None:
        await self.client.rest.create_interaction_response(self.id, self.token, {
            "type": int(InteractionResponseType.DeferredUpdateMessage),
        })
        self.deferred = True


class ButtonInteraction(_ComponentInteraction):
    """Buton etkileşimi."""

    component_type = 2


class SelectMenuInteraction(_ComponentInteraction):
    """Seçim menüsü etkileşimi."""

    component_type = 3

    def __init__(self, client: "Client", data: Mapping[str, Any]) -> None:
        super().__init__(client, data)
        self.values: List[str] = list((data.get("data") or {}).get("values") or [])


StringSelectMenuInteraction = SelectMenuInteraction


class ModalFields(CamelCaseCompat):
    """Modal alanlarına erişim yardımcısı."""

    def __init__(self, components: Sequence[Mapping[str, Any]]) -> None:
        self._fields: Dict[str, Any] = {}
        for row in components or []:
            for comp in (row or {}).get("components") or []:
                if comp.get("custom_id") and comp.get("value") is not None:
                    self._fields[comp["custom_id"]] = comp["value"]

    def get_text_input_value(self, custom_id: str) -> Optional[str]:
        return self._fields.get(custom_id)

    def get_field(self, custom_id: str) -> Optional[Dict[str, Any]]:
        if custom_id not in self._fields:
            return None
        return {"value": self._fields[custom_id]}

    def __contains__(self, custom_id: str) -> bool:
        return custom_id in self._fields

    def __iter__(self):
        return iter(self._fields.items())


class ModalSubmitInteraction(Interaction):
    """Modal gönderim etkileşimi."""

    def __init__(self, client: "Client", data: Mapping[str, Any]) -> None:
        super().__init__(client, data)
        inner = data.get("data") or {}
        self.custom_id: str = inner.get("custom_id") or ""
        components = list(inner.get("components") or [])
        # Backend uyumluluğu: değerler values[0] içinde JSON string olarak gelebilir
        if not components and inner.get("values"):
            try:
                parsed = json.loads(inner["values"][0])
                if isinstance(parsed, list):
                    components = parsed
            except (TypeError, ValueError):
                pass
        self.fields = ModalFields(components)
        self.message: Optional[Message] = None
        if data.get("message"):
            self.message = Message(client, {**data["message"], "guild_id": data.get("guild_id")})


def create_interaction(client: "Client", data: Mapping[str, Any]) -> Interaction:
    """Etkileşim tipine göre uygun sınıfı oluşturur."""
    interaction_type = data.get("type")
    if interaction_type == InteractionType.ApplicationCommand:
        return CommandInteraction(client, data)
    if interaction_type == InteractionType.ApplicationCommandAutocomplete:
        return AutocompleteInteraction(client, data)
    if interaction_type == InteractionType.ModalSubmit:
        return ModalSubmitInteraction(client, data)
    if interaction_type == InteractionType.MessageComponent:
        component_type = (data.get("data") or {}).get("component_type")
        if component_type == 2:
            return ButtonInteraction(client, data)
        if component_type == 3:
            return SelectMenuInteraction(client, data)
    return Interaction(client, data)
