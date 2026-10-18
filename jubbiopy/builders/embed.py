"""Zengin embed oluşturucu."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Union

from .._utils import CamelCaseCompat, iso_timestamp

#: Renk sabitleri (Discord.js uyumlu)
Colors: Dict[str, int] = {
    "Default": 0x000000,
    "White": 0xFFFFFF,
    "Aqua": 0x1ABC9C,
    "Green": 0x57F287,
    "Blue": 0x3498DB,
    "Yellow": 0xFEE75C,
    "Purple": 0x9B59B6,
    "LuminousVividPink": 0xE91E63,
    "Fuchsia": 0xEB459E,
    "Gold": 0xF1C40F,
    "Orange": 0xE67E22,
    "Red": 0xED4245,
    "Grey": 0x95A5A6,
    "Navy": 0x34495E,
    "DarkAqua": 0x11806A,
    "DarkGreen": 0x1F8B4C,
    "DarkBlue": 0x206694,
    "DarkPurple": 0x71368A,
    "DarkVividPink": 0xAD1457,
    "DarkGold": 0xC27C0E,
    "DarkOrange": 0xA84300,
    "DarkRed": 0x992D22,
    "DarkGrey": 0x979C9F,
    "DarkerGrey": 0x7F8C8D,
    "LightGrey": 0xBCC0C0,
    "DarkNavy": 0x2C3E50,
    "Blurple": 0x5865F2,
    "Greyple": 0x99AAB5,
    "DarkButNotBlack": 0x2C2F33,
    "NotQuiteBlack": 0x23272A,
}


class _ColorsNamespace(dict):
    """``Colors.Blue`` ve ``Colors["Blue"]`` kullanımının ikisini de destekler."""

    def __getattr__(self, name: str) -> int:
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name) from None


Colors = _ColorsNamespace(Colors)

MAX_FIELDS = 25
ColorLike = Union[int, str, Sequence[int], None]


def _flatten(items: Iterable[Any]) -> List[Dict[str, Any]]:
    flat: List[Dict[str, Any]] = []
    for item in items:
        if isinstance(item, (list, tuple)):
            flat.extend(dict(f) for f in item)
        else:
            flat.append(dict(item))
    return flat


class EmbedBuilder(CamelCaseCompat):
    """Embed oluşturucu.

    Örnek::

        embed = (EmbedBuilder()
                 .set_title("Merhaba!")
                 .set_color(Colors.Blue)
                 .add_fields({"name": "Alan", "value": "Değer", "inline": True})
                 .set_timestamp())
    """

    def __init__(self, data: Optional[Mapping[str, Any]] = None) -> None:
        self.data: Dict[str, Any] = dict(data or {})
        if "fields" in self.data and self.data["fields"] is not None:
            self.data["fields"] = [dict(f) for f in self.data["fields"]]

    def _set(self, key: str, value: Any) -> "EmbedBuilder":
        if value is None:
            self.data.pop(key, None)
        else:
            self.data[key] = value
        return self

    def set_title(self, title: Optional[str]) -> "EmbedBuilder":
        return self._set("title", title)

    def set_description(self, description: Optional[str]) -> "EmbedBuilder":
        return self._set("description", description)

    def set_url(self, url: Optional[str]) -> "EmbedBuilder":
        return self._set("url", url)

    def set_timestamp(self, timestamp: Any = ...) -> "EmbedBuilder":
        """Zaman damgası ayarlar. Parametresiz çağrılırsa şu anki zaman kullanılır;
        ``None`` zaman damgasını kaldırır. ``datetime`` veya milisaniye kabul eder."""
        if timestamp is None:
            return self._set("timestamp", None)
        return self._set("timestamp", iso_timestamp(None if timestamp is ... else timestamp))

    def set_color(self, color: ColorLike) -> "EmbedBuilder":
        """Renk ayarlar: sayı, ``"#ff0000"``, ``"Red"`` gibi isim veya ``(r, g, b)``."""
        if color is None:
            return self._set("color", None)
        if isinstance(color, int):
            return self._set("color", color)
        if isinstance(color, str):
            if color in Colors:
                return self._set("color", Colors[color])
            return self._set("color", int(color.replace("#", ""), 16))
        r, g, b = list(color)[:3]
        return self._set("color", (r << 16) + (g << 8) + b)

    def set_footer(self, options: Optional[Union[Mapping[str, Any], str]] = None, *, text: Optional[str] = None,
                   icon_url: Optional[str] = None) -> "EmbedBuilder":
        if options is None and text is None:
            return self._set("footer", None)
        if isinstance(options, str):
            text = options
        elif isinstance(options, Mapping):
            text = options.get("text", text)
            icon_url = options.get("icon_url") or options.get("iconURL") or icon_url
        footer = {"text": text}
        if icon_url:
            footer["icon_url"] = icon_url
        return self._set("footer", footer)

    def set_image(self, url: Optional[str]) -> "EmbedBuilder":
        return self._set("image", None if url is None else {"url": url})

    def set_thumbnail(self, url: Optional[str]) -> "EmbedBuilder":
        return self._set("thumbnail", None if url is None else {"url": url})

    def set_author(self, options: Optional[Union[Mapping[str, Any], str]] = None, *, name: Optional[str] = None,
                   icon_url: Optional[str] = None, url: Optional[str] = None) -> "EmbedBuilder":
        if options is None and name is None:
            return self._set("author", None)
        if isinstance(options, str):
            name = options
        elif isinstance(options, Mapping):
            name = options.get("name", name)
            icon_url = options.get("icon_url") or options.get("iconURL") or icon_url
            url = options.get("url", url)
        author: Dict[str, Any] = {"name": name}
        if icon_url:
            author["icon_url"] = icon_url
        if url:
            author["url"] = url
        return self._set("author", author)

    def add_field(self, name: str, value: str, inline: bool = False) -> "EmbedBuilder":
        return self.add_fields({"name": name, "value": value, "inline": inline})

    def add_fields(self, *fields: Any) -> "EmbedBuilder":
        """Alan ekler (en fazla 25). Tek tek veya liste halinde verilebilir."""
        current = self.data.setdefault("fields", [])
        flat = _flatten(fields)
        if len(current) + len(flat) > MAX_FIELDS:
            raise ValueError(f"Embed alanları 25'i geçemez. Mevcut: {len(current)}, eklenen: {len(flat)}")
        current.extend(flat)
        return self

    def set_fields(self, *fields: Any) -> "EmbedBuilder":
        flat = _flatten(fields)
        if len(flat) > MAX_FIELDS:
            raise ValueError(f"Embed alanları 25'i geçemez. Verilen: {len(flat)}")
        self.data["fields"] = flat
        return self

    def splice_fields(self, index: int, delete_count: int, *fields: Mapping[str, Any]) -> "EmbedBuilder":
        current = self.data.setdefault("fields", [])
        new = current[:index] + [dict(f) for f in fields] + current[index + delete_count:]
        if len(new) > MAX_FIELDS:
            raise ValueError(f"Embed alanları 25'i geçemez. Sonuç: {len(new)}")
        self.data["fields"] = new
        return self

    def to_json(self) -> Dict[str, Any]:
        result = dict(self.data)
        if result.get("fields") is not None:
            result["fields"] = [dict(f) for f in result["fields"]]
        return result

    to_dict = to_json

    @classmethod
    def from_(cls, other: Union["EmbedBuilder", Mapping[str, Any]]) -> "EmbedBuilder":
        return cls(other.data if isinstance(other, EmbedBuilder) else other)

