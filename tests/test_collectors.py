"""Collector testleri."""

from __future__ import annotations

import asyncio

import pytest

from jubbio import CollectorEnded, MessageCollector, TextChannel, await_messages

from .conftest import APP_ID, until


def _msg(i: int, author: str = "7", channel: str = "300"):
    return {"id": str(i), "channel_id": channel, "guild_id": "200", "content": f"m{i}",
            "author": {"id": author, "username": "u"}}


async def test_message_collector_max_and_filters(client, server):
    await client.login("t")
    collector = MessageCollector(client, "300", max=2, filter=lambda m, _c: m.content != "m3")
    for i, (author, channel) in enumerate([("7", "300"), ("1000", "300"), ("7", "999"), ("7", "300"),
                                           ("7", "300")], start=0):
        await server.dispatch("MESSAGE_CREATE", _msg(i, author, channel))
    collected, reason = await asyncio.wait_for(collector.wait(), 3)
    assert reason == "limit"
    # m1: bot'un kendi mesajı, m2: başka kanal, m3: filtreye takılır -> m0 ve m4 toplanır
    assert list(collected.keys()) == ["0", "4"]
    assert client.listener_count("messageCreate") == 0


async def test_await_messages_time_error(client, server):
    await client.login("t")
    channel = TextChannel(client, {"id": "300", "guild_id": "200", "type": 0})
    with pytest.raises(CollectorEnded) as info:
        await channel.await_messages(max=1, time=0.1, errors=["time"])
    assert info.value.reason == "time"

    with pytest.raises(CollectorEnded):
        await await_messages(client, "300", max=1, time=0.1)


async def test_idle_and_async_iteration(client, server):
    await client.login("t")
    collector = MessageCollector(client, "300", idle=0.3)
    got = []

    async def produce():
        for i in range(3):
            await server.dispatch("MESSAGE_CREATE", _msg(i))
            await asyncio.sleep(0.05)

    asyncio.get_running_loop().create_task(produce())
    async for message in collector:
        got.append(message.id)
    assert got == ["0", "1", "2"]
    assert collector.end_reason == "idle"


async def test_message_component_collector(client, server):
    await client.login("t")
    from jubbio import Message

    message = Message(client, {"id": "77", "channel_id": "300", "guild_id": "200"})
    waiter = asyncio.get_running_loop().create_task(message.await_message_component(time=3))
    await asyncio.sleep(0.05)
    base = {"application_id": APP_ID, "guild_id": "200", "channel_id": "300", "token": "t", "type": 3,
            "user": {"id": "7", "username": "ali"}, "data": {"custom_id": "b", "component_type": 2}}
    await server.dispatch("INTERACTION_CREATE", {**base, "id": "1", "message": {"id": "other"}})
    await server.dispatch("INTERACTION_CREATE", {**base, "id": "2", "message": {"id": "77"}})
    interaction = await asyncio.wait_for(waiter, 3)
    assert interaction.id == "2"
