"""Sharding testi: gerçek alt süreçler sahte gateway'e bağlanır."""

from __future__ import annotations

import asyncio
import os
import textwrap

from jubbio import ShardClientUtil, ShardingManager

from .conftest import until

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


async def test_sharding_manager(server, tmp_path, monkeypatch):
    bot = tmp_path / "bot.py"
    bot.write_text(textwrap.dedent("""
        import asyncio, os
        from jubbio import Client

        async def main():
            client = Client(intents=1, gateway_url=os.environ["FAKE_GW"], api_url=os.environ["FAKE_API"])
            await client.start(os.environ["JUBBIO_TOKEN"])

        asyncio.run(main())
    """))
    monkeypatch.setenv("FAKE_GW", server.gateway_url)
    monkeypatch.setenv("FAKE_API", server.api_url)
    monkeypatch.setenv("PYTHONPATH", ROOT)

    manager = ShardingManager(str(bot), total_shards=2, token="shard-token", respawn=False)
    ready = []
    manager.on("shardReady", ready.append)
    try:
        await asyncio.wait_for(manager.spawn(delay=0, timeout=20), 30)
        assert sorted(ready) == [0, 1]
        identifies = sorted(p["d"]["shard"] for p in server.received if p["op"] == 2)
        assert identifies == [[0, 2], [1, 2]]
        assert all(p["d"]["token"] == "Bot shard-token" for p in server.received if p["op"] == 2)

        assert await manager.broadcast_eval("len(client.guilds)") == [1, 1]
        assert await manager.fetch_client_values("user.username") == ["testbot", "testbot"]
        assert await manager.shards[1].eval("client.shard.id") == 1
    finally:
        await manager.close()
    await until(lambda: all(s.process is None for s in manager.shards.values()))


def test_shard_id_for_guild():
    assert ShardClientUtil.shard_id_for_guild_id(str(5 << 22), 2) == 1
