"""Mesaj gönderme seçeneklerini (str / dict / kwargs) tek formata çeviren yardımcı."""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Union

from .._utils import camel_to_snake, to_json

MessageOptions = Union[str, Mapping[str, Any], None]


def parse_message_options(content: MessageOptions, kwargs: Mapping[str, Any]) -> Dict[str, Any]:
    """``reply("metin")``, ``reply({"content": ...})`` ve ``reply(content=..., embeds=[...])``
    çağrılarının hepsini aynı sözlüğe dönüştürür. camelCase anahtarlar da kabul edilir."""
    opts: Dict[str, Any] = {}
    if isinstance(content, Mapping):
        opts.update({camel_to_snake(k): v for k, v in content.items()})
    elif content is not None:
        opts["content"] = str(content)
    opts.update({camel_to_snake(k): v for k, v in kwargs.items() if v is not None})

    # Tekil embed desteği (embed=...)
    if opts.get("embed") is not None and not opts.get("embeds"):
        opts["embeds"] = [opts["embed"]]
    opts.pop("embed", None)

    if opts.get("embeds") is not None:
        opts["embeds"] = to_json(list(opts["embeds"]))
    if opts.get("components") is not None:
        opts["components"] = to_json(list(opts["components"]))
    return opts


def pick(opts: Mapping[str, Any], *keys: str) -> Dict[str, Any]:
    return {k: opts.get(k) for k in keys}


def first_file(opts: Mapping[str, Any]) -> Optional[Any]:
    files = opts.get("files") or ([opts["file"]] if opts.get("file") else [])
    return files[0] if files else None
