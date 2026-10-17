<p align="center">
  <img src="https://cdn.jubbio.com/assets/logo/jubbio-logo.png" alt="Jubbio" width="70" />
</p>

<h1 align="center">Jubbio.py</h1>

<p align="center">
  <strong>Jubbio platformu için Python bot kütüphanesi</strong><br>
  <code>@jubbio/core</code> + <code>@jubbio/voice</code> → tek paket
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-%3E%3D3.10-blue" alt="Python">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="License">
  <img src="https://img.shields.io/badge/asyncio-✓-brightgreen" alt="asyncio">
</p>

<p align="center">Yapımcı: <strong>Lanux Yazılım Hizmetleri</strong></p>

---

Jubbio.py, resmi JavaScript kütüphaneleri [`@jubbio/core`](https://www.npmjs.com/package/@jubbio/core)
ve [`@jubbio/voice`](https://www.npmjs.com/package/@jubbio/voice)'un **tek bir pakette birleşmiş**
Python karşılığıdır. Aynı gateway protokolünü, aynı REST uç noktalarını ve aynı
olay isimlerini kullanır; `asyncio` üzerine kuruludur.

## Kurulum

```bash
pip install jubbio.py            # çekirdek (gateway, REST, builder'lar, sharding)
pip install "jubbio.py[voice]"   # + ses desteği (LiveKit)
```

Kaynaktan kurmak için:

```bash
git clone https://github.com/nylithra/jubbiopy.git
cd jubbiopy
pip install -e ".[voice]"
```

Ses desteği için sistemde ayrıca **FFmpeg** ve (YouTube / SoundCloud için) **yt-dlp** kurulu olmalıdır:

```bash
# Ubuntu/Debian
sudo apt install ffmpeg && pip install yt-dlp
# macOS
brew install ffmpeg yt-dlp
# Windows: ffmpeg.org ve yt-dlp GitHub sürümlerinden indirip PATH'e ekleyin
```

## Hızlı Başlangıç

```python
import os
from jubbio import Client, GatewayIntentBits

client = Client(intents=[
    GatewayIntentBits.Guilds,
    GatewayIntentBits.GuildMessages,
    GatewayIntentBits.MessageContent,
])

@client.on("ready")
async def on_ready(c):
    print(f"✅ {client.user.username} çevrimiçi!")

@client.on("messageCreate")
async def on_message(message):
    if message.content == "!ping":
        await message.reply("🏓 Pong!")

@client.on("interactionCreate")
async def on_interaction(interaction):
    if not interaction.is_command():
        return
    if interaction.command_name == "merhaba":
        await interaction.reply("Merhaba! 👋")

client.run(os.environ["BOT_TOKEN"])
```

Kendi `asyncio` döngünüz varsa `client.run()` yerine `await client.start(token)` veya
`await client.login(token)` (READY gelince döner, bağlantı arka planda sürer) kullanabilirsiniz.

Daha fazla örnek: [`examples/`](examples/) — temel bot, slash komutlar/modal/collector, müzik botu, sharding.

## İstemci Seçenekleri

```python
client = Client(
    intents=[...],                 # Gateway intent'leri (liste veya sayı)
    shards=[0, 2],                 # İsteğe bağlı: [shard_id, toplam_shard]
    gateway_url="wss://...",       # İsteğe bağlı: özel gateway adresi
    api_url="https://...",         # İsteğe bağlı: özel API adresi
    max_reconnect_attempts=5,      # Yeniden bağlanma deneme sınırı
    ready_timeout=30,              # READY bekleme süresi (sn)
)
```

## Olaylar

Olay isimleri JS kütüphanesiyle **aynıdır**. Üç farklı yazım da kabul edilir:

```python
@client.on("messageCreate")          # JS adı
async def a(message): ...

@client.on("message_create")         # snake_case
async def b(message): ...

@client.event                        # discord.py tarzı: fonksiyon adından
async def on_message_create(message): ...
```

Dinleyiciler senkron veya `async` olabilir. Belirli bir olayı beklemek için:

```python
msg = await client.wait_for("messageCreate", lambda m: m.author.id == "123", timeout=30)
```

| Olay | Açıklama |
|------|----------|
| `ready` | Bot bağlandı ve hazır |
| `messageCreate` | Yeni mesaj (`Message`) |
| `messageUpdate` / `messageDelete` / `messageDeleteBulk` | Mesaj düzenlendi / silindi |
| `messageReactionAdd` / `messageReactionRemove` | Tepki eklendi / kaldırıldı |
| `interactionCreate` | Slash komut / buton / menü / modal / otomatik tamamlama |
| `guildCreate` / `guildUpdate` / `guildDelete` | Sunucu olayları (`Guild`) |
| `guildMemberAdd` / `guildMemberUpdate` / `guildMemberRemove` | Üye olayları (`GuildMember`) |
| `channelCreate` / `channelUpdate` / `channelDelete` | Kanal olayları |
| `roleCreate` / `roleUpdate` / `roleDelete` | Rol olayları |
| `guildBanAdd` / `guildBanRemove` | Yasaklama olayları |
| `inviteCreate` / `inviteDelete` | Davet olayları |
| `voiceStateUpdate` / `voiceServerUpdate` | Ses durumu |
| `presenceUpdate` / `typingStart` | Durum / yazıyor |
| `error` / `debug` | Hata / hata ayıklama bilgisi |
| `raw` | İşlenmeyen ham gateway olayı |

## Builder'lar

```python
from jubbio import (EmbedBuilder, Colors, ButtonBuilder, ButtonStyle, ActionRowBuilder,
                    StringSelectMenuBuilder, ModalBuilder, TextInputBuilder, TextInputStyle,
                    SlashCommandBuilder)

embed = (EmbedBuilder()
         .set_title("Merhaba!")
         .set_description("Bu bir embed")
         .set_color(Colors.Blue)            # sayı, "#ff0000", "Red" veya (r, g, b)
         .add_fields({"name": "Alan 1", "value": "Değer 1", "inline": True},
                     {"name": "Alan 2", "value": "Değer 2", "inline": True})
         .set_footer(text="Alt bilgi")
         .set_timestamp())
await message.reply(embeds=[embed])

row = ActionRowBuilder().add_components(
    ButtonBuilder().set_custom_id("buton").set_label("Tıkla!").set_style(ButtonStyle.Primary)
)
await interaction.reply(components=[row])

command = (SlashCommandBuilder()
           .set_name("selamla")
           .set_description("Bir kullanıcıyı selamla")
           .add_user_option(lambda o: o.set_name("kullanici")
                                       .set_description("Selamlanacak kişi")
                                       .set_required(True)))
await client.application.commands.set([command])   # global
await guild.commands.set([command])                # sadece bir sunucu (anında)
```

> 💡 **JS'den geçiş:** Tüm metotların JS adları da çalışır — `setTitle`, `addFields`, `setCustomId`,
> `toJSON`, `isCommand`, `deferReply`, `createMessage`... Otomatik olarak Python karşılığına
> (`set_title`, `add_fields`, ...) yönlendirilir. Böylece JS kodunu satır satır taşıyabilirsiniz.

## Etkileşimler

```python
from jubbio import File

@client.on("interactionCreate")
async def handler(interaction):
    if interaction.is_command():
        name = interaction.options.get_string("isim")
        user = interaction.options.get_user("kullanici")
        sub = interaction.options.get_subcommand()
        await interaction.defer_reply(ephemeral=True)
        await interaction.edit_reply("İşlem tamam!")
        await interaction.follow_up(content="Ek mesaj", files=[File("rapor.txt", b"...")])

    elif interaction.is_button():
        await interaction.update(content="Buton tıklandı!", components=[])

    elif interaction.is_select_menu():
        await interaction.reply(f"Seçilen: {interaction.values}")

    elif interaction.is_modal_submit():
        value = interaction.fields.get_text_input_value("alan_id")

    elif interaction.is_autocomplete():
        focused = interaction.options.get_focused()
        await interaction.respond([{"name": "Seçenek", "value": "secenek"}])
```

## Collector'lar

> ⚠️ Python sürümünde `time` ve `idle` süreleri **saniye** cinsindendir (JS'de milisaniye).

```python
# Kanalda mesaj bekle
collected = await message.channel.await_messages(
    filter=lambda m, _: m.author.id == message.author.id, max=1, time=30, errors=["time"])

# Mesajdaki buton tıklamalarını topla
collector = sent.create_message_component_collector(time=60)
collector.on("collect", lambda i: print("Tıklandı:", i.custom_id))
async for interaction in collector:   # veya: await collector.wait()
    await interaction.reply("Aldım!", ephemeral=True)

# Tek bir bileşen etkileşimi bekle
interaction = await sent.await_message_component(time=30)
```

## Ses Desteği

```python
from jubbio.voice import (join_voice_channel, create_audio_player, create_audio_resource,
                          create_audio_resource_from_url, probe_audio_info, get_voice_connection,
                          enters_state, AudioPlayerStatus, VoiceConnectionStatus)

info = await probe_audio_info("https://youtube.com/watch?v=...")   # veya arama metni
print(info.title, info.duration, info.thumbnail)

connection = get_voice_connection(guild_id) or join_voice_channel(
    channel_id=voice_channel_id,
    guild_id=guild_id,
    adapter_creator=client.voice.adapters.get(guild_id),   # veya guild.voice_adapter_creator
    self_mute=False,
    self_deaf=False,
)
await enters_state(connection, VoiceConnectionStatus.Ready, 20)

player = create_audio_player(behaviors={"no_subscriber": "pause"})   # "pause" | "play" | "stop"
connection.subscribe(player)

resource = create_audio_resource_from_url(info.url, metadata={"title": info.title})
resource.set_volume(0.5)          # 0.0 – 2.0, çalarken de değiştirilebilir
player.play(resource)

player.pause(); player.unpause(); player.stop()
if player.state.status == AudioPlayerStatus.Playing: ...

connection.disconnect()   # kanaldan ayrıl
connection.destroy()      # tamamen kapat

player.on("stateChange", lambda old, new: print(old.status, "->", new.status))
player.on("error", lambda err: print("Hata:", err.message, err.resource))
connection.on("stateChange", lambda old, new: ...)
```

| `AudioPlayerStatus` | Açıklama | | `VoiceConnectionStatus` | Açıklama |
|---|---|---|---|---|
| `Idle` | Bir şey çalmıyor | | `Connecting` | Bağlanıyor |
| `Buffering` | Yükleniyor | | `Signalling` | Bağlantı bilgisi alınıyor |
| `Playing` | Çalıyor | | `Ready` | Bağlı ve hazır |
| `Paused` | Duraklatıldı | | `Disconnected` | Bağlantı koptu |
| `AutoPaused` | Abone yok, otomatik duraklatıldı | | `Destroyed` | Yok edildi |

FFmpeg / yt-dlp yolları `FFMPEG_PATH` ve `YTDLP_PATH` ortam değişkenleriyle veya
`create_audio_player(ffmpeg_path=..., yt_dlp_path=...)` ile değiştirilebilir.

## REST API

Tüm uç noktalara `client.rest` ile erişilir. Metot isimleri JS ile birebir aynıdır (snake_case):

```python
# Mesajlar
await client.rest.create_message(guild_id, channel_id, {"content": "Merhaba <@123>!", "embeds": [embed]})
await client.rest.create_ephemeral_message(guild_id, channel_id, user_id, {"content": "Sadece sen görürsün"})
await client.rest.edit_message(guild_id, channel_id, message_id, {"content": "Güncellendi!"})
await client.rest.delete_message(guild_id, channel_id, message_id)
await client.rest.bulk_delete_messages(guild_id, channel_id, message_ids)
messages = await client.rest.get_messages(guild_id, channel_id, limit=50, before=message_id)
await client.rest.add_reaction(guild_id, channel_id, message_id, ":thumbsup:")  # :isim: / <:isim:id>
await client.rest.pin_message(guild_id, channel_id, message_id)
await client.rest.create_message_with_file(guild_id, channel_id, {"content": "Dosya", "file": File.from_path("resim.png")})
await client.rest.create_dm_message(user_id, {"content": "DM!"})

# Üyeler
member = await client.rest.get_member(guild_id, user_id)
await client.rest.timeout_member(guild_id, user_id, 60 * 60 * 1000, "Spam")  # milisaniye; None = kaldır
await client.rest.kick_member(guild_id, user_id, "Kural ihlali")
await client.rest.ban_member(guild_id, user_id, delete_message_days=7, reason="Ağır ihlal")
await client.rest.unban_member(guild_id, user_id)
await client.rest.edit_member(guild_id, user_id, {"nick": "Yeni Takma Ad", "roles": ["rol1", "rol2"]})
await client.rest.add_member_role(guild_id, user_id, role_id)
await client.rest.remove_member_role(guild_id, user_id, role_id)

# Roller
roles = await client.rest.get_roles(guild_id)
role = await client.rest.create_role(guild_id, {"name": "Yeni Rol", "color": 0xFF0000, "permissions": "8"})
await client.rest.edit_role(guild_id, role_id, {"name": "Güncel Rol"})
await client.rest.delete_role(guild_id, role_id)

# Kanallar
channels = await client.rest.get_guild_channels(guild_id)
channel = await client.rest.create_channel(guild_id, {"name": "yeni-kanal", "type": 0, "parent_id": category_id})
await client.rest.delete_channel(guild_id, channel_id)
await client.rest.edit_channel_permissions(channel_id, role_or_user_id, {"allow": "1024", "deny": "2048", "type": 0})

# Sunucu, davetler, kullanıcılar, webhook'lar
guild = await client.rest.get_guild(guild_id)
bans = await client.rest.get_bans(guild_id)
invite = await client.rest.create_invite(guild_id, channel_id, {"max_age": 86400, "max_uses": 10})
user = await client.rest.get_user(user_id)
me = await client.rest.get_current_user()
webhook = await client.rest.create_webhook(guild_id, channel_id, {"name": "Webhook'um"})

# Slash komutları
await client.rest.register_global_commands([{"name": "ping", "description": "Pong!"}])
await client.rest.register_guild_commands(guild_id, commands)   # anında, test için
await client.rest.delete_global_command(command_id)

# Genel HTTP metotları
await client.rest.get("/bot/guilds/123/channels")
await client.rest.post("/bot/guilds/123/channels", {"name": "kanal", "type": 2})
```

Başarısız istekler `jubbio.HTTPException` fırlatır (`.status`, `.text`).

## Sharding

```python
import asyncio
from jubbio import ShardingManager

async def main():
    manager = ShardingManager("bot.py", total_shards=2, token="BOT_TOKEN")
    manager.on("shardReady", lambda shard_id: print(f"Shard {shard_id} hazır"))
    await manager.spawn()
    print(await manager.fetch_client_values("guilds.size"))      # her shard'dan değer
    print(await manager.broadcast_eval("len(client.guilds)"))   # Python ifadesi
    await manager.wait()

asyncio.run(main())
```

Her shard ayrı bir Python sürecinde çalışır; `bot.py` içindeki `Client` shard bilgisini
(`SHARD_ID`, `SHARD_COUNT`) ortamdan otomatik alır, token `JUBBIO_TOKEN` değişkenindedir.
Shard içinden yöneticiye `client.shard.send(...)` / `await client.shard.broadcast_eval(...)` ile ulaşılır.

## JS'den Python'a Geçiş Notları

| JavaScript (`@jubbio/core` / `@jubbio/voice`) | Python (`jubbio`) |
|---|---|
| `import { Client } from '@jubbio/core'` | `from jubbio import Client` |
| `import { joinVoiceChannel } from '@jubbio/voice'` | `from jubbio.voice import join_voice_channel` |
| `client.login(token)` (Promise) | `client.run(token)` veya `await client.login(token)` |
| `client.on('messageCreate', fn)` | `@client.on("messageCreate")` (aynı isimler) |
| `interaction.deferReply()` | `await interaction.defer_reply()` (`deferReply` de çalışır) |
| `message.reply({ content, embeds })` | `await message.reply(content, embeds=[...])` veya `reply({...})` |
| `{ name, data: Buffer }` dosyalar | `File("ad.txt", b"...")` veya `{"name": ..., "data": ...}` |
| `EmbedBuilder.from(x)` | `EmbedBuilder.from_(x)` |
| Collector `time` / `idle` (ms) | **saniye** |
| `rest.timeoutMember(..., duration)` (ms) | `rest.timeout_member(..., duration)` (ms, aynı) |
| `client.guilds.cache.get(id)` | `client.guilds.get(id)` (`.cache` de çalışır) |
| `bigint` izin bitleri | Python `int` |

JS sürümüne göre küçük iyileştirmeler:
- Ses bağlantısı sadece **bot'un kendi** ses durumu değişince kopar (JS'de sunucudaki herhangi bir kullanıcı ayrılınca kopuyordu).
- `DMChannel.send()` doğru uç noktayı (`/bot/dm/{kanal}`) kullanır.
- Tepki olayları (`messageReactionAdd`/`Remove`) yayınlanır, böylece `ReactionCollector` çalışır.
- Shard'lar arası `eval` / `broadcast_eval` gerçekten çalışır.
- Alt komut seçenekleri (`get_subcommand()` + iç içe seçenekler) desteklenir.
- Duraklatma sırasında ses verisi kaybolmaz.
- Hata ayıklama çıktısı `print` yerine `logging` (`jubbio`, `jubbio.rest`, `jubbio.voice` logger'ları) ile verilir.

## Geliştirme

```bash
pip install -e ".[voice,dev]"
pytest
```

Testler sahte bir Jubbio gateway + REST sunucusuna karşı çalışır (gerçek token gerekmez);
ses testleri FFmpeg varsa gerçek çözümleme yapar.

## Lisans

MIT © Lanux Yazılım Hizmetleri
