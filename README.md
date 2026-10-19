<h1 align="center">🐍 JubbioPy</h1>

<p align="center">
  <strong>Jubbio platformu için modern, asenkron Python bot kütüphanesi</strong><br>
  <code>@jubbio/core</code> + <code>@jubbio/voice</code> → tek Python paketi
</p>

<p align="center">
  <a href="https://pypi.org/project/jubbio/"><img src="https://img.shields.io/pypi/v/jubbio?color=blue&label=PyPI" alt="PyPI"></a>
  <img src="https://img.shields.io/badge/python-3.10%2B-blue" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/asyncio-✓-brightgreen" alt="asyncio">
  <a href="https://github.com/nylithra/jubbiopy/blob/main/LICENSE"><img src="https://img.shields.io/badge/lisans-MIT-green" alt="MIT"></a>
</p>

<p align="center">Yapımcı: <strong>Lanux Yazılım Hizmetleri</strong></p>

> [!IMPORTANT]
> **Bu resmi bir Jubbio kütüphanesi değildir.** JubbioPy, Lanux Yazılım Hizmetleri tarafından
> geliştirilen bağımsız bir topluluk projesidir; Jubbio ile bir bağlantısı yoktur ve Jubbio tarafından
> onaylanmamıştır. Resmi Python paketi [`jubbio.py`](https://pypi.org/project/jubbio.py/) (Jubbio Community)
> ayrı bir projedir:
>
> | | Kurulum | Kod içinde |
> |---|---|---|
> | **JubbioPy** (bu proje) | `pip install jubbio` | `from jubbiopy import Client` |
> | Resmi paket | `pip install jubbio.py` | `import jubbio` |
>
> Import adları farklı olduğu için iki paket aynı ortamda çakışmadan kurulabilir.

---

## 📑 İçindekiler

- [Neden JubbioPy?](#-neden-jubbiopy)
- [Kurulum](#-kurulum)
- [Hızlı Başlangıç](#-hızlı-başlangıç)
- [Hazır Botlar](#-hazır-botlar)
- [Kullanım Kılavuzu](#-kullanım-kılavuzu)
  - [İstemci ve Olaylar](#istemci-ve-olaylar) · [Builder'lar](#builderlar) · [Etkileşimler](#etkileşimler)
  - [Collector'lar](#collectorlar) · [Ses](#ses) · [REST API](#rest-api) · [Sharding](#sharding)
- [JS'den Python'a Geçiş](#-jsden-pythona-geçiş)
- [Sık Karşılaşılan Sorunlar](#-sık-karşılaşılan-sorunlar)
- [Proje Yapısı](#-proje-yapısı)
- [Geliştirme ve Katkı](#-geliştirme-ve-katkı)
- [Lisans](#-lisans)

## ✨ Neden JubbioPy?

JubbioPy, Jubbio'nun JavaScript kütüphaneleri [`@jubbio/core`](https://www.npmjs.com/package/@jubbio/core)
ve [`@jubbio/voice`](https://www.npmjs.com/package/@jubbio/voice)'un **tek pakette birleşmiş** Python
karşılığıdır. Aynı gateway protokolünü, aynı REST uç noktalarını ve aynı olay isimlerini kullanır.

| | |
|---|---|
| 🔌 **Gateway** | WebSocket bağlantısı, heartbeat, otomatik yeniden bağlanma, anlaşılır Türkçe hata mesajları |
| 🌐 **REST API** | Mesaj, üye, rol, kanal, davet, webhook, slash komut — JS kütüphanesindeki tüm uç noktalar |
| ⚡ **Etkileşimler** | Slash komutlar, alt komutlar, butonlar, seçim menüleri, modal formlar, otomatik tamamlama |
| 📦 **Builder'lar** | Embed, Button, ActionRow, SelectMenu, Modal, SlashCommand |
| 🔄 **Collector'lar** | Mesaj / tepki / buton bekleme, `async for` desteği |
| 🎵 **Ses** | LiveKit üzerinden müzik çalma, YouTube/SoundCloud (yt-dlp), **FFmpeg kurmadan** (PyAV) |
| 🎯 **Sharding** | Çoklu süreç desteği, shard'lar arası `broadcast_eval` |
| 🔁 **JS uyumluluğu** | `setTitle`, `deferReply`, `createMessage`... JS isimleri de çalışır, kod satır satır taşınabilir |
| 🧪 **Test edilmiş** | Sahte Jubbio sunucusuna karşı uçtan uca testler |

## 📥 Kurulum

Python **3.10 veya üstü** gerekir.

```bash
pip install jubbio                     # çekirdek: gateway, REST, builder'lar, sharding
pip install "jubbio[voice]" yt-dlp     # + ses desteği (müzik botları için)
```

Ses için **ayrıca FFmpeg kurmanız gerekmez**: `[voice]` paketi, FFmpeg kütüphanelerini içinde getiren
[PyAV](https://pypi.org/project/av/)'ı kurar. Sistemde FFmpeg programı varsa o kullanılır.
`yt-dlp` sadece YouTube / SoundCloud gibi sitelerden çalmak için gereklidir.

> 💡 Kurulum adı **`jubbio`**, kodda kullanılan ad **`jubbiopy`**'dir: `pip install jubbio` → `from jubbiopy import Client`

<details>
<summary><b>Kaynaktan kurulum (en güncel sürüm)</b></summary>

```bash
git clone https://github.com/nylithra/jubbiopy.git
cd jubbiopy
pip install -e ".[voice]"
```

Windows'ta GitHub'dan zip indirdiyseniz, `pyproject.toml` dosyasının olduğu klasörde:

```bat
python -m pip install -e ".[voice]"
```

`-e`'den sonraki **nokta** (`.`) "bu klasör" demektir, unutmayın.
</details>

## 🚀 Hızlı Başlangıç

`bot.py` adında bir dosya oluşturun:

```python
import os
from jubbiopy import Client, GatewayIntentBits

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
        await message.reply(f"🏓 Pong! ({client.ping} ms)")

client.run(os.environ["BOT_TOKEN"])
```

Token'ı ortam değişkeni olarak verip çalıştırın:

```bat
:: Windows (cmd)
set BOT_TOKEN=tokeniniz
python bot.py
```

```bash
# Linux / macOS
BOT_TOKEN=tokeniniz python bot.py
```

> 🔒 Token'ı koda yazmayın ve kimseyle paylaşmayın. Token'ı ele geçiren kişi botunuzu tamamen kontrol eder.

## 🤖 Hazır Botlar

[`examples/`](https://github.com/nylithra/jubbiopy/tree/main/examples) klasöründe doğrudan çalıştırılabilen,
Türkçe botlar bulunur. Her birinin klasöründe ayrıntılı bir kurulum kılavuzu vardır.

| Bot | Özellikler |
|---|---|
| 🎫 [**Ticket Botu**](https://github.com/nylithra/jubbiopy/tree/main/examples/ticket_bot) | Kategori menülü panel, form, özel kanal, sahiplenme, kullanıcı ekle/çıkar, mesaj dökümü (.txt), hoş geldin / ayrılma mesajları, oto-rol |
| 🎵 [**Müzik Botu**](https://github.com/nylithra/jubbiopy/tree/main/examples/muzik_bot) | Şarkı sırası, çalma listesi, arama menüsü, butonlu panel, döngü, karıştırma, ses ayarı, DJ rolü, 24/7 modu |
| 🛡️ [**Moderasyon Botu**](https://github.com/nylithra/jubbiopy/tree/main/examples/moderasyon_bot) | Ban (süreli), kick, susturma, uyarı sistemi ve otomatik cezalar, vaka kayıtları, sicil, toplu silme, kanal kilidi, AutoMod, mesaj ve giriş/çıkış kayıtları |
| 🤝 [**Partner Botu**](https://github.com/nylithra/jubbiopy/blob/main/examples/partner_bot.py) | `?partner` yazınca butonlu tanıtım embed'i |
| 📚 [Basit örnekler](https://github.com/nylithra/jubbiopy/tree/main/examples) | `basic_bot.py`, `slash_commands.py`, `music_bot.py`, `sharding_launcher.py` |

```bat
set BOT_TOKEN=tokeniniz
python examples\ticket_bot\bot.py
```

## 📖 Kullanım Kılavuzu

### İstemci ve Olaylar

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

`client.run(token)` en basit yoldur. Kendi `asyncio` döngünüz varsa `await client.start(token)` veya
`await client.login(token)` (READY gelince döner, bağlantı arka planda sürer) kullanın.

Olay isimleri JS kütüphanesiyle **aynıdır** ve üç yazım da kabul edilir:

```python
@client.on("messageCreate")          # JS adı
async def a(message): ...

@client.on("message_create")         # snake_case
async def b(message): ...

@client.event                        # discord.py tarzı: fonksiyon adından
async def on_message_create(message): ...

# Bir olayı beklemek
msg = await client.wait_for("messageCreate", lambda m: m.author.id == "123", timeout=30)
```

<details>
<summary><b>Tüm olaylar</b></summary>

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
</details>

### Builder'lar

```python
from jubbiopy import (EmbedBuilder, Colors, ButtonBuilder, ButtonStyle, ActionRowBuilder,
                      StringSelectMenuBuilder, ModalBuilder, TextInputBuilder, TextInputStyle,
                      SlashCommandBuilder)

embed = (EmbedBuilder()
         .set_title("Merhaba!")
         .set_description("Bu bir embed")
         .set_color(Colors.Blue)            # sayı, "#ff0000", "Red" veya (r, g, b)
         .add_fields({"name": "Alan 1", "value": "Değer 1", "inline": True},
                     {"name": "Alan 2", "value": "Değer 2", "inline": True})
         .set_thumbnail("https://...")
         .set_footer(text="Alt bilgi")
         .set_timestamp())

row = ActionRowBuilder().add_components(
    ButtonBuilder().set_custom_id("onay").set_label("Onayla").set_style(ButtonStyle.Success),
    ButtonBuilder().set_label("Site").set_style(ButtonStyle.Link).set_url("https://example.com"),
)
await message.channel.send(embeds=[embed], components=[row])

command = (SlashCommandBuilder()
           .set_name("selamla")
           .set_description("Bir kullanıcıyı selamla")
           .add_user_option(lambda o: o.set_name("kullanici")
                                       .set_description("Selamlanacak kişi")
                                       .set_required(True)))
await client.application.commands.set([command])   # global
await guild.commands.set([command])                # sadece bir sunucu (anında)
```

### Etkileşimler

```python
from jubbiopy import File

@client.on("interactionCreate")
async def handler(interaction):
    if interaction.is_command():
        user = interaction.options.get_user("kullanici")
        sub = interaction.options.get_subcommand()
        await interaction.defer_reply(ephemeral=True)      # "düşünüyor..."
        await interaction.edit_reply("İşlem tamam!")
        await interaction.follow_up("Ek mesaj", files=[File("rapor.txt", b"...")])

    elif interaction.is_button():
        await interaction.update(content="Buton tıklandı!", components=[])

    elif interaction.is_select_menu():
        await interaction.reply(f"Seçilen: {interaction.values}", ephemeral=True)

    elif interaction.is_modal_submit():
        value = interaction.fields.get_text_input_value("alan_id")

    elif interaction.is_autocomplete():
        focused = interaction.options.get_focused()
        await interaction.respond([{"name": "Seçenek", "value": "secenek"}])
```

Butonlarda ve menülerde `await interaction.show_modal(modal)` ile form açabilirsiniz.

### Collector'lar

> ⚠️ `time` ve `idle` süreleri **saniye** cinsindendir (JS'de milisaniye).

```python
# Kanalda mesaj bekle
collected = await message.channel.await_messages(
    filter=lambda m, _: m.author.id == message.author.id, max=1, time=30, errors=["time"])

# Mesajdaki buton tıklamalarını topla
collector = sent.create_message_component_collector(time=60)
async for interaction in collector:
    await interaction.reply("Aldım!", ephemeral=True)

# Tek bir bileşen etkileşimi bekle
interaction = await sent.await_message_component(time=30)
```

### Ses

```python
from jubbiopy.voice import (join_voice_channel, create_audio_player, create_audio_resource_from_url,
                            probe_audio_info, get_voice_connection, enters_state,
                            AudioPlayerStatus, VoiceConnectionStatus)

info = await probe_audio_info("tarkan kuzu kuzu")      # link veya arama metni
connection = get_voice_connection(guild_id) or join_voice_channel(
    channel_id=voice_channel_id,
    guild_id=guild_id,
    adapter_creator=client.voice.adapters.get(guild_id),
)
await enters_state(connection, VoiceConnectionStatus.Ready, 20)

player = create_audio_player()                          # decoder="auto" | "pyav" | "ffmpeg"
connection.subscribe(player)

resource = create_audio_resource_from_url(info.url, metadata={"title": info.title})
resource.set_volume(0.5)                                # 0.0 – 2.0, çalarken de değişir
player.play(resource)

player.pause(); player.unpause(); player.stop()
player.on("stateChange", lambda old, new: print(old.status, "->", new.status))
player.on("error", lambda err: print("Hata:", err.message))
connection.destroy()                                    # kanaldan ayrıl ve kapat
```

| `AudioPlayerStatus` | | `VoiceConnectionStatus` | |
|---|---|---|---|
| `Idle` | Çalmıyor | `Connecting` | Bağlanıyor |
| `Buffering` | Yükleniyor | `Signalling` | Ses sunucusu bilgisi alınıyor |
| `Playing` | Çalıyor | `Ready` | Bağlı |
| `Paused` | Duraklatıldı | `Disconnected` | Koptu |
| `AutoPaused` | Dinleyici yok | `Destroyed` | Kapatıldı |

FFmpeg / yt-dlp yolları `FFMPEG_PATH` ve `YTDLP_PATH` ortam değişkenleriyle değiştirilebilir.

### REST API

Tüm uç noktalara `client.rest` ile erişilir. Metot isimleri JS ile birebir aynıdır (snake_case).
Başarısız istekler `jubbiopy.HTTPException` fırlatır (`.status`, `.text`).

<details>
<summary><b>Tüm REST metotları (örneklerle)</b></summary>

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
await client.rest.edit_member(guild_id, user_id, {"nick": "Yeni Takma Ad"})
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
webhook = await client.rest.create_webhook(guild_id, channel_id, {"name": "Webhook'um"})

# Slash komutları
await client.rest.register_global_commands([{"name": "ping", "description": "Pong!"}])
await client.rest.register_guild_commands(guild_id, commands)   # anında, test için
await client.rest.delete_global_command(command_id)

# Genel HTTP metotları
await client.rest.get("/bot/guilds/123/channels")
await client.rest.post("/bot/guilds/123/channels", {"name": "kanal", "type": 2})
```
</details>

### Sharding

```python
import asyncio
from jubbiopy import ShardingManager

async def main():
    manager = ShardingManager("bot.py", total_shards=2, token="BOT_TOKEN")
    manager.on("shardReady", lambda shard_id: print(f"Shard {shard_id} hazır"))
    await manager.spawn()
    print(await manager.broadcast_eval("len(client.guilds)"))   # her shard'dan değer
    await manager.wait()

asyncio.run(main())
```

Her shard ayrı bir Python sürecinde çalışır. `bot.py` içindeki `Client` shard bilgisini
(`SHARD_ID`, `SHARD_COUNT`) ortamdan otomatik alır; token `JUBBIO_TOKEN` değişkenindedir.

## 🔁 JS'den Python'a Geçiş

| JavaScript (`@jubbio/core` / `@jubbio/voice`) | Python (`jubbiopy`) |
|---|---|
| `import { Client } from '@jubbio/core'` | `from jubbiopy import Client` |
| `import { joinVoiceChannel } from '@jubbio/voice'` | `from jubbiopy.voice import join_voice_channel` |
| `client.login(token)` (Promise) | `client.run(token)` veya `await client.login(token)` |
| `client.on('messageCreate', fn)` | `@client.on("messageCreate")` (aynı isimler) |
| `interaction.deferReply()` | `await interaction.defer_reply()` (`deferReply` da çalışır) |
| `message.reply({ content, embeds })` | `await message.reply(content, embeds=[...])` |
| `{ name, data: Buffer }` dosyalar | `File("ad.txt", b"...")` veya `{"name": ..., "data": ...}` |
| `EmbedBuilder.from(x)` | `EmbedBuilder.from_(x)` |
| Collector `time` / `idle` (ms) | **saniye** |
| `client.guilds.cache.get(id)` | `client.guilds.get(id)` (`.cache` da çalışır) |
| `bigint` izin bitleri | Python `int` |

<details>
<summary><b>JS sürümüne göre iyileştirmeler</b></summary>

- Ses bağlantısı sadece **bot'un kendi** ses durumu değişince kopar (JS'de sunucudaki herhangi biri ayrılınca kopuyordu).
- `DMChannel.send()` doğru uç noktayı kullanır.
- Tepki olayları yayınlanır, böylece `ReactionCollector` çalışır.
- Shard'lar arası `eval` / `broadcast_eval` gerçekten çalışır.
- Alt komut seçenekleri (`get_subcommand()` + iç içe seçenekler) desteklenir.
- Duraklatma sırasında ses verisi kaybolmaz; FFmpeg kurmadan ses çalınabilir (PyAV).
- Hata ayıklama çıktısı `print` yerine `logging` ile verilir (`jubbiopy`, `jubbiopy.rest`, `jubbiopy.voice`).
</details>

## 🩺 Sık Karşılaşılan Sorunlar

<details>
<summary><b><code>API Error 403: Insufficient permissions</code></b></summary>

Bot'un o işlem için izni yok. Sunucu ayarlarında bot'un rolüne gereken izinleri verin
(mesaj için **Kanalı Görüntüle**, **Mesaj Gönder**, embed için **Bağlantı Yerleştir**) ve
kanalın kendi izin ayarlarının bunu engellemediğini kontrol edin.
</details>

<details>
<summary><b>Bot mesajlara cevap vermiyor</b></summary>

- `GatewayIntentBits.MessageContent` intent'ini eklediğinizden emin olun.
- Jubbio'nun bot ayarlarında mesaj içeriği (Message Content) için bir izin varsa açık olmalıdır.
- Hata ayrıntıları için: `client.run(token, log_level=logging.DEBUG)`
</details>

<details>
<summary><b><code>Gateway bağlantısı reddedildi [4004]</code></b></summary>

Token geçersiz. Token'ı kopyalarken başına/sonuna boşluk eklenmediğinden emin olun
ve gerekirse yeni bir token oluşturun.
</details>

<details>
<summary><b><code>-e option requires 1 argument</code></b></summary>

Komutun sonuna nokta koyun: `python -m pip install -e .`
</details>

<details>
<summary><b>Müzik: <code>yt-dlp bulunamadı</code> / <code>[WinError 2]</code></b></summary>

`python -m pip install yt-dlp` ile kurun. JubbioPy, PATH'te olmasa bile yt-dlp'yi otomatik bulur.
Yine de bulamazsa: `set YTDLP_PATH=C:\...\yt-dlp.exe`
</details>

<details>
<summary><b>Müzik: ses çözücü bulunamadı</b></summary>

`python -m pip install av` (veya `pip install "jubbio[voice]"`). FFmpeg kurmanız gerekmez.
</details>

## 🗂️ Proje Yapısı

```
jubbiopy/
├── client.py          # Client: gateway bağlantısı, olaylar, önbellek
├── rest.py            # REST API istemcisi
├── events.py          # asyncio olay yayıcı
├── enums.py           # Intent'ler, kanal tipleri, izin bitleri...
├── structures/        # User, Guild, GuildMember, Message, kanallar, etkileşimler
├── builders/          # Embed, Button, SelectMenu, Modal, SlashCommand
├── utils/             # Collector'lar, Formatters, BitField, SnowflakeUtil
├── managers/          # Slash komut yöneticisi
├── sharding/          # ShardingManager
└── voice/             # Ses bağlantısı, AudioPlayer, kaynaklar
examples/              # Hazır botlar ve örnekler
tests/                 # Sahte Jubbio sunucusuna karşı testler
```

## 🛠️ Geliştirme ve Katkı

```bash
git clone https://github.com/nylithra/jubbiopy.git
cd jubbiopy
pip install -e ".[voice,dev]"
pytest
```

Testler sahte bir Jubbio gateway + REST sunucusuna karşı çalışır (gerçek token gerekmez);
ses testleri FFmpeg / PyAV ile gerçek çözümleme yapar.

Hata bildirimi ve öneriler için [GitHub Issues](https://github.com/nylithra/jubbiopy/issues) kullanın.
Hata bildirirken Python sürümünüzü, işletim sisteminizi ve konsoldaki hata çıktısının tamamını ekleyin
(**token'ınızı eklemeyin**).

## 📄 Lisans

[MIT](https://github.com/nylithra/jubbiopy/blob/main/LICENSE) © Lanux Yazılım Hizmetleri

JubbioPy bağımsız bir projedir; "Jubbio" adı ve logosu sahiplerine aittir.
