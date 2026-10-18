"""Sharding örneği: ``basic_bot.py`` dosyasını 2 shard olarak başlatır.

Shard süreçleri yöneticinin ortam değişkenlerini devralır; ayrıca token
``JUBBIO_TOKEN``, shard bilgisi ``SHARD_ID`` / ``SHARD_COUNT`` olarak verilir
ve ``Client`` shard bilgisini otomatik kullanır.

Çalıştırma:  BOT_TOKEN=... python examples/sharding_launcher.py
"""

import asyncio
import os

from jubbiopy import ShardingManager


async def main():
    manager = ShardingManager(
        os.path.join(os.path.dirname(__file__), "basic_bot.py"),
        total_shards=2,
        token=os.environ["BOT_TOKEN"],
    )
    manager.on("shardReady", lambda shard_id: print(f"✅ Shard {shard_id} hazır"))
    manager.on("shardDeath", lambda shard_id, info: print(f"💀 Shard {shard_id} kapandı: {info}"))

    await manager.spawn()
    counts = await manager.fetch_client_values("guilds.size")
    print(f"Toplam sunucu: {sum(counts)}")
    await manager.wait()


asyncio.run(main())
