"""Sunucu üyesi yapısı ve ``Permissions`` yardımcısı."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Mapping, Optional, Union

from .._utils import CamelCaseCompat, ms_to_datetime, parse_timestamp
from ..enums import PermissionFlagsBits
from .user import User

if TYPE_CHECKING:
    from ..client import Client
    from .guild import Guild

#: İzin isimleri -> bit değerleri (``PermissionFlagsBits`` ile aynı)
PermissionFlags: Dict[str, int] = PermissionFlagsBits.as_dict()

PermissionLike = Union[str, int]


class Permissions(CamelCaseCompat):
    """İzin bit alanı yardımcısı. Sunucu sahibi ve yöneticiler tüm izinlere sahiptir."""

    def __init__(self, bits: Union[int, str] = 0, is_owner: bool = False) -> None:
        self.bitfield: int = int(bits or 0)
        self.is_owner = is_owner
        self._frozen = False

    @staticmethod
    def resolve(permission: PermissionLike) -> int:
        if isinstance(permission, int):
            return permission
        bit = PermissionFlags.get(permission)
        if bit is None:
            raise ValueError(f"Bilinmeyen izin: {permission}")
        return bit

    def _is_admin(self, check_admin: bool) -> bool:
        admin = PermissionFlags["Administrator"]
        return check_admin and (self.bitfield & admin) == admin

    def has(self, permission: PermissionLike, check_admin: bool = True) -> bool:
        if self.is_owner or self._is_admin(check_admin):
            return True
        bit = self.resolve(permission)
        return (self.bitfield & bit) == bit

    def any(self, permissions: Iterable[PermissionLike], check_admin: bool = True) -> bool:
        if self.is_owner or self._is_admin(check_admin):
            return True
        for permission in permissions:
            bit = self.resolve(permission)
            if (self.bitfield & bit) == bit:
                return True
        return False

    def missing(self, permissions: Iterable[PermissionLike], check_admin: bool = True) -> List[str]:
        result = []
        for permission in permissions:
            if not self.has(permission, check_admin):
                if isinstance(permission, str):
                    result.append(permission)
                else:
                    name = next((k for k, v in PermissionFlags.items() if v == permission), str(permission))
                    result.append(name)
        return result

    def _check_frozen(self) -> None:
        if self._frozen:
            raise TypeError("Dondurulmuş (frozen) Permissions nesnesi değiştirilemez")

    def add(self, *permissions: PermissionLike) -> "Permissions":
        self._check_frozen()
        for permission in permissions:
            self.bitfield |= self.resolve(permission)
        return self

    def remove(self, *permissions: PermissionLike) -> "Permissions":
        self._check_frozen()
        for permission in permissions:
            self.bitfield &= ~self.resolve(permission)
        return self

    def equals(self, other: Union["Permissions", int, str]) -> bool:
        if isinstance(other, Permissions):
            return self.bitfield == other.bitfield
        return self.bitfield == int(other)

    def clone(self) -> "Permissions":
        return Permissions(self.bitfield, self.is_owner)

    def freeze(self) -> "Permissions":
        self._frozen = True
        return self

    @property
    def bits(self) -> int:
        return self.bitfield

    def to_array(self) -> List[str]:
        return [name for name, bit in PermissionFlags.items() if (self.bitfield & bit) == bit]

    def to_json(self) -> str:
        return str(self.bitfield)

    def __str__(self) -> str:
        return str(self.bitfield)

    def __repr__(self) -> str:
        return f"<Permissions {self.bitfield}>"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, (Permissions, int, str)):
            try:
                return self.equals(other)  # type: ignore[arg-type]
            except ValueError:
                return False
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self.bitfield)


@dataclass
class VoiceState:
    """Üyenin ses durumu."""

    channel_id: Optional[str] = None
    self_mute: bool = False
    self_deaf: bool = False

    # JS uyumluluğu
    @property
    def channelId(self) -> Optional[str]:  # noqa: N802
        return self.channel_id

    @property
    def selfMute(self) -> bool:  # noqa: N802
        return self.self_mute

    @property
    def selfDeaf(self) -> bool:  # noqa: N802
        return self.self_deaf

    def copy(self) -> "VoiceState":
        return replace(self)


def voice_state_from(data: Optional[Mapping[str, Any]]) -> VoiceState:
    data = data or {}
    channel = data.get("channel_id")
    return VoiceState(
        channel_id=str(channel) if channel is not None else None,
        self_mute=bool(data.get("self_mute") or False),
        self_deaf=bool(data.get("self_deaf") or False),
    )


class GuildMember(CamelCaseCompat):
    """Bir sunucu üyesi."""

    def __init__(self, client: "Client", guild: "Guild", data: Mapping[str, Any]) -> None:
        self.client = client
        self.guild = guild
        user_data = data.get("user") or {"id": "0", "username": "Unknown"}
        self.user = User(user_data, client)
        self.nickname: Optional[str] = data.get("nick")
        self.avatar: Optional[str] = data.get("avatar")
        self.roles: List[str] = [str(r) for r in (data.get("roles") or [])]
        self.joined_timestamp: Optional[float] = parse_timestamp(data.get("joined_at"))
        self.voice = voice_state_from(data.get("voice"))
        owner_id = getattr(guild, "owner_id", None)
        is_owner = owner_id is not None and str(owner_id) == self.user.id
        self.permissions = Permissions(data.get("permissions") or "0", is_owner)

    @property
    def id(self) -> str:
        return self.user.id

    @property
    def display_name(self) -> str:
        return self.nickname or self.user.display_name or self.user.username

    @property
    def joined_at(self) -> Optional[datetime]:
        return ms_to_datetime(self.joined_timestamp)

    @property
    def in_voice_channel(self) -> bool:
        return bool(self.voice.channel_id)

    def avatar_url(self) -> Optional[str]:
        return self.avatar or None

    def display_avatar_url(self) -> str:
        return self.avatar or self.user.display_avatar_url()

    @property
    def mention(self) -> str:
        return f"<@{self.id}>"

    def __str__(self) -> str:
        return self.mention

    def __repr__(self) -> str:
        return f"<GuildMember id={self.id} display_name={self.display_name!r}>"

    def _patch(self, data: Mapping[str, Any]) -> None:
        if "nick" in data:
            self.nickname = data["nick"]
        if "avatar" in data:
            self.avatar = data["avatar"]
        if data.get("roles") is not None:
            self.roles = [str(r) for r in data["roles"]]
        if data.get("voice") is not None:
            self.voice = voice_state_from(data["voice"])
        if data.get("permissions") is not None:
            self.permissions = Permissions(data["permissions"], self.permissions.is_owner)
        if isinstance(data.get("user"), Mapping):
            self.user._patch(data["user"])

    # ------------------------------------------------------------ moderasyon
    @property
    def _guild_id(self) -> str:
        return str(self.guild.id)

    async def kick(self, reason: Optional[str] = None) -> None:
        await self.client.rest.kick_member(self._guild_id, self.id, reason)

    async def ban(self, *, delete_message_days: Optional[int] = None, delete_message_seconds: Optional[int] = None,
                  reason: Optional[str] = None) -> None:
        await self.client.rest.ban_member(self._guild_id, self.id, {
            "delete_message_days": delete_message_days,
            "delete_message_seconds": delete_message_seconds,
            "reason": reason,
        })

    async def timeout(self, duration_ms: Optional[float], reason: Optional[str] = None) -> None:
        """Zaman aşımı uygular (milisaniye). ``None`` zaman aşımını kaldırır."""
        await self.client.rest.timeout_member(self._guild_id, self.id, duration_ms, reason)

    async def edit(self, **data: Any) -> Any:
        return await self.client.rest.edit_member(self._guild_id, self.id, data)

    async def set_nickname(self, nick: Optional[str]) -> Any:
        return await self.edit(nick=nick)

    async def add_role(self, role_id: str, reason: Optional[str] = None) -> None:
        await self.client.rest.add_member_role(self._guild_id, self.id, str(role_id), reason)
        if str(role_id) not in self.roles:
            self.roles.append(str(role_id))

    async def remove_role(self, role_id: str, reason: Optional[str] = None) -> None:
        await self.client.rest.remove_member_role(self._guild_id, self.id, str(role_id), reason)
        if str(role_id) in self.roles:
            self.roles.remove(str(role_id))

    async def send(self, *args: Any, **kwargs: Any) -> Any:
        return await self.user.send(*args, **kwargs)
