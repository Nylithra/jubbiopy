"""Buton, seçim menüsü, action row ve modal oluşturucuları."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Union

from .._utils import CamelCaseCompat, to_json
from ..enums import ButtonStyle, TextInputStyle


def _emoji(emoji: Union[str, Mapping[str, Any]]) -> Dict[str, Any]:
    return {"name": emoji} if isinstance(emoji, str) else dict(emoji)


class _Builder(CamelCaseCompat):
    def __init__(self, data: Optional[Mapping[str, Any]] = None, **defaults: Any) -> None:
        self.data: Dict[str, Any] = {**defaults, **dict(data or {})}

    def _set(self, key: str, value: Any):
        self.data[key] = value
        return self

    def to_json(self) -> Dict[str, Any]:
        return to_json(dict(self.data))

    to_dict = to_json

    @classmethod
    def from_(cls, other: Any):
        return cls(other.data if isinstance(other, cls) else other)


class ButtonBuilder(_Builder):
    """Buton oluşturucu."""

    def __init__(self, data: Optional[Mapping[str, Any]] = None) -> None:
        super().__init__(data, type=2)

    def set_custom_id(self, custom_id: str) -> "ButtonBuilder":
        return self._set("custom_id", custom_id)

    def set_label(self, label: str) -> "ButtonBuilder":
        return self._set("label", label)

    def set_style(self, style: Union[ButtonStyle, int]) -> "ButtonBuilder":
        return self._set("style", int(style))

    def set_emoji(self, emoji: Union[str, Mapping[str, Any]]) -> "ButtonBuilder":
        return self._set("emoji", _emoji(emoji))

    def set_url(self, url: str) -> "ButtonBuilder":
        """URL ayarlar (sadece ``ButtonStyle.Link`` için)."""
        return self._set("url", url)

    def set_disabled(self, disabled: bool = True) -> "ButtonBuilder":
        return self._set("disabled", disabled)


class StringSelectMenuOptionBuilder(_Builder):
    """Seçim menüsü seçeneği oluşturucu."""

    def set_label(self, label: str) -> "StringSelectMenuOptionBuilder":
        return self._set("label", label)

    def set_value(self, value: str) -> "StringSelectMenuOptionBuilder":
        return self._set("value", value)

    def set_description(self, description: str) -> "StringSelectMenuOptionBuilder":
        return self._set("description", description)

    def set_emoji(self, emoji: Union[str, Mapping[str, Any]]) -> "StringSelectMenuOptionBuilder":
        return self._set("emoji", _emoji(emoji))

    def set_default(self, is_default: bool = True) -> "StringSelectMenuOptionBuilder":
        return self._set("default", is_default)


def _flatten(items: Iterable[Any]) -> List[Any]:
    flat: List[Any] = []
    for item in items:
        if isinstance(item, (list, tuple)):
            flat.extend(_flatten(item))
        else:
            flat.append(to_json(item))
    return flat


class StringSelectMenuBuilder(_Builder):
    """Metin seçim menüsü oluşturucu."""

    def __init__(self, data: Optional[Mapping[str, Any]] = None) -> None:
        super().__init__(data, type=3)
        self.data["options"] = [to_json(o) for o in self.data.get("options") or []]

    def set_custom_id(self, custom_id: str) -> "StringSelectMenuBuilder":
        return self._set("custom_id", custom_id)

    def set_placeholder(self, placeholder: str) -> "StringSelectMenuBuilder":
        return self._set("placeholder", placeholder)

    def set_min_values(self, min_values: int) -> "StringSelectMenuBuilder":
        return self._set("min_values", min_values)

    def set_max_values(self, max_values: int) -> "StringSelectMenuBuilder":
        return self._set("max_values", max_values)

    def set_disabled(self, disabled: bool = True) -> "StringSelectMenuBuilder":
        return self._set("disabled", disabled)

    def add_options(self, *options: Any) -> "StringSelectMenuBuilder":
        self.data["options"].extend(_flatten(options))
        return self

    def set_options(self, *options: Any) -> "StringSelectMenuBuilder":
        self.data["options"] = _flatten(options)
        return self

    def splice_options(self, index: int, delete_count: int, *options: Any) -> "StringSelectMenuBuilder":
        current = self.data["options"]
        self.data["options"] = current[:index] + _flatten(options) + current[index + delete_count:]
        return self


SelectMenuBuilder = StringSelectMenuBuilder


class ActionRowBuilder(_Builder):
    """Bileşen satırı (action row) oluşturucu."""

    def __init__(self, data: Optional[Mapping[str, Any]] = None) -> None:
        super().__init__({"components": list((data or {}).get("components") or [])}, type=1)
        self.data["components"] = _flatten(self.data["components"])

    def add_components(self, *components: Any) -> "ActionRowBuilder":
        """Bileşen ekler. Tek tek veya liste halinde verilebilir."""
        self.data["components"].extend(_flatten(components))
        return self

    def set_components(self, *components: Any) -> "ActionRowBuilder":
        self.data["components"] = _flatten(components)
        return self

    def splice_components(self, index: int, delete_count: int, *components: Any) -> "ActionRowBuilder":
        current = self.data["components"]
        self.data["components"] = current[:index] + _flatten(components) + current[index + delete_count:]
        return self


class TextInputBuilder(_Builder):
    """Modal metin girişi oluşturucu."""

    def __init__(self, data: Optional[Mapping[str, Any]] = None) -> None:
        super().__init__(data, type=4)

    def set_custom_id(self, custom_id: str) -> "TextInputBuilder":
        return self._set("custom_id", custom_id)

    def set_label(self, label: str) -> "TextInputBuilder":
        return self._set("label", label)

    def set_style(self, style: Union[TextInputStyle, int]) -> "TextInputBuilder":
        return self._set("style", int(style))

    def set_min_length(self, min_length: int) -> "TextInputBuilder":
        return self._set("min_length", min_length)

    def set_max_length(self, max_length: int) -> "TextInputBuilder":
        return self._set("max_length", max_length)

    def set_required(self, required: bool = True) -> "TextInputBuilder":
        return self._set("required", required)

    def set_value(self, value: str) -> "TextInputBuilder":
        return self._set("value", value)

    def set_placeholder(self, placeholder: str) -> "TextInputBuilder":
        return self._set("placeholder", placeholder)


class ModalBuilder(_Builder):
    """Modal (form) oluşturucu."""

    def __init__(self, data: Optional[Mapping[str, Any]] = None) -> None:
        super().__init__(data)
        self.data["components"] = _flatten(self.data.get("components") or [])

    def set_custom_id(self, custom_id: str) -> "ModalBuilder":
        return self._set("custom_id", custom_id)

    def set_title(self, title: str) -> "ModalBuilder":
        return self._set("title", title)

    def add_components(self, *components: Any) -> "ModalBuilder":
        """Metin girişleri içeren action row'lar ekler."""
        self.data["components"].extend(_flatten(components))
        return self

    def set_components(self, *components: Any) -> "ModalBuilder":
        self.data["components"] = _flatten(components)
        return self
