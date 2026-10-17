"""examples/moderasyon_bot/bot.py için uçtan uca test (sahte sunucuya karşı)."""

from __future__ import annotations

import importlib.util
import os
import sys

import pytest

from .conftest import APP_ID, until

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def mod_module(monkeypatch):
    spec = importlib.util.spec_from_file_location("moderasyon_bot", os.path.join(ROOT, "examples", "moderasyon_bot", "bot.py"))
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "moderasyon_bot", module)
    spec.loader.exec_module(module)
    return module


ADMIN = {"user": {"id": "1", "username": "sahip"}, "roles": [], "joined_at": "2025-01-01T00:00:00Z", "permissions": "8"}
MOD = {"user": {"id": "50", "username": "mod"}, "roles": ["900"], "joined_at": "2025-01-01T00:00:00Z"}
USER = {"user": {"id": "7", "username": "ali"}, "roles": [], "joined_at": "2025-01-01T00:00:00Z"}


def command(i, member, name, options=(), sub=None):
    opts = [{"name": sub, "type": 1, "options": list(options)}] if sub else list(options)
    return {"id": str(i), "application_id": APP_ID, "guild_id": "200", "channel_id": "300", "token": f"t{i}",
            "member": member, "type": 2, "data": {"name": name, "options": opts}}


def opt(name, value, kind=3):
    return {"name": name, "type": kind, "value": value}


def test_parse_duration(mod_module):
    p = mod_module.parse_duration
    assert p("10dk") == 600 and p("1sa30dk") == 5400 and p("2g") == 172800 and p("45s") == 45
    assert p("1hf") == 604800 and p("15") == 900 and p("abc") is None and p("10x") is None
    assert mod_module.fmt_duration(5400) == "1 saat 30 dakika"


