"""Jubbio REST API istemcisi (``@jubbio/core`` REST sınıfının Python karşılığı)."""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Union
from urllib.parse import quote, urlencode

import aiohttp

from ._utils import CamelCaseCompat, iso_timestamp, normalize_embed, to_int_id, to_json
from .errors import HTTPException

log = logging.getLogger("jubbiopy.rest")

DEFAULT_API_URL = "https://gateway.jubbio.com/api/v1"
USER_AGENT = "JubbioBot/1.0 (+https://jubbio.com) jubbiopy"
USER_CACHE_TTL = 5 * 60  # saniye

_USER_MENTION_RE = re.compile(r"<@!?(\d+)>")
_ROLE_MENTION_RE = re.compile(r"<@&(\d+)>")
_CUSTOM_EMOJI_RE = re.compile(r"^<a?:\w+:\d+>$")
_NAMED_EMOJI_RE = re.compile(r"^:\w+:$")


@dataclass
class File:
    """Yüklenecek dosya.

    ``data`` bytes veya str olabilir. ``File.from_path("resim.png")`` ile
    diskten de oluşturulabilir.
    """

    name: str
    data: Union[bytes, str]
    content_type: Optional[str] = None

    @classmethod
    def from_path(cls, path: str, name: Optional[str] = None, content_type: Optional[str] = None) -> "File":
        import mimetypes
        import os

        with open(path, "rb") as fh:
            data = fh.read()
        filename = name or os.path.basename(path)
        return cls(filename, data, content_type or mimetypes.guess_type(filename)[0])

    @property
    def bytes(self) -> bytes:
        return self.data.encode() if isinstance(self.data, str) else bytes(self.data)


FileLike = Union[File, Mapping[str, Any]]


def resolve_file(file: FileLike) -> File:
    if isinstance(file, File):
        return file
    if isinstance(file, Mapping):
        return File(
            name=file.get("name") or file.get("filename") or "file",
            data=file.get("data") if file.get("data") is not None else file.get("attachment", b""),
            content_type=file.get("content_type") or file.get("contentType"),
        )
    raise TypeError(f"Geçersiz dosya: {file!r}")


