"""Kütüphane içi yardımcı fonksiyonlar."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional

_CAMEL_RE = re.compile(r"(?<!^)(?=[A-Z])")


def camel_to_snake(name: str) -> str:
    """``setCustomId`` -> ``set_custom_id``, ``iconURL`` -> ``icon_url``."""
    # Ardışık büyük harfleri (URL, ID, DM, NSFW) tek kelime say
    name = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    return name.lower()


def snake_to_camel(name: str) -> str:
    """``message_create`` -> ``messageCreate``."""
    if "_" not in name:
        return name
    head, *rest = name.split("_")
    return head + "".join(part[:1].upper() + part[1:] for part in rest)


class CamelCaseCompat:
    """JS API'sine alışkın olanlar için camelCase takma adlar.

    ``embed.setTitle("x")`` çağrısı otomatik olarak ``embed.set_title("x")``
    metoduna yönlendirilir. Sadece normal attribute araması başarısız
    olduğunda devreye girer, bu yüzden performansa etkisi yoktur.
    """

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_") or not any(c.isupper() for c in name):
            raise AttributeError(f"{type(self).__name__!r} nesnesinde {name!r} özelliği yok")
        snake = camel_to_snake(name)
        try:
            return object.__getattribute__(self, snake)
        except AttributeError:
            raise AttributeError(f"{type(self).__name__!r} nesnesinde {name!r} özelliği yok") from None


def to_json(value: Any) -> Any:
    """Builder nesnelerini (``to_json()`` metodu olanları) iç içe düz dict'e çevirir."""
    if hasattr(value, "to_json") and callable(value.to_json):
        return to_json(value.to_json())
    if isinstance(value, Mapping):
        return {k: to_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_json(v) for v in value]
    return value


def iso_timestamp(value: Any = None) -> str:
    """JS ``Date.toISOString()`` ile aynı formatta zaman damgası üretir."""
    if value is None:
        dt = datetime.now(timezone.utc)
    elif isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    elif isinstance(value, (int, float)):
        # JS gibi milisaniye kabul et; saniye verildiyse de çalışsın
        seconds = value / 1000 if value > 1e11 else value
        dt = datetime.fromtimestamp(seconds, tz=timezone.utc)
    elif isinstance(value, str):
        return value
    else:
        raise TypeError(f"Geçersiz zaman damgası: {value!r}")
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_timestamp(value: Any) -> Optional[float]:
    """API'den gelen ISO zaman damgasını milisaniye cinsinden epoch'a çevirir."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        text = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp() * 1000
    except ValueError:
        return None


def ms_to_datetime(ms: Optional[float]) -> Optional[datetime]:
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def to_int_id(value: Any) -> Any:
    """JS ``parseInt(id, 10)`` davranışı: sayıya çevrilebiliyorsa int döndür."""
    if isinstance(value, int):
        return value
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return value


def parse_color(color: Any) -> Any:
    if isinstance(color, str):
        return int(color.replace("#", ""), 16)
    return color


def normalize_embed(embed: Any) -> Dict[str, Any]:
    """EmbedBuilder/dict embed'i API formatına normalize eder (renk, zaman, icon_url)."""
    raw = to_json(embed)
    processed = dict(raw)
    if isinstance(processed.get("thumbnail"), str):
        processed["thumbnail"] = {"url": processed["thumbnail"]}
    if isinstance(processed.get("image"), str):
        processed["image"] = {"url": processed["image"]}
    if isinstance(processed.get("color"), str):
        processed["color"] = parse_color(processed["color"])
    ts = processed.get("timestamp")
    if ts is not None and not isinstance(ts, str):
        processed["timestamp"] = iso_timestamp(ts)
    for key in ("footer", "author"):
        part = processed.get(key)
        if isinstance(part, Mapping):
            part = dict(part)
            icon = part.pop("iconURL", None) or part.pop("icon_url", None)
            if icon is not None:
                part["icon_url"] = icon
            processed[key] = {k: v for k, v in part.items() if v is not None}
    return {k: v for k, v in processed.items() if v is not None}


def drop_none(data: Mapping[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in data.items() if v is not None}
