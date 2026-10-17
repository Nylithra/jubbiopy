"""examples/ticket_bot/bot.py için uçtan uca test (sahte sunucuya karşı)."""

from __future__ import annotations

import importlib.util
import os

import pytest

from .conftest import APP_ID, until

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def ticket_module(monkeypatch):
    spec = importlib.util.spec_from_file_location("ticket_bot", os.path.join(ROOT, "examples", "ticket_bot", "bot.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "DELETE_DELAY", 0)
    return module


ADMIN = {"user": {"id": "1", "username": "sahip"}, "roles": [], "joined_at": "2025-01-01T00:00:00Z", "permissions": "8"}
STAFF = {"user": {"id": "50", "username": "yetkili"}, "roles": ["900"], "joined_at": "2025-01-01T00:00:00Z"}
USER = {"user": {"id": "7", "username": "ali"}, "roles": [], "joined_at": "2025-01-01T00:00:00Z"}


def interaction(i, member, channel="300", **data):
    return {"id": str(i), "application_id": APP_ID, "guild_id": "200", "channel_id": channel,
            "token": f"tok{i}", "member": member, **data}


def command(i, member, name, sub, options=(), channel="300"):
    return interaction(i, member, channel, type=2, data={
        "name": name, "options": [{"name": sub, "type": 1, "options": list(options)}]})


def button(i, member, custom_id, channel="300"):
    return interaction(i, member, channel, type=3, data={"custom_id": custom_id, "component_type": 2},
                       message={"id": "m1", "channel_id": channel})


async def test_full_ticket_flow(server, tmp_path, ticket_module):
    server.responses["POST /bot/guilds/200/channels"] = {"id": "555", "name": "destek-0001"}
    server.responses["PUT /applications/5000/commands"] = []
    server.responses["GET /bot/guilds/200/channels/555/messages"] = {"messages": [
        {"id": "11", "content": "ikinci", "author": {"username": "yetkili"}, "timestamp": "2026-01-01T10:01:00Z"},
        {"id": "10", "content": "merhaba", "author": {"username": "ali"}, "timestamp": "2026-01-01T10:00:00Z",
         "attachments": [{"url": "http://x/a.png"}]},
    ]}
    bot = ticket_module.TicketBot(str(tmp_path / "data.json"), gateway_url=server.gateway_url,
                                  api_url=server.api_url, ready_timeout=5)
    client = bot.client
    try:
        await client.login("t")
        await until(lambda: server.find("PUT", "/applications/5000/commands"))
        names = [c["name"] for c in server.find("PUT", "/applications/5000/commands")[0]["json"]]
        assert names == ["ayarla", "ticket-panel", "ticket"]

        async def send(payload, path):
            before = len(server.find("POST", path))
            await server.dispatch("INTERACTION_CREATE", payload)
            await until(lambda: len(server.find("POST", path)) > before, timeout=5)
            return server.find("POST", path)[-1]["json"]

        # Normal kullanıcı ayar yapamaz
        resp = await send(command(1, USER, "ayarla", "goster"), "/interactions/1/")
        assert "Sunucuyu Yönet" in resp["data"]["embeds"][0]["description"]

        # Kurulum
        resp = await send(command(2, ADMIN, "ayarla", "ticket", [
            {"name": "yetkili_rol", "type": 8, "value": "900"},
            {"name": "kategori", "type": 7, "value": "800"},
            {"name": "log_kanal", "type": 7, "value": "301"},
        ]), "/interactions/2/")
        assert resp["data"]["flags"] == 64
        await send(command(3, ADMIN, "ayarla", "hosgeldin", [{"name": "kanal", "type": 7, "value": "300"}]), "/interactions/3/")
        await send(command(4, ADMIN, "ayarla", "otorol", [{"name": "rol", "type": 8, "value": "901"}]), "/interactions/4/")

        # Panel
        await send(command(5, ADMIN, "ticket-panel", "x"), "/interactions/5/")
        panel = [r for r in server.find("POST", "/bot/guilds/200/channels/300/messages") if r["json"].get("components")][-1]
        assert panel["json"]["components"][0]["components"][0]["custom_id"] == "ticket:category"

        # Ticket aç: buton -> modal -> kanal
        resp = await send(button(6, USER, "ticket:open"), "/interactions/6/")
        assert resp["type"] == 9 and resp["data"]["custom_id"] == "ticket:modal:destek"

        await server.dispatch("INTERACTION_CREATE", interaction(7, USER, type=5, data={
            "custom_id": "ticket:modal:destek",
            "components": [{"type": 1, "components": [{"type": 4, "custom_id": "konu", "value": "Ödeme sorunu"}]}],
        }))
        await until(lambda: server.find("POST", "/bot/guilds/200/channels/555/messages"), timeout=5)
        create = next(r["json"] for r in server.requests if r["method"] == "POST" and r["path"] == "/bot/guilds/200/channels")
        assert create["name"] == "destek-0001" and create["category_id"] == "800"
        overwrites = {o["id"]: o for o in create["permission_overwrites"]}
        assert overwrites["200"]["deny"] == str(1 << 10)  # @everyone göremez
        assert overwrites["7"]["type"] == 1 and overwrites["900"]["type"] == 0
        welcome = server.find("POST", "/bot/guilds/200/channels/555/messages")[0]["json"]
        assert welcome["content"] == "<@7> <@&900>"
        assert {"id": "900"} in welcome["mentions"]["roles"]
        assert "555" in bot.store.guild("200")["tickets"]

        # İkinci ticket limit nedeniyle reddedilir
        resp = await send(button(8, USER, "ticket:open"), "/interactions/8/")
        assert "Zaten açık ticket" in resp["data"]["embeds"][0]["description"]

        # Kullanıcı ekle, sahiplen
        await send(command(9, USER, "ticket", "ekle", [{"name": "kullanici", "type": 6, "value": "77"}], channel="555"),
                   "/interactions/9/")
        assert server.find("PUT", "/bot/channels/555/permissions/77")[0]["json"]["type"] == 1
        resp = await send(button(10, USER, "ticket:claim", channel="555"), "/interactions/10/")
        assert "yetkililer" in resp["data"]["embeds"][0]["description"]
        await send(button(11, STAFF, "ticket:claim", channel="555"), "/interactions/11/")
        assert bot.store.ticket("200", "555")["claimed_by"] == "50"

        # Kapat: onay -> döküm -> log + DM -> kanal silme
        resp = await send(button(12, USER, "ticket:close", channel="555"), "/interactions/12/")
        assert resp["data"]["components"][0]["components"][0]["custom_id"] == "ticket:close_confirm"
        await server.dispatch("INTERACTION_CREATE", button(13, STAFF, "ticket:close_confirm", channel="555"))
        await until(lambda: server.find("DELETE", "/bot/guilds/200/channels/555"), timeout=5)
        log_msg = [r for r in server.find("POST", "/bot/guilds/200/channels/301/messages") if "form" in r][-1]
        name, content = log_msg["form"]["files"]
        transcript = content.decode()
        assert name == "ticket-0001.txt"
        assert transcript.index("ali: merhaba [Dosya: http://x/a.png]") < transcript.index("yetkili: ikinci")
        dm = server.find("POST", "/bot/dm")[-1]
        assert dm["form"]["recipient_user_id"] == "7"
        assert "555" not in bot.store.guild("200")["tickets"]
        assert bot.store.guild("200")["stats"] == {"opened": 1, "closed": 1}

        # Hoş geldin + oto-rol
        await server.dispatch("GUILD_MEMBER_ADD", {"guild_id": "200", "user": {"id": "99", "username": "yeni"},
                                                   "roles": [], "joined_at": "2026-01-01T00:00:00Z"})
        await until(lambda: server.find("PUT", "/bot/guilds/200/members/99/roles/901"), timeout=5)
        await until(lambda: any(r["json"] and r["json"].get("content") == "<@99>"
                                for r in server.find("POST", "/bot/guilds/200/channels/300/messages")), timeout=5)

        # Ayarlar kalıcı
        reloaded = ticket_module.Storage(str(tmp_path / "data.json"))
        assert reloaded.guild("200")["staff_role"] == "900"
    finally:
        await client.destroy()
