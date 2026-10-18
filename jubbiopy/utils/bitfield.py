"""Genel amaçlı ``BitField``, ``PermissionsBitField`` ve ``IntentsBitField``."""

from __future__ import annotations

from typing import Any, ClassVar, Dict, Iterable, Iterator, List, Union

from .._utils import CamelCaseCompat
from ..enums import GatewayIntentBits, PermissionFlagsBits

BitFieldResolvable = Union[int, str, "BitField", Iterable[Any]]


class BitField(CamelCaseCompat):
    """Bit alanı veri yapısı (Discord.js ``BitField`` uyumlu)."""

    Flags: ClassVar[Dict[str, int]] = {}
    DefaultBit: ClassVar[int] = 0

    def __init__(self, bits: BitFieldResolvable = None) -> None:
        self.bitfield: int = self.resolve(self.DefaultBit if bits is None else bits)
        self._frozen = False

    @classmethod
    def resolve(cls, bit: BitFieldResolvable) -> int:
        if isinstance(bit, bool):
            raise TypeError(f"Geçersiz bit: {bit!r}")
        if isinstance(bit, int):
            return int(bit)
        if isinstance(bit, BitField):
            return bit.bitfield
        if isinstance(bit, str):
            if bit.isdigit():
                return int(bit)
            if bit not in cls.Flags:
                raise ValueError(f"Bilinmeyen bit: {bit}")
            return cls.Flags[bit]
        if isinstance(bit, Iterable):
            result = cls.DefaultBit
            for b in bit:
                result |= cls.resolve(b)
            return result
        raise TypeError(f"Geçersiz bit: {bit!r}")

    def has(self, bit: BitFieldResolvable) -> bool:
        resolved = self.resolve(bit)
        return (self.bitfield & resolved) == resolved

    def any(self, bits: BitFieldResolvable) -> bool:
        return (self.bitfield & self.resolve(bits)) != 0

    def missing(self, bits: BitFieldResolvable) -> List[str]:
        resolved = self.resolve(bits)
        return [name for name, bit in self.Flags.items() if (resolved & bit) and not self.has(bit)]

    def _check_frozen(self) -> None:
        if self._frozen:
            raise TypeError("Dondurulmuş (frozen) bit alanı değiştirilemez")

    def add(self, *bits: BitFieldResolvable):
        self._check_frozen()
        for bit in bits:
            self.bitfield |= self.resolve(bit)
        return self

    def remove(self, *bits: BitFieldResolvable):
        self._check_frozen()
        for bit in bits:
            self.bitfield &= ~self.resolve(bit)
        return self

    def to_array(self) -> List[str]:
        return [name for name, bit in self.Flags.items() if self.bitfield & bit]

    def to_json(self) -> Union[str, int]:
        return str(self.bitfield)

    def freeze(self):
        self._frozen = True
        return self

    def equals(self, other: BitFieldResolvable) -> bool:
        return self.bitfield == self.resolve(other)

    def clone(self):
        return type(self)(self.bitfield)

    def serialize(self) -> Dict[str, bool]:
        return {name: self.has(bit) for name, bit in self.Flags.items()}

    def __iter__(self) -> Iterator[str]:
        return iter(self.to_array())

    def __int__(self) -> int:
        return self.bitfield

    def __str__(self) -> str:
        return str(self.bitfield)

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.bitfield}>"

    def __eq__(self, other: object) -> bool:
        try:
            return self.equals(other)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return NotImplemented

    def __hash__(self) -> int:
        return hash(self.bitfield)

    def __contains__(self, bit: BitFieldResolvable) -> bool:
        return self.has(bit)


class PermissionsBitField(BitField):
    """İzin bit alanı. Varsayılan olarak ``Administrator`` tüm izinleri kapsar."""

    Flags: ClassVar[Dict[str, int]] = PermissionFlagsBits.as_dict()
    All: ClassVar[int] = 0
    Default: ClassVar[int] = 0

    def has(self, permission: BitFieldResolvable, check_admin: bool = True) -> bool:  # type: ignore[override]
        if check_admin and self.bitfield & PermissionFlagsBits.Administrator:
            return True
        return super().has(permission)

    def any(self, permissions: BitFieldResolvable, check_admin: bool = True) -> bool:  # type: ignore[override]
        if check_admin and self.bitfield & PermissionFlagsBits.Administrator:
            return True
        return super().any(permissions)

    def missing(self, permissions: BitFieldResolvable, check_admin: bool = True) -> List[str]:  # type: ignore[override]
        resolved = self.resolve(permissions)
        return [name for name, bit in self.Flags.items() if (resolved & bit) and not self.has(bit, check_admin)]


PermissionsBitField.All = sum(PermissionsBitField.Flags.values())


class IntentsBitField(BitField):
    """Gateway intent bit alanı."""

    Flags: ClassVar[Dict[str, int]] = {m.name: int(m.value) for m in GatewayIntentBits}

    PRIVILEGED: ClassVar[int] = int(
        GatewayIntentBits.GuildMembers | GatewayIntentBits.GuildPresences | GatewayIntentBits.MessageContent
    )

    def has_privileged(self) -> bool:
        return self.any(self.PRIVILEGED)

    def get_privileged(self) -> List[str]:
        return [name for name in ("GuildMembers", "GuildPresences", "MessageContent") if self.has(name)]


IntentsAll = sum(IntentsBitField.Flags.values())
PrivilegedIntents = IntentsBitField.PRIVILEGED


def calculate_intents(intents: Iterable[Union[int, str]]) -> int:
    return IntentsBitField.resolve(list(intents))


def resolve_intents(bits: int) -> List[str]:
    return [name for name, value in IntentsBitField.Flags.items() if (bits & value) == value]
