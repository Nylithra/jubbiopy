"""Kullanıcı yapısı."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Mapping, Optional, Sequence, Union

from .._utils import CamelCaseCompat, to_json

if TYPE_CHECKING:
    from ..client import Client


class User(CamelCaseCompat):
    """Bir Jubbio kullanıcısı."""

    def __init__(self, data: Mapping[str, Any], client: Optional["Client"] = None) -> None:
        self.client = client
        # Snowflake hassasiyet sorunu nedeniyle ID her zaman string tutulur
        self.id: str = str(data.get("id"))
        self.username: str = data.get("username") or f"User_{self.id}"
        self.display_name: Optional[str] = data.get("display_name")
        self.avatar_url: Optional[str] = data.get("avatar_url")
        self.bot: bool = bool(data.get("bot") or False)

    @property
    def tag(self) -> str:
        return self.username

    @property
    def default_avatar_url(self) -> str:
        try:
            index = int(self.id) % 5
        except ValueError:
            index = 0
        return f"https://cdn.jubbio.com/embed/avatars/{index}.png"

    def display_avatar_url(self) -> str:
        return self.avatar_url or self.default_avatar_url

    @property
    def mention(self) -> str:
        return f"<@{self.id}>"

    def __str__(self) -> str:
        return self.mention

    def __repr__(self) -> str:
        return f"<User id={self.id} username={self.username!r}>"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, User) and other.id == self.id

    def __hash__(self) -> int:
        return hash(("user", self.id))

    def _patch(self, data: Mapping[str, Any]) -> None:
        if "username" in data:
            self.username = data["username"]
        if "display_name" in data:
            self.display_name = data["display_name"]
        if "avatar_url" in data:
            self.avatar_url = data["avatar_url"]
        if "bot" in data:
            self.bot = bool(data["bot"])

    async def send(
        self,
        content: Union[str, Mapping[str, Any], None] = None,
        *,
        embeds: Optional[Sequence[Any]] = None,
        components: Optional[Sequence[Any]] = None,
        files: Optional[Sequence[Any]] = None,
    ) -> Any:
        """Bu kullanıcıya doğrudan mesaj (DM) gönderir.

        Örnek::

            await user.send("Merhaba!")
            await user.send(embeds=[embed])
            await user.send(files=[File("test.txt", b"merhaba")])
        """
        if self.client is None:
            raise RuntimeError("DM gönderilemiyor: User nesnesi client referansı olmadan oluşturulmuş")
        if isinstance(content, Mapping):
            opts = dict(content)
            content = opts.get("content")
            embeds = embeds or opts.get("embeds")
            components = components or opts.get("components")
            files = files or opts.get("files")
        data = {
            "content": content,
            "embeds": to_json(list(embeds)) if embeds else None,
            "components": to_json(list(components)) if components else None,
        }
        if files:
            return await self.client.rest.create_dm_message_with_file(self.id, data, list(files))
        return await self.client.rest.create_dm_message(self.id, data)