async def test_moderation_flow(server, tmp_path, mod_module):
    server.responses["PUT /applications/5000/commands"] = []
    bot = mod_module.ModerationBot(str(tmp_path / "mod.json"), gateway_url=server.gateway_url,
                                   api_url=server.api_url, ready_timeout=5)
    client = bot.client
    i = 0

    async def send(member, name, options=(), sub=None):
        nonlocal i
        i += 1
        await server.dispatch("INTERACTION_CREATE", command(i, member, name, options, sub))
        await until(lambda: server.find("POST", f"/interactions/{i}/"), timeout=5)
        body = server.find("POST", f"/interactions/{i}/")[-1]["json"]
        data = body.get("data") or body
        return (data.get("embeds") or [{}])[0].get("description", "")

    def msgs(channel):
        return [r for r in server.find("POST", f"/bot/guilds/200/channels/{channel}/messages") if r.get("json")]

    try:
        await client.login("t")
        await until(lambda: server.find("PUT", "/applications/5000/commands"))
        commands = {c["name"]: c for c in server.find("PUT", "/applications/5000/commands")[0]["json"]}
        assert commands["ban"]["default_member_permissions"] == str(1 << 2)

        # Yetkisiz kullanıcı
        assert "yetkin yok" in await send(USER, "ban", [opt("kullanici", "8", 6)])

        await send(ADMIN, "ayarla", [opt("kanal", "301", 7)], sub="log")
        await send(ADMIN, "ayarla", [opt("kanal", "302", 7)], sub="mesaj-log")
        await send(ADMIN, "ayarla", [opt("rol", "900", 8)], sub="mod-rol")

        # Süreli ban (mod rolüyle)
        text = await send(MOD, "ban", [opt("kullanici", "7", 6), opt("sebep", "spam"), opt("sure", "1g")])
        assert "yasaklandı (1 gün)" in text and "Vaka #1" in text
        ban = server.find("PUT", "/bot/guilds/200/bans/7")[0]["json"]
        assert ban["reason"] == "spam (Yetkili: 50)"
        assert server.find("POST", "/bot/dm")[0]["json"]["recipient_user_id"] == "7"
        assert bot.store.guild("200")["tempbans"][0]["user_id"] == "7"
        assert "Süreli Ban | Vaka #1" in msgs("301")[-1]["json"]["embeds"][0]["title"]

        # Hedef kontrolleri
        assert "Kendine" in await send(MOD, "kick", [opt("kullanici", "50", 6)])
        assert "Sunucu sahibine" in await send(MOD, "kick", [opt("kullanici", "1", 6)])
        assert "Geçersiz süre" in await send(MOD, "sustur", [opt("kullanici", "8", 6), opt("sure", "çok")])

        await send(MOD, "sustur", [opt("kullanici", "8", 6), opt("sure", "10dk")])
        assert server.find("POST", "/bot/guilds/200/members/8/timeout")[0]["json"]["until"].endswith("Z")

        # 3 uyarı -> otomatik 1 saat susturma
        for n in range(3):
            await send(MOD, "uyari", [opt("kullanici", "9", 6), opt("sebep", f"kural {n}")], sub="ver")
        await until(lambda: server.find("POST", "/bot/guilds/200/members/9/timeout"))
        cases = bot.store.guild("200")["cases"]
        assert [c["type"] for c in cases[-4:]] == ["warn", "warn", "warn", "timeout"]
        assert cases[-1]["mod_id"] == "automod" and cases[-1]["seconds"] == 3600

        await send(MOD, "uyari", [opt("vaka", cases[-2]["id"], 4)], sub="sil")
        assert len(bot.active_warnings("200", "9")) == 2

        # Toplu silme (kullanıcı filtresi)
        server.responses["GET /bot/guilds/200/channels/300/messages"] = {"messages": [
            {"id": "31", "author": {"id": "9"}}, {"id": "30", "author": {"id": "5"}},
            {"id": "29", "author": {"id": "9"}}, {"id": "28", "author": {"id": "9"}}]}
        await send(MOD, "temizle", [opt("miktar", 2, 4), opt("kullanici", "9", 6)])
        assert server.find("POST", "/messages/bulk-delete")[0]["json"] == {"messages": ["31", "29"]}

        # Kilit / kilit aç
        await send(ADMIN, "kilit")
        await send(ADMIN, "kilit-ac")
        locks = server.find("PUT", "/bot/channels/300/permissions/200")
        assert locks[0]["json"]["deny"] == str(1 << 11) and locks[1]["json"]["deny"] == "0"

        # AutoMod: yasaklı kelime -> sil + uyarı
        await send(ADMIN, "automod", [opt("acik", True, 5)], sub="durum")
        await send(ADMIN, "automod", [opt("kelime", "kotu, çok kötü")], sub="kelime-ekle")
        await server.dispatch("MESSAGE_CREATE", {"id": "40", "channel_id": "300", "guild_id": "200",
                                                 "content": "Bu KOTU bir mesaj", "author": {"id": "11", "username": "x"}})
        await until(lambda: server.find("DELETE", "/channels/300/messages/40"))
        await until(lambda: bot.active_warnings("200", "11"))
        assert "Yasaklı kelime" in bot.active_warnings("200", "11")[0]["reason"]

        # Davet linki (varsayılan açık)
        await server.dispatch("MESSAGE_CREATE", {"id": "41", "channel_id": "300", "guild_id": "200",
                                                 "content": "gel discord.gg/abc", "author": {"id": "12", "username": "y"}})
        await until(lambda: server.find("DELETE", "/channels/300/messages/41"))

        # Spam: 3 mesaj / 5 sn -> susturma
        await send(ADMIN, "automod", [opt("spam_mesaj", 3, 4), opt("spam_saniye", 5, 4)], sub="filtre")
        for n in range(3):
            await server.dispatch("MESSAGE_CREATE", {"id": f"5{n}", "channel_id": "300", "guild_id": "200",
                                                     "content": "selam", "author": {"id": "13", "username": "z"}})
        await until(lambda: server.find("POST", "/bot/guilds/200/members/13/timeout"))

        # Yetkili muaf
        await server.dispatch("MESSAGE_CREATE", {"id": "60", "channel_id": "300", "guild_id": "200", "content": "kotu",
                                                 "author": {"id": "50", "username": "mod"}, "member": {"roles": ["900"]}})
        # Silinen mesaj kaydı
        await server.dispatch("MESSAGE_CREATE", {"id": "70", "channel_id": "300", "guild_id": "200",
                                                 "content": "gizli bilgi", "author": {"id": "14", "username": "w"}})
        await until(lambda: "70" in bot.messages)
        await server.dispatch("MESSAGE_DELETE", {"id": "70", "channel_id": "300", "guild_id": "200"})
        await until(lambda: msgs("302"))
        fields = {f["name"]: f["value"] for f in msgs("302")[-1]["json"]["embeds"][0]["fields"]}
        assert fields["İçerik"] == "gizli bilgi"
        assert not server.find("DELETE", "/channels/300/messages/60")

        # Sicil ve kalıcılık
        await send(MOD, "sicil", [opt("kullanici", "9", 6)])
        sicil = server.find("POST", f"/interactions/{i}/")[-1]["json"]["data"]["embeds"][0]
        assert "Uyarı: 3" in sicil["fields"][0]["value"] and "Susturma: 1" in sicil["fields"][0]["value"]
        reloaded = mod_module.Storage(str(tmp_path / "mod.json"))
        assert reloaded.guild("200")["mod_role"] == "900"
        assert len(reloaded.guild("200")["cases"]) == len(bot.store.guild("200")["cases"])
    finally:
        await client.destroy()
