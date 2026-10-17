"""Markdown ve mention biçimlendiricileri."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from types import SimpleNamespace
from typing import Any, Iterable, Optional, Union

__all__ = [
    "Formatters", "TimestampStyles", "block_quote", "bold", "channel_mention", "code_block", "format_emoji",
    "heading", "hide_link_embed", "hyperlink", "inline_code", "italic", "ordered_list", "quote",
    "role_mention", "spoiler", "strikethrough", "time", "underline", "unordered_list", "user_mention",
    "blockQuote", "channelMention", "codeBlock", "formatEmoji", "hideLinkEmbed", "inlineCode",
    "orderedList", "roleMention", "unorderedList", "userMention",
]


def user_mention(user_id: Any) -> str:
    return f"<@{user_id}>"


def channel_mention(channel_id: Any) -> str:
    return f"<#{channel_id}>"


def role_mention(role_id: Any) -> str:
    return f"<@&{role_id}>"


def format_emoji(emoji_id: Any, name: str, animated: bool = False) -> str:
    return f"<{'a' if animated else ''}:{name}:{emoji_id}>"


def bold(text: Any) -> str:
    return f"**{text}**"


def italic(text: Any) -> str:
    return f"*{text}*"


def underline(text: Any) -> str:
    return f"__{text}__"


def strikethrough(text: Any) -> str:
    return f"~~{text}~~"


def spoiler(text: Any) -> str:
    return f"||{text}||"


def inline_code(text: Any) -> str:
    return f"`{text}`"


def code_block(text: Any, language: Optional[str] = None) -> str:
    return f"```{language or ''}\n{text}\n```"


def block_quote(text: Any) -> str:
    return f">>> {text}"


def quote(text: Any) -> str:
    return f"> {text}"


def hyperlink(text: Any, url: str, title: Optional[str] = None) -> str:
    return f'[{text}]({url} "{title}")' if title else f"[{text}]({url})"


def hide_link_embed(url: str) -> str:
    return f"<{url}>"


class TimestampStyles(str, Enum):
    ShortTime = "t"       # 16:20
    LongTime = "T"        # 16:20:30
    ShortDate = "d"       # 20/04/2021
    LongDate = "D"        # 20 Nisan 2021
    ShortDateTime = "f"   # 20 Nisan 2021 16:20
    LongDateTime = "F"    # Salı, 20 Nisan 2021 16:20
    RelativeTime = "R"    # 2 ay önce


def time(timestamp: Union[datetime, int, float, None] = None, style: Union[TimestampStyles, str, None] = None) -> str:
    """Zaman damgası biçimlendirir. ``datetime``, milisaniye veya saniye kabul eder."""
    if timestamp is None:
        timestamp = datetime.now()
    if isinstance(timestamp, datetime):
        seconds = int(timestamp.timestamp())
    elif timestamp > 1e12:
        seconds = int(timestamp // 1000)
    else:
        seconds = int(timestamp)
    style_value = style.value if isinstance(style, TimestampStyles) else style
    return f"<t:{seconds}:{style_value}>" if style_value else f"<t:{seconds}>"


def heading(text: Any, level: int = 1) -> str:
    return f"{'#' * level} {text}"


def unordered_list(items: Iterable[Any]) -> str:
    return "\n".join(f"- {item}" for item in items)


def ordered_list(items: Iterable[Any]) -> str:
    return "\n".join(f"{i}. {item}" for i, item in enumerate(items, start=1))


# JS isimleriyle takma adlar
userMention = user_mention
channelMention = channel_mention
roleMention = role_mention
formatEmoji = format_emoji
inlineCode = inline_code
codeBlock = code_block
blockQuote = block_quote
hideLinkEmbed = hide_link_embed
unorderedList = unordered_list
orderedList = ordered_list

#: Tüm biçimlendiriciler tek bir isim alanında (Discord.js uyumlu)
Formatters = SimpleNamespace(
    user_mention=user_mention, channel_mention=channel_mention, role_mention=role_mention,
    format_emoji=format_emoji, bold=bold, italic=italic, underline=underline,
    strikethrough=strikethrough, spoiler=spoiler, inline_code=inline_code, code_block=code_block,
    block_quote=block_quote, quote=quote, hyperlink=hyperlink, hide_link_embed=hide_link_embed,
    time=time, heading=heading, unordered_list=unordered_list, ordered_list=ordered_list,
    TimestampStyles=TimestampStyles,
    userMention=user_mention, channelMention=channel_mention, roleMention=role_mention,
    formatEmoji=format_emoji, inlineCode=inline_code, codeBlock=code_block, blockQuote=block_quote,
    hideLinkEmbed=hide_link_embed, unorderedList=unordered_list, orderedList=ordered_list,
)
