"""REST istemcisi testleri."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from jubbio import REST, EmbedBuilder, File, HTTPException


@pytest.fixture
async def rest(server):
    api = REST(server.api_url).set_token("tok")
    api.set_application_id("5000")
    yield api
    await api.close()


def test_process_mentions_uses_cache():
    api = REST()
    api.cache_user({"id": "42", "username": "ali"})
    result = api.process_mentions("Selam <@42> ve <@!43>, <@&9> @everyone")
    assert result["content"] == "Selam <@42> ve <@!43>, <@&9> @everyone"
    assert result["mentions"] == {
        "users": [{"id": 42, "username": "ali"}, {"id": 43, "username": "User_43"}],
        "roles": [{"id": "9"}],
        "everyone": True,
    }


def test_prepare_message_data_normalizes_embeds():
    api = REST()
    when = datetime(2026, 1, 2, 3, 4, 5, 678000, tzinfo=timezone.utc)
    data = api.prepare_message_data({
        "content": "hi",
        "embeds": [
            EmbedBuilder().set_description("<@1>").set_footer({"text": "<@2>", "iconURL": "http://i"}),
            {"title": "x", "color": "#ff0000", "timestamp": when, "thumbnail": "http://t",
             "author": {"name": "a", "iconURL": "http://a"}, "fields": [{"name": "<@&3>", "value": "v"}]},
        ],
    })
    first, second = data["embeds"]
    assert first["footer"] == {"text": "<@2>", "icon_url": "http://i"}
    assert second["color"] == 0xFF0000
    assert second["timestamp"] == "2026-01-02T03:04:05.678Z"
    assert second["thumbnail"] == {"url": "http://t"}
    assert second["author"] == {"name": "a", "icon_url": "http://a"}
    assert data["mentions"] == {"users": [{"id": 1, "username": "User_1"}, {"id": 2, "username": "User_2"}],
                                "roles": [{"id": "3"}]}


def test_validate_emoji():
    assert REST.validate_emoji(" :thumbsup: ") == ":thumbsup:"
    assert REST.validate_emoji("<a:dance:123>") == "<a:dance:123>"
    with pytest.raises(ValueError):
        REST.validate_emoji("👍")


async def test_endpoints(rest, server):
    await rest.add_reaction("1", "2", "3", "<:ok:55>")
    await rest.kick_member("1", "2", "kural ihlali")
    await rest.ban_member("1", "2", delete_message_days=7, reason="spam")
    await rest.timeout_member("1", "2", 60_000, "sus")
    await rest.timeout_member("1", "2", None)
    await rest.create_channel("1", {"name": "yeni", "parent_id": "9"})
    await rest.get_members("1", limit=10)
    await rest.bulk_overwrite_global_commands([{"name": "ping", "description": "Pong"}])
    await rest.create_ephemeral_message("1", "2", "77", {"content": "gizli"})
    await rest.create_dm_message("77", {"content": "dm"})

    paths = [(r["method"], r["path"]) for r in server.requests]
    assert ("PUT", "/bot/guilds/1/channels/2/messages/3/reactions/<:ok:55>/@me") in paths
    kick = server.find("DELETE", "/bot/guilds/1/members/2")[0]
    assert kick["query"] == {"reason": "kural ihlali"}
    ban = server.find("PUT", "/bot/guilds/1/bans/2")[0]
    assert ban["json"] == {"delete_message_days": 7, "delete_message_seconds": None, "reason": "spam"}
    timeout = server.find("POST", "/members/2/timeout")[0]
    assert timeout["json"]["until"].endswith("Z") and timeout["json"]["reason"] == "sus"
    assert server.find("POST", "/members/2/timeout/clear")
    assert server.find("POST", "/bot/guilds/1/channels")[0]["json"] == {"name": "yeni", "type": 0, "category_id": "9"}
    assert server.find("GET", "/bot/guilds/1/members")[0]["query"] == {"flat": "true", "limit": "10"}
    assert server.find("PUT", "/applications/5000/commands")[0]["json"] == [{"name": "ping", "description": "Pong"}]
    eph = server.find("POST", "/bot/guilds/1/channels/2/messages")[0]["json"]
    assert eph == {"content": "gizli", "flags": 64, "target_user_id": 77}
    assert server.find("POST", "/bot/dm")[0]["json"] == {"content": "dm", "recipient_user_id": "77"}


async def test_file_upload(rest, server):
    await rest.create_message_with_file("1", "2", {
        "content": "dosya", "embeds": [EmbedBuilder().set_title("t")], "file": File("a.txt", "merhaba"),
        "interaction_id": "44",
    })
    form = server.find("POST", "/bot/guilds/1/channels/2/messages")[0]["form"]
    assert form["content"] == "dosya"
    assert form["embeds"] == '[{"title": "t"}]'
    assert form["interaction_id"] == "44"
    assert form["files"] == ("a.txt", b"merhaba")


async def test_followup_with_files(rest, server):
    await rest.create_followup("tok", {"content": "x", "flags": 64, "files": [{"name": "b.bin", "data": b"\x00\x01"}]})
    form = server.find("POST", "/interactions/webhooks/5000/tok")[0]["form"]
    assert form["files[0]"] == ("b.bin", b"\x00\x01") and form["flags"] == "64"


async def test_get_messages_and_errors(rest, server):
    server.responses["GET /bot/guilds/1/channels/2/messages"] = {"messages": [{"id": "1"}]}
    assert await rest.get_messages("1", "2", limit=5, before="9") == [{"id": "1"}]
    assert server.requests[-1]["query"] == {"limit": "5", "before": "9"}

    rest.base_url = rest.base_url.replace("/api/v1", "/yok")
    with pytest.raises(HTTPException) as info:
        await rest.get_user("1")
    assert info.value.status == 404


def test_camel_case_aliases():
    api = REST()
    assert api.createMessage == api.create_message
    assert api.setToken("x") is api