class REST(CamelCaseCompat):
    """Jubbio REST API istemcisi. ``client.rest`` üzerinden erişilir."""

    def __init__(self, base_url: Optional[str] = None, *, session: Optional[aiohttp.ClientSession] = None) -> None:
        self.base_url = (base_url or DEFAULT_API_URL).rstrip("/")
        self.token = ""
        self.application_id = ""
        self._session = session
        self._owns_session = session is None
        # Mention çözümleme için kullanıcı önbelleği (ID -> kullanıcı bilgisi)
        self._user_cache: Dict[int, Dict[str, Any]] = {}

    # ================================================================ oturum
    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
            self._owns_session = True
        return self._session

    async def close(self) -> None:
        if self._session is not None and self._owns_session and not self._session.closed:
            await self._session.close()
        self._session = None

    def set_token(self, token: str) -> "REST":
        self.token = token
        return self

    def set_application_id(self, application_id: str) -> None:
        self.application_id = str(application_id)

    def get_application_id(self) -> str:
        if not self.application_id:
            raise RuntimeError("Application ID ayarlanmadı. Önce set_application_id() çağırın.")
        return self.application_id

    # ======================================================= mention yardımcıları
    def cache_user(self, user: Any) -> None:
        """Mention çözümlemesi için bir kullanıcıyı önbelleğe alır."""
        data = user if isinstance(user, Mapping) else vars(user)
        user_id = to_int_id(data.get("id"))
        self._user_cache[user_id] = {
            "id": user_id,
            "username": data.get("username"),
            "display_name": data.get("display_name") or data.get("displayName"),
            "cached_at": time.monotonic(),
        }

    def cache_users(self, users: Iterable[Any]) -> None:
        for user in users:
            self.cache_user(user)

    def get_cached_user(self, user_id: Any) -> Optional[Dict[str, Any]]:
        user_id = to_int_id(user_id)
        cached = self._user_cache.get(user_id)
        if cached and time.monotonic() - cached["cached_at"] < USER_CACHE_TTL:
            return cached
        self._user_cache.pop(user_id, None)
        return None

    def format_mention(self, user: Any) -> Dict[str, Any]:
        data = user if isinstance(user, Mapping) else {"id": user.id, "username": user.username}
        user_id = to_int_id(data["id"])
        return {
            "text": f"<@{user_id}>",
            "data": {"users": [{"id": user_id, "username": data.get("username")}]},
        }

    def process_mentions(self, content: Any, existing: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        """İçerikteki ``<@ID>``, ``<@&ID>`` ve ``@everyone`` mention'larından mentions verisi üretir.

        İçerik olduğu gibi kalır; istemci mention'ları kendisi render eder.
        """
        text = "" if content is None else str(content)
        existing = existing or {}
        users = list(existing.get("users") or [])
        roles = list(existing.get("roles") or [])
        mentions: Dict[str, Any] = {"users": users, "roles": roles}
        if existing.get("everyone") is not None:
            mentions["everyone"] = existing["everyone"]

        seen_users = {u.get("id") for u in users}
        for match in _USER_MENTION_RE.finditer(text):
            user_id = int(match.group(1))
            if user_id not in seen_users:
                cached = self.get_cached_user(user_id)
                users.append({"id": user_id, "username": (cached or {}).get("username") or f"User_{user_id}"})
                seen_users.add(user_id)

        seen_roles = {r.get("id") for r in roles}
        for match in _ROLE_MENTION_RE.finditer(text):
            role_id = match.group(1)
            if role_id not in seen_roles:
                roles.append({"id": role_id})
                seen_roles.add(role_id)

        if "@everyone" in text:
            mentions["everyone"] = True
        if not users:
            del mentions["users"]
        if not roles:
            del mentions["roles"]
        return {"content": text, "mentions": mentions}

    def prepare_message_data(self, data: Mapping[str, Any]) -> Dict[str, Any]:
        """Mesaj verisini API'ye hazırlar: builder'ları JSON'a çevirir, embed'leri
        normalize eder ve mention verisini otomatik oluşturur."""
        result: Dict[str, Any] = {k: v for k, v in data.items() if v is not None}
        if data.get("components"):
            result["components"] = to_json(list(data["components"]))

        mentions: Dict[str, Any] = dict(data.get("mentions") or {})
        if data.get("content"):
            processed = self.process_mentions(data["content"], mentions)
            result["content"] = processed["content"]
            mentions = processed["mentions"]

        if data.get("embeds"):
            embeds = []
            for embed in data["embeds"]:
                emb = normalize_embed(embed)
                for key in ("description", "title"):
                    if emb.get(key):
                        processed = self.process_mentions(emb[key], mentions)
                        emb[key] = processed["content"]
                        mentions = processed["mentions"]
                if isinstance(emb.get("footer"), dict) and emb["footer"].get("text"):
                    processed = self.process_mentions(emb["footer"]["text"], mentions)
                    emb["footer"] = {**emb["footer"], "text": processed["content"]}
                    mentions = processed["mentions"]
                if emb.get("fields"):
                    fields = []
                    for field in emb["fields"]:
                        field = dict(field)
                        for key in ("value", "name"):
                            if field.get(key):
                                processed = self.process_mentions(field[key], mentions)
                                field[key] = processed["content"]
                                mentions = processed["mentions"]
                        fields.append(field)
                    emb["fields"] = fields
                embeds.append(emb)
            result["embeds"] = embeds

        if mentions.get("users") or mentions.get("roles") or mentions.get("everyone"):
            result["mentions"] = mentions
        else:
            result.pop("mentions", None)
        return result

    # ============================================================== istek
    def _headers(self, json_body: bool = True) -> Dict[str, str]:
        headers = {"Authorization": f"Bot {self.token}", "User-Agent": USER_AGENT}
        if json_body:
            headers["Content-Type"] = "application/json"
        return headers

    async def request(self, method: str, path: str, body: Any = None) -> Any:
        """Kimlik doğrulamalı bir API isteği yapar ve JSON yanıtı döndürür."""
        url = f"{self.base_url}{path}"
        log.debug("[REST] %s %s %s", method, url, json.dumps(body, default=str) if body is not None else "")
        session = await self._get_session()
        payload = json.dumps(to_json(body), default=str) if body is not None else None
        async with session.request(method, url, data=payload, headers=self._headers()) as response:
            text = await response.text()
            if response.status >= 400:
                raise HTTPException(response.status, text)
        if not text:
            return {}
        return json.loads(text)

    async def _request_form(self, method: str, path: str, form: aiohttp.FormData, error_prefix: str = "API Error") -> Any:
        url = f"{self.base_url}{path}"
        session = await self._get_session()
        async with session.request(method, url, data=form, headers=self._headers(json_body=False)) as response:
            text = await response.text()
            if response.status >= 400:
                raise HTTPException(response.status, text, prefix=error_prefix)
        return json.loads(text) if text else {}

    def _build_form(
        self,
        data: Mapping[str, Any],
        files: Sequence[FileLike],
        file_field: str = "files",
        indexed: bool = False,
        default_content_type: str = "application/octet-stream",
        leading_fields: Optional[Mapping[str, str]] = None,
    ) -> aiohttp.FormData:
        form = aiohttp.FormData()
        for key, value in (leading_fields or {}).items():
            form.add_field(key, value)
        if data.get("content"):
            form.add_field("content", str(data["content"]))
        if data.get("embeds"):
            form.add_field("embeds", json.dumps([normalize_embed(e) for e in data["embeds"]], default=str))
        if data.get("components"):
            form.add_field("components", json.dumps(to_json(list(data["components"])), default=str))
        for index, raw in enumerate(files):
            file = resolve_file(raw)
            field = f"{file_field}[{index}]" if indexed else file_field
            form.add_field(
                field,
                file.bytes,
                filename=file.name,
                content_type=file.content_type or default_content_type,
            )
        return form

    # ============================================================ mesajlar
    async def create_message(self, guild_id: str, channel_id: str, data: Mapping[str, Any]) -> Any:
        """Bir kanala mesaj gönderir. Mention'lar ``<@ID>`` formatında kalır."""
        if isinstance(channel_id, Mapping):
            raise TypeError("create_message guild_id gerektirir: create_message(guild_id, channel_id, data)")
        message = self.prepare_message_data(data)
        interaction_id = message.pop("interactionId", None) or message.pop("interaction_id", None)
        if interaction_id:
            message["interaction_id"] = interaction_id
        return await self.request("POST", f"/bot/guilds/{guild_id}/channels/{channel_id}/messages", message)

    async def create_ephemeral_message(self, guild_id: str, channel_id: str, target_user_id: Any, data: Mapping[str, Any]) -> Any:
        """Sadece belirli bir kullanıcının görebileceği geçici mesaj gönderir (veritabanına kaydedilmez)."""
        message = self.prepare_message_data(data)
        message["flags"] = 64
        message["target_user_id"] = to_int_id(target_user_id)
        return await self.request("POST", f"/bot/guilds/{guild_id}/channels/{channel_id}/messages", message)

    async def create_dm_message(self, user_id: str, data: Mapping[str, Any]) -> Any:
        """Bir kullanıcıya DM gönderir."""
        message = self.prepare_message_data(data)
        message["recipient_user_id"] = user_id
        return await self.request("POST", "/bot/dm", message)

    async def create_dm_message_to_channel(self, channel_id: str, data: Mapping[str, Any]) -> Any:
        return await self.request("POST", f"/bot/dm/{channel_id}", self.prepare_message_data(data))

    async def create_dm_message_with_file(self, user_id: str, data: Mapping[str, Any], files: Sequence[FileLike]) -> Any:
        """Dosya ekli DM gönderir."""
        form = self._build_form(data, files, leading_fields={"recipient_user_id": str(user_id)})
        return await self._request_form("POST", "/bot/dm", form, error_prefix="DM file upload failed:")

    async def edit_message(self, guild_id: str, channel_id: str, message_id: str, data: Mapping[str, Any]) -> Any:
        path = f"/bot/guilds/{guild_id}/channels/{channel_id}/messages/{message_id}"
        return await self.request("PATCH", path, self.prepare_message_data(data))

    async def delete_message(self, guild_id: str, channel_id: str, message_id: str) -> None:
        await self.request("DELETE", f"/bot/guilds/{guild_id}/channels/{channel_id}/messages/{message_id}")

    @staticmethod
    def validate_emoji(emoji: str) -> str:
        """Emoji formatını doğrular. Kabul edilen: ``:isim:``, ``<:isim:id>``, ``<a:isim:id>``.

        Unicode emoji karakterleri (👍) desteklenmez.
        """
        trimmed = emoji.strip()
        if _CUSTOM_EMOJI_RE.match(trimmed) or _NAMED_EMOJI_RE.match(trimmed):
            return trimmed
        raise ValueError(
            f'Geçersiz emoji formatı: "{emoji}". Kabul edilen formatlar: :emoji_name:, <:name:id>, <a:name:id>'
        )

    async def add_reaction(self, guild_id: str, channel_id: str, message_id: str, emoji: str) -> None:
        encoded = quote(self.validate_emoji(emoji), safe="")
        await self.request("PUT", f"/bot/guilds/{guild_id}/channels/{channel_id}/messages/{message_id}/reactions/{encoded}/@me")

    async def remove_reaction(self, guild_id: str, channel_id: str, message_id: str, emoji: str) -> None:
        encoded = quote(self.validate_emoji(emoji), safe="")
        await self.request("DELETE", f"/bot/guilds/{guild_id}/channels/{channel_id}/messages/{message_id}/reactions/{encoded}/@me")

    async def upload_attachment(self, guild_id: str, channel_id: str, file: FileLike) -> Any:
        f = resolve_file(file)
        form = aiohttp.FormData()
        form.add_field("file", f.bytes, filename=f.name, content_type=f.content_type or "text/plain")
        return await self._request_form("POST", f"/bot/guilds/{guild_id}/channels/{channel_id}/attachments", form)

    async def create_message_with_file(self, guild_id: str, channel_id: str, data: Mapping[str, Any]) -> Any:
        """Dosya ekli mesaj gönderir. ``data["file"]`` (veya ``files``) zorunludur."""
        files = list(data.get("files") or ([data["file"]] if data.get("file") else []))
        form = self._build_form(data, files[:1], default_content_type="text/plain")
        interaction_id = data.get("interaction_id") or data.get("interactionId")
        if interaction_id:
            form.add_field("interaction_id", str(interaction_id))
        return await self._request_form("POST", f"/bot/guilds/{guild_id}/channels/{channel_id}/messages", form)

    # ========================================================= etkileşimler
    async def create_interaction_response(self, interaction_id: str, token: str, data: Mapping[str, Any]) -> None:
        payload = dict(data)
        inner = payload.get("data")
        if isinstance(inner, Mapping) and (inner.get("content") or inner.get("embeds")):
            payload["data"] = self.prepare_message_data(inner)
        elif isinstance(inner, Mapping):
            payload["data"] = to_json({k: v for k, v in inner.items() if v is not None})
        elif inner is None:
            payload.pop("data", None)
        await self.request("POST", f"/interactions/{interaction_id}/{token}/callback", payload)

    async def edit_interaction_response(
        self,
        token: str,
        data: Mapping[str, Any],
        guild_id: Optional[str] = None,
        channel_id: Optional[str] = None,
        interaction_id: Optional[str] = None,
    ) -> None:
        """Orijinal etkileşim yanıtını düzenler.

        Ertelenmiş (deferred) yanıtlar mesaj oluşturmadığı için guild/kanal
        bilgisi varsa ``interaction_id`` ile yeni mesaj oluşturulur.
        """
        files = list(data.get("files") or [])
        processed = self.prepare_message_data({k: v for k, v in data.items() if k != "files"})

        if files and guild_id and channel_id:
            await self.create_message_with_file(guild_id, channel_id, {
                "content": processed.get("content"),
                "embeds": processed.get("embeds"),
                "components": processed.get("components"),
                "file": files[0],
                "interaction_id": interaction_id,
            })
            return

        payload: Dict[str, Any] = {}
        for key in ("content", "embeds", "components", "mentions"):
            if processed.get(key) is not None:
                payload[key] = processed[key]

        if guild_id and channel_id and interaction_id:
            payload = {"interaction_id": interaction_id, **payload}
            await self.request("POST", f"/bot/guilds/{guild_id}/channels/{channel_id}/messages", payload)
            return

        app_id = self.get_application_id()
        await self.request("PATCH", f"/interactions/webhooks/{app_id}/{token}/messages/@original", payload)

    async def delete_interaction_response(self, token: str) -> None:
        app_id = self.get_application_id()
        await self.request("DELETE", f"/interactions/webhooks/{app_id}/{token}/messages/@original")

    async def create_followup(self, token: str, data: Mapping[str, Any]) -> None:
        """Takip mesajı gönderir. Dosyalar multipart/form-data ile yüklenir."""
        app_id = self.get_application_id()
        endpoint = f"/interactions/webhooks/{app_id}/{token}"
        files = list(data.get("files") or [])
        if files:
            form = self._build_form(data, files, file_field="files", indexed=True)
            if data.get("flags"):
                form.add_field("flags", str(int(data["flags"])))
            await self._request_form("POST", endpoint, form, error_prefix="Followup with file failed:")
            return
        await self.request("POST", endpoint, self.prepare_message_data(data))

    # ============================================================== komutlar
    async def register_global_commands(self, commands: Sequence[Any]) -> None:
        app_id = self.get_application_id()
        for command in commands:
            await self.request("POST", f"/applications/{app_id}/commands", to_json(command))

    async def bulk_overwrite_global_commands(self, commands: Sequence[Any]) -> Any:
        app_id = self.get_application_id()
        return await self.request("PUT", f"/applications/{app_id}/commands", to_json(list(commands)))

    async def register_guild_commands(self, guild_id: str, commands: Sequence[Any]) -> None:
        app_id = self.get_application_id()
        for command in commands:
            await self.request("POST", f"/applications/{app_id}/guilds/{guild_id}/commands", to_json(command))

    async def bulk_overwrite_guild_commands(self, guild_id: str, commands: Sequence[Any]) -> Any:
        app_id = self.get_application_id()
        return await self.request("PUT", f"/applications/{app_id}/guilds/{guild_id}/commands", to_json(list(commands)))

    async def delete_global_command(self, command_id: str) -> None:
        await self.request("DELETE", f"/applications/{self.get_application_id()}/commands/{command_id}")

    async def delete_guild_command(self, guild_id: str, command_id: str) -> None:
        await self.request("DELETE", f"/applications/{self.get_application_id()}/guilds/{guild_id}/commands/{command_id}")

    async def list_global_commands(self) -> Any:
        return await self.request("GET", f"/applications/{self.get_application_id()}/commands")

    async def list_guild_commands(self, guild_id: str) -> Any:
        return await self.request("GET", f"/applications/{self.get_application_id()}/guilds/{guild_id}/commands")

    async def get_global_command(self, command_id: str) -> Any:
        return await self.request("GET", f"/applications/{self.get_application_id()}/commands/{command_id}")

    async def get_guild_command(self, guild_id: str, command_id: str) -> Any:
        return await self.request("GET", f"/applications/{self.get_application_id()}/guilds/{guild_id}/commands/{command_id}")

    async def update_global_command(self, command_id: str, data: Any) -> Any:
        return await self.request("PATCH", f"/applications/{self.get_application_id()}/commands/{command_id}", to_json(data))

    async def update_guild_command(self, guild_id: str, command_id: str, data: Any) -> Any:
        return await self.request(
            "PATCH", f"/applications/{self.get_application_id()}/guilds/{guild_id}/commands/{command_id}", to_json(data)
        )

    # ============================================================== kanallar
    async def create_channel(self, guild_id: str, data: Mapping[str, Any]) -> Any:
        """Sunucuda kanal oluşturur. ``type``: 0 = metin, 2 = ses."""
        body: Dict[str, Any] = {"name": data["name"], "type": data.get("type", 0)}
        # Backend parent_id yerine category_id bekliyor
        category = data.get("category_id") or data.get("parent_id")
        if category:
            body["category_id"] = category
        if data.get("permission_overwrites"):
            body["permission_overwrites"] = to_json(data["permission_overwrites"])
        return await self.request("POST", f"/bot/guilds/{guild_id}/channels", body)

    async def delete_channel(self, guild_id: str, channel_id: str) -> None:
        await self.request("DELETE", f"/bot/guilds/{guild_id}/channels/{channel_id}")

    async def delete_category(self, guild_id: str, category_id: str) -> None:
        await self.request("DELETE", f"/bot/guilds/{guild_id}/categories/{category_id}")

    async def edit_channel_permissions(self, channel_id: str, overwrite_id: str, data: Mapping[str, Any]) -> None:
        await self.request("PUT", f"/bot/channels/{channel_id}/permissions/{overwrite_id}", dict(data))

    async def delete_channel_permission(self, channel_id: str, overwrite_id: str) -> None:
        await self.request("DELETE", f"/bot/channels/{channel_id}/permissions/{overwrite_id}")

    async def get_messages(
        self,
        guild_id: str,
        channel_id: str,
        options: Optional[Mapping[str, Any]] = None,
        **kwargs: Any,
    ) -> List[Dict[str, Any]]:
        """Kanaldaki mesajları getirir. ``limit``, ``before``, ``after`` destekler."""
        opts = {**(options or {}), **kwargs}
        params = {k: str(opts[k]) for k in ("limit", "before", "after") if opts.get(k)}
        query = f"?{urlencode(params)}" if params else ""
        response = await self.request("GET", f"/bot/guilds/{guild_id}/channels/{channel_id}/messages{query}")
        if isinstance(response, Mapping):
            return list(response.get("messages") or [])
        return list(response or [])

    # ================================================================ üyeler
    async def get_member(self, guild_id: str, user_id: str) -> Any:
        return await self.request("GET", f"/bot/guilds/{guild_id}/members/{user_id}")

    async def get_members(self, guild_id: str, options: Optional[Mapping[str, Any]] = None, **kwargs: Any) -> Any:
        """Sunucu üyelerini sayfalı getirir (``limit``, ``cursor``)."""
        opts = {**(options or {}), **kwargs}
        params = {"flat": "true"}
        if opts.get("limit"):
            params["limit"] = str(opts["limit"])
        if opts.get("cursor"):
            params["cursor"] = str(opts["cursor"])
        return await self.request("GET", f"/bot/guilds/{guild_id}/members?{urlencode(params)}")

    async def timeout_member(self, guild_id: str, user_id: str, duration: Optional[float], reason: Optional[str] = None) -> None:
        """Üyeye zaman aşımı uygular.

        ``duration`` **milisaniye** cinsindendir (JS kütüphanesiyle aynı);
        ``None`` verilirse zaman aşımı kaldırılır.
        """
        if duration is None:
            await self.request("POST", f"/bot/guilds/{guild_id}/members/{user_id}/timeout/clear", {"reason": reason})
            return
        until = iso_timestamp(time.time() * 1000 + duration)
        await self.request("POST", f"/bot/guilds/{guild_id}/members/{user_id}/timeout", {"until": until, "reason": reason})

    @staticmethod
    def _reason_query(reason: Optional[str]) -> str:
        return f"?reason={quote(reason, safe='')}" if reason else ""

    async def kick_member(self, guild_id: str, user_id: str, reason: Optional[str] = None) -> None:
        await self.request("DELETE", f"/bot/guilds/{guild_id}/members/{user_id}{self._reason_query(reason)}")

    async def ban_member(self, guild_id: str, user_id: str, options: Optional[Mapping[str, Any]] = None, **kwargs: Any) -> None:
        """Üyeyi yasaklar. ``delete_message_days``, ``delete_message_seconds``, ``reason``."""
        opts = {**(options or {}), **kwargs}
        await self.request("PUT", f"/bot/guilds/{guild_id}/bans/{user_id}", {
            "delete_message_days": opts.get("delete_message_days", opts.get("deleteMessageDays")),
            "delete_message_seconds": opts.get("delete_message_seconds", opts.get("deleteMessageSeconds")),
            "reason": opts.get("reason"),
        })

    async def unban_member(self, guild_id: str, user_id: str, reason: Optional[str] = None) -> None:
        await self.request("DELETE", f"/bot/guilds/{guild_id}/bans/{user_id}{self._reason_query(reason)}")

    async def edit_member(self, guild_id: str, user_id: str, data: Mapping[str, Any]) -> Any:
        return await self.request("PATCH", f"/bot/guilds/{guild_id}/members/{user_id}", dict(data))

    async def add_member_role(self, guild_id: str, user_id: str, role_id: str, reason: Optional[str] = None) -> None:
        await self.request("PUT", f"/bot/guilds/{guild_id}/members/{user_id}/roles/{role_id}{self._reason_query(reason)}")

    async def remove_member_role(self, guild_id: str, user_id: str, role_id: str, reason: Optional[str] = None) -> None:
        await self.request("DELETE", f"/bot/guilds/{guild_id}/members/{user_id}/roles/{role_id}{self._reason_query(reason)}")

    async def bulk_assign_roles(self, guild_id: str, assignments: Sequence[Mapping[str, Any]]) -> Any:
        return await self.request("PUT", f"/bot/guilds/{guild_id}/members/roles/assign", {"assignments": list(assignments)})

    async def bulk_remove_roles(self, guild_id: str, removals: Sequence[Mapping[str, Any]]) -> Any:
        return await self.request("DELETE", f"/bot/guilds/{guild_id}/members/roles/remove", {"removals": list(removals)})

    async def bulk_delete_messages(self, guild_id: str, channel_id: str, message_ids: Sequence[str]) -> None:
        await self.request("POST", f"/bot/guilds/{guild_id}/channels/{channel_id}/messages/bulk-delete", {"messages": list(message_ids)})

    # =============================================================== sunucular
    async def get_guild(self, guild_id: str) -> Any:
        """Güncel sunucu bilgisini (canlı member_count / online_count) getirir."""
        return await self.request("GET", f"/bot/guilds/{guild_id}")

    async def get_guild_channels(self, guild_id: str) -> Any:
        return await self.request("GET", f"/bot/guilds/{guild_id}/channels")

    async def get_roles(self, guild_id: str) -> Any:
        return await self.request("GET", f"/bot/guilds/{guild_id}/roles")

    async def create_role(self, guild_id: str, data: Mapping[str, Any]) -> Any:
        return await self.request("POST", f"/bot/guilds/{guild_id}/roles", dict(data))

    async def edit_role(self, guild_id: str, role_id: str, data: Mapping[str, Any]) -> Any:
        return await self.request("PATCH", f"/bot/guilds/{guild_id}/roles/{role_id}", dict(data))

    async def delete_role(self, guild_id: str, role_id: str) -> None:
        await self.request("DELETE", f"/bot/guilds/{guild_id}/roles/{role_id}")

    async def get_emojis(self, guild_id: str) -> Any:
        return await self.request("GET", f"/bot/guilds/{guild_id}/emojis")

    async def get_bans(self, guild_id: str) -> Any:
        return await self.request("GET", f"/bot/guilds/{guild_id}/bans")

    async def get_ban(self, guild_id: str, user_id: str) -> Any:
        return await self.request("GET", f"/bot/guilds/{guild_id}/bans/{user_id}")

    async def get_guild_invites(self, guild_id: str) -> Any:
        return await self.request("GET", f"/bot/guilds/{guild_id}/invites")

    # =========================================================== sabitlemeler
    async def pin_message(self, guild_id: str, channel_id: str, message_id: str) -> None:
        await self.request("PUT", f"/bot/guilds/{guild_id}/channels/{channel_id}/pins/{message_id}")

    async def unpin_message(self, guild_id: str, channel_id: str, message_id: str) -> None:
        await self.request("DELETE", f"/bot/guilds/{guild_id}/channels/{channel_id}/pins/{message_id}")

    async def get_pinned_messages(self, guild_id: str, channel_id: str) -> Any:
        return await self.request("GET", f"/bot/guilds/{guild_id}/channels/{channel_id}/pins")

    # ============================================================ kullanıcılar
    async def get_user(self, user_id: str) -> Any:
        return await self.request("GET", f"/bot/users/{user_id}")

    async def get_current_user(self) -> Any:
        return await self.request("GET", "/bot/users/@me")

    # ================================================================ davetler
    async def create_invite(self, guild_id: str, channel_id: str, data: Optional[Mapping[str, Any]] = None) -> Any:
        return await self.request("POST", f"/bot/guilds/{guild_id}/channels/{channel_id}/invites", dict(data or {}))

    async def delete_invite(self, invite_code: str) -> None:
        await self.request("DELETE", f"/bot/invites/{invite_code}")

    async def get_invite(self, invite_code: str) -> Any:
        return await self.request("GET", f"/bot/invites/{invite_code}")

    # ================================================================ webhook
    async def get_channel_webhooks(self, guild_id: str, channel_id: str) -> Any:
        return await self.request("GET", f"/bot/guilds/{guild_id}/channels/{channel_id}/webhooks")

    async def get_guild_webhooks(self, guild_id: str) -> Any:
        return await self.request("GET", f"/bot/guilds/{guild_id}/webhooks")

    async def create_webhook(self, guild_id: str, channel_id: str, data: Mapping[str, Any]) -> Any:
        return await self.request("POST", f"/bot/guilds/{guild_id}/channels/{channel_id}/webhooks", dict(data))

    async def update_webhook(self, guild_id: str, webhook_id: str, data: Mapping[str, Any]) -> Any:
        return await self.request("PATCH", f"/bot/guilds/{guild_id}/webhooks/{webhook_id}", dict(data))

    async def delete_webhook(self, guild_id: str, webhook_id: str) -> Any:
        return await self.request("DELETE", f"/bot/guilds/{guild_id}/webhooks/{webhook_id}")

    # ======================================================= genel HTTP metotları
    async def get(self, path: str) -> Any:
        return await self.request("GET", path)

    async def post(self, path: str, body: Any = None) -> Any:
        return await self.request("POST", path, body)

    async def patch(self, path: str, body: Any = None) -> Any:
        return await self.request("PATCH", path, body)

    async def put(self, path: str, body: Any = None) -> Any:
        return await self.request("PUT", path, body)

    async def delete(self, path: str) -> Any:
        return await self.request("DELETE", path)
