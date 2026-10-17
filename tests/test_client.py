"""Gateway ve olay akışı testleri."""

from __future__ import annotations

import asyncio

import pytest

from jubbio import (
    ButtonInteraction,
    CommandInteraction,
    EmbedBuilder,
    GatewayError,
    Message,
    ModalSubmitInteraction,
    SelectMenuInteraction,
)

from .conftest import APP_ID, until


async def test_login_identify_and_ready(client, server):
    events = []
    client.on("ready", lambda c: events.append(c))
    token = await client.login("Bot gizli-token")

    assert token == "gizli-token"
    identify = next(p for p in server.received if p["op"] == 2)
    assert identify["d"] == {"token": "Bot gizli-token", "intents": 1 | 512 | 32768, "shard": [0, 1]}
    assert events == [client]
    assert client.user.username == "testbot"
    assert client.application_id == APP_ID
    assert client.rest.application_id == APP_ID
    guild = client.guilds.get("200")
    assert guild.name == "Test Sunucusu"
    assert guild.channels.get("300")["name"] == "genel"
    assert "200" in client.voice.adapters
    assert client.is_ready()


async def test_heartbeat_updates_ping(client, server):
    await client.login("t")
    await until(lambda: client.ping >= 0)
    assert any(p["op"] == 1 for p in server.received)


async def test_non_reconnectable_close_rejects_login(client, server):
    server.close_on_identify = 4004
    with pytest.raises(GatewayError) as info:
        await client.login("yanlis")
    assert info.value.code == 4004
    assert "Geçersiz bot token" in str(info.value)
    assert server.connections == 1


async def test_reconnect_opcode(client, server):
    await client.login("t")
    await server.sockets[-1].send_str('{"op": 7}')
    await until(lambda: server.connections == 2, timeout=5)


async def test_multiple_payloads_in_one_frame(client, server):
    await client.login("t")
    seen = []
    client.on("typingStart", lambda d: seen.append(d["user_id"]))
    await server.sockets[-1].send_str(
        '{"op":0,"t":"TYPING_START","d":{"user_id":"1"}}\n{"op":0,"t":"TYPING_START","d":{"user_id":"2"}}'
    )
    await until(lambda: len(seen) == 2)
    assert seen == ["1", "2"]


async def test_message_create_and_reply(client, server):
    await client.login("t")
    received: asyncio.Future = asyncio.get_running_loop().create_future()

    @client.on("messageCreate")
    async def on_message(message: Message):
        if message.content == "!ping":
            reply = await message.reply("🏓 Pong! <@42>", embeds=[EmbedBuilder().set_title("Başlık")])
            received.set_result((message, reply))

    await server.dispatch("MESSAGE_CREATE", {
        "id": "700", "channel_id": "300", "guild_id": "200", "content": "!ping", "user_id": 7,
        "author": {"username": "ali"}, "member": {"roles": ["5"], "joined_at": "2025-01-01T00:00:00Z"},
        "timestamp": "2026-01-01T10:00:00.000Z",
    })
    message, reply = await asyncio.wait_for(received, 3)

    assert message.author.id == "7"
    assert message.member is not None and message.member.roles == ["5"]
    assert client.guilds.get("200").members.get("7") is message.member
    assert message.channel.name == "genel"
    assert reply.id == "999"

    request = server.find("POST", "/bot/guilds/200/channels/300/messages")[0]
    assert request["headers"]["Authorization"] == "Bot t"
    assert request["json"]["message_reference"] == {"message_id": "700"}
    assert request["json"]["embeds"] == [{"title": "Başlık"}]
    assert request["json"]["mentions"] == {"users": [{"id": 42, "username": "User_42"}]}


async def test_snake_case_event_and_decorator(client, server):
    await client.login("t")
    got = []

    @client.event
    async def on_message_create(message):
        got.append(message.content)

    client.on("guild_member_add", lambda m: got.append(m.display_name))
    await server.dispatch("MESSAGE_CREATE", {"id": "1", "channel_id": "300", "guild_id": "200", "content": "x",
                                             "author": {"id": "8", "username": "veli"}})
    await server.dispatch("GUILD_MEMBER_ADD", {"guild_id": "200", "user": {"id": "9", "username": "ayse"},
                                               "roles": [], "joined_at": "2025-01-01T00:00:00Z"})
    await until(lambda: len(got) == 2)
    assert sorted(got) == ["ayse", "x"]


async def test_slash_command_interaction(client, server):
    await client.login("t")
    done: asyncio.Future = asyncio.get_running_loop().create_future()

    @client.on("interactionCreate")
    async def on_interaction(interaction):
        assert isinstance(interaction, CommandInteraction)
        assert interaction.is_command()
        user = interaction.options.get_user("kullanici", True)
        await interaction.reply(f"Merhaba {user}!", ephemeral=True)
        done.set_result(interaction)

    await server.dispatch("INTERACTION_CREATE", {
        "id": 11, "application_id": APP_ID, "type": 2, "guild_id": "200", "channel_id": "300", "token": "tok",
        "member": {"user": {"id": "7", "username": "ali"}, "roles": [], "joined_at": "2025-01-01T00:00:00Z",
                   "permissions": "8"},
        "data": {"name": "selamla", "options": [{"name": "kullanici", "type": 6, "value": "<@!55>"}],
                 "resolved": {"users": {"55": {"id": "55", "username": "zeynep"}}}},
    })
    interaction = await asyncio.wait_for(done, 3)
    assert interaction.replied
    assert interaction.member.permissions.has("BanMembers")  # Administrator her şeyi kapsar
    request = server.find("POST", "/interactions/11/tok/callback")[0]
    assert request["json"]["type"] == 4
    assert request["json"]["data"]["content"] == "Merhaba <@55>!"
    assert request["json"]["data"]["flags"] == 64
    assert request["json"]["data"]["mentions"]["users"][0]["id"] == 55


async def test_defer_and_edit_reply_creates_message(client, server):
    await client.login("t")
    done: asyncio.Future = asyncio.get_running_loop().create_future()

    @client.on("interactionCreate")
    async def on_interaction(interaction):
        await interaction.defer_reply()
        await interaction.edit_reply(content="Bitti")
        done.set_result(True)

    await server.dispatch("INTERACTION_CREATE", {
        "id": "12", "application_id": APP_ID, "type": 2, "guild_id": "200", "channel_id": "300", "token": "tok2",
        "user": {"id": "7", "username": "ali"}, "data": {"name": "uzun"},
    })
    await asyncio.wait_for(done, 3)
    defer = server.find("POST", "/interactions/12/tok2/callback")[0]
    assert defer["json"] == {"type": 5}
    msg = server.find("POST", "/bot/guilds/200/channels/300/messages")[0]
    assert msg["json"] == {"interaction_id": "12", "content": "Bitti"}


async def test_component_and_modal_interactions(client, server):
    await client.login("t")
    seen = []
    client.on("interactionCreate", lambda i: seen.append(i))
    base = {"application_id": APP_ID, "guild_id": "200", "channel_id": "300", "token": "t",
            "user": {"id": "7", "username": "ali"}}
    await server.dispatch("INTERACTION_CREATE", {**base, "id": "1", "type": 3,
                                                 "data": {"custom_id": "btn", "component_type": 2},
                                                 "message": {"id": "77", "channel_id": "300"}})
    await server.dispatch("INTERACTION_CREATE", {**base, "id": "2", "type": 3,
                                                 "data": {"custom_id": "menu", "component_type": 3, "values": ["a"]}})
    await server.dispatch("INTERACTION_CREATE", {**base, "id": "3", "type": 5, "data": {
        "custom_id": "form",
        "values": ['[{"type":1,"components":[{"type":4,"custom_id":"ad","value":"Ahmet"}]}]'],
    }})
    await until(lambda: len(seen) == 3)
    button, menu, modal = seen
    assert isinstance(button, ButtonInteraction) and button.is_button() and button.message.guild_id == "200"
    assert isinstance(menu, SelectMenuInteraction) and menu.values == ["a"]
    assert isinstance(modal, ModalSubmitInteraction) and modal.fields.get_text_input_value("ad") == "Ahmet"

    await button.update("güncellendi")
    request = server.find("POST", "/interactions/1/t/callback")[0]
    assert request["json"] == {"type": 7, "data": {"content": "güncellendi"}}


async def test_voice_state_updates_member_cache(client, server):
    await client.login("t")
    await server.dispatch("VOICE_STATE_UPDATE", {
        "guild_id": "200", "user_id": "7", "channel_id": "301", "self_mute": True,
        "user": {"id": "7", "username": "ali"},
    })
    guild = client.guilds.get("200")
    await until(lambda: guild.members.get("7") is not None)
    member = guild.members.get("7")
    assert member.voice.channel_id == "301" and member.voice.self_mute
    assert member.voice.channelId == "301"  # JS uyumluluğu
    assert member.in_voice_channel


async def test_guild_lifecycle_and_channel_cache(client, server):
    await client.login("t")
    events = []
    for name in ("guildCreate", "guildUpdate", "guildDelete", "channelCreate", "channelDelete"):
        client.on(name, lambda x, n=name: events.append(n))
    await server.dispatch("GUILD_CREATE", {"id": "201", "name": "Yeni"})
    await server.dispatch("GUILD_UPDATE", {"id": "201", "name": "Yeni Ad"})
    await server.dispatch("CHANNEL_CREATE", {"id": "400", "guild_id": "201", "type": 0, "name": "x"})
    await until(lambda: len(events) == 3)
    assert client.guilds.get("201").name == "Yeni Ad"
    assert "400" in client.guilds.get("201").channels
    await server.dispatch("CHANNEL_DELETE", {"id": "400", "guild_id": "201"})
    await server.dispatch("GUILD_DELETE", {"id": "201"})
    await until(lambda: len(events) == 5)
    assert "201" not in client.guilds and "201" not in client.voice.adapters


async def test_unknown_event_emits_raw(client, server):
    await client.login("t")
    raw = []
    client.on("raw", raw.append)
    await server.dispatch("SOMETHING_NEW", {"x": 1})
    await until(lambda: raw)
    assert raw[0] == {"t": "SOMETHING_NEW", "d": {"x": 1}}


async def test_wait_for(client, server):
    await client.login("t")

    async def later():
        await asyncio.sleep(0.05)
        await server.dispatch("MESSAGE_CREATE", {"id": "2", "channel_id": "300", "content": "evet",
                                                 "author": {"id": "8", "username": "u"}})

    asyncio.get_running_loop().create_task(later())
    message = await client.wait_for("messageCreate", lambda m: m.content == "evet", timeout=3)
    assert message.id == "2"
