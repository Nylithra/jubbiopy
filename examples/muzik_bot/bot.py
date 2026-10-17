"""Gelişmiş Müzik Botu altyapısı (Jubbio.py).

Özellikler
----------
• Sunucu başına şarkı sırası (kuyruk), YouTube / SoundCloud linki, arama ve çalma listesi desteği
• /ara ile arama sonuçlarından menüyle seçme
• Butonlu "Şimdi Çalıyor" paneli: önceki, duraklat/devam, geç, durdur, döngü, karıştır, ses -/+, sıra
• Döngü modları (kapalı / şarkı / sıra), karıştırma, sıradan kaldırma, taşıma, belirli şarkıya atlama
• Önceki şarkıya dönme (geçmiş), ilerleme çubuğu, ses seviyesi (0-200%, çalarken anında)
• DJ rolü: kontrol komutlarını DJ / yöneticilerle sınırlama
• 24/7 modu; aksi halde sıra bitince veya kanal boşalınca otomatik ayrılma
• Ayarlar ``muzik_data.json`` dosyasında kalıcıdır

Gerekenler::

    python -m pip install -e ".[voice]" yt-dlp

Çalıştırma (Windows)::

    set BOT_TOKEN=tokenin
    python examples\\muzik_bot\\bot.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
from collections import deque
from dataclasses import dataclass
from typing import Any, Deque, Dict, List, Optional

from jubbio import (
    ActionRowBuilder,
    ButtonBuilder,
    ButtonStyle,
    Client,
    Colors,
    EmbedBuilder,
    GatewayIntentBits,
    HTTPException,
    SlashCommandBuilder,
    StringSelectMenuBuilder,
)
from jubbio.voice import (
    AudioPlayerStatus,
    VoiceConnectionStatus,
    create_audio_player,
    create_audio_resource,
    join_voice_channel,
    probe_audio_info,
)
from jubbio.voice.resource import yt_dlp_command

log = logging.getLogger("muzik_bot")

IDLE_TIMEOUT = 180      # sıra bitince / kanal boşalınca ayrılmadan önce bekleme (sn)
MAX_QUEUE = 500         # sunucu başına en fazla şarkı
MAX_PLAYLIST = 100      # bir çalma listesinden alınacak en fazla şarkı
PAGE_SIZE = 10          # /sira sayfa boyutu
LOOP_NAMES = {"off": "Kapalı", "track": "🔂 Şarkı", "queue": "🔁 Sıra"}


# ============================================================== yardımcılar
def fmt_time(seconds: float) -> str:
    seconds = int(seconds or 0)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def progress_bar(position: float, duration: float, size: int = 14) -> str:
    if not duration:
        return f"🔴 CANLI • {fmt_time(position)}"
    filled = min(size - 1, int(size * position / duration))
    return "▬" * filled + "🔘" + "▬" * (size - filled - 1) + f"  `{fmt_time(position)} / {fmt_time(duration)}`"


def err(text: str) -> EmbedBuilder:
    return EmbedBuilder().set_description(f"❌ {text}").set_color(Colors.Red)


def ok(text: str) -> EmbedBuilder:
    return EmbedBuilder().set_description(text).set_color(Colors.Blurple)


async def respond(interaction, content: Optional[str] = None, **kwargs: Any) -> None:
    if interaction.deferred:
        kwargs.pop("ephemeral", None)
        await interaction.edit_reply(content, **kwargs)
    elif interaction.replied:
        await interaction.follow_up(content, **kwargs)
    else:
        await interaction.reply(content, **kwargs)


@dataclass
class Track:
    title: str
    url: str
    duration: int = 0
    thumbnail: Optional[str] = None
    requester_id: str = ""

    @property
    def link(self) -> str:
        return f"[{self.title[:80]}]({self.url})" if self.url.startswith("http") else f"**{self.title[:80]}**"


class Settings:
    """Sunucu ayarları (DJ rolü, varsayılan ses, 24/7) — JSON dosyasında."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.data: Dict[str, Dict[str, Any]] = {}
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                self.data = json.load(fh)

    def get(self, guild_id: str) -> Dict[str, Any]:
        return self.data.setdefault(guild_id, {"dj_role": None, "volume": 100, "stay": False})

    def save(self) -> None:
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)


class GuildMusic:
    """Bir sunucunun müzik durumu."""

    def __init__(self, bot: "MusicBot", guild_id: str, volume: int) -> None:
        self.bot = bot
        self.guild_id = guild_id
        self.queue: List[Track] = []
        self.history: Deque[Track] = deque(maxlen=25)
        self.current: Optional[Track] = None
        self.loop = "off"
        self.volume = volume
        self.text_channel_id: Optional[str] = None
        self.connection = None
        self.resource = None
        self.idle_task: Optional[asyncio.Task] = None
        self.transition = False  # play()/stop() kaynaklı Idle durumunu doğal bitişten ayırır
        self.player = create_audio_player()
        self.player.on("stateChange", self._on_state)
        self.player.on("error", self._on_error)

    @property
    def position(self) -> float:
        return self.resource.playback_duration if self.resource is not None else 0.0

    def _on_state(self, old, new) -> None:
        if new.status == AudioPlayerStatus.Idle and old.status == AudioPlayerStatus.Playing and not self.transition:
            self.bot.spawn(self.bot.play_next(self))

    def _on_error(self, error) -> None:
        log.warning("Çalma hatası (%s): %s", self.guild_id, error.message)
        title = self.current.title if self.current else "şarkı"
        self.bot.spawn(self.bot.notify(self, embeds=[err(f"**{title}** çalınamadı: {error.message[:300]}")]))
        self.bot.spawn(self.bot.play_next(self, failed=True))


# ============================================================== komutlar
def build_commands() -> List[SlashCommandBuilder]:
    def cmd(name: str, desc: str) -> SlashCommandBuilder:
        return SlashCommandBuilder().set_name(name).set_description(desc)

    return [
        cmd("cal", "Şarkı veya çalma listesi çal / sıraya ekle")
        .add_string_option(lambda o: o.set_name("sarki").set_description("Şarkı adı, YouTube/SoundCloud linki veya liste").set_required(True)),
        cmd("ara", "YouTube'da ara ve sonuçlardan seç")
        .add_string_option(lambda o: o.set_name("sorgu").set_description("Aranacak şarkı").set_required(True)),
        cmd("sira", "Şarkı sırasını göster")
        .add_integer_option(lambda o: o.set_name("sayfa").set_description("Sayfa").set_min_value(1)),
        cmd("simdi", "Şu an çalan şarkı"),
        cmd("gec", "Şarkıyı geç"),
        cmd("atla", "Sıradaki belirli bir şarkıya atla")
        .add_integer_option(lambda o: o.set_name("sira").set_description("Sıra numarası").set_required(True).set_min_value(1)),
        cmd("onceki", "Önceki şarkıya dön"),
        cmd("duraklat", "Duraklat"),
        cmd("devam", "Devam et"),
        cmd("durdur", "Çalmayı durdur ve sırayı temizle"),
        cmd("ses", "Ses seviyesini ayarla")
        .add_integer_option(lambda o: o.set_name("seviye").set_description("0-200").set_required(True).set_min_value(0).set_max_value(200)),
        cmd("dongu", "Döngü modunu ayarla")
        .add_string_option(lambda o: o.set_name("mod").set_description("Döngü modu").set_required(True)
                           .add_choices({"name": "Kapalı", "value": "off"}, {"name": "Şarkı", "value": "track"},
                                        {"name": "Sıra", "value": "queue"})),
        cmd("karistir", "Sırayı karıştır"),
        cmd("kaldir", "Sıradan şarkı kaldır")
        .add_integer_option(lambda o: o.set_name("sira").set_description("Sıra numarası").set_required(True).set_min_value(1)),
        cmd("tasi", "Sıradaki şarkının yerini değiştir")
        .add_integer_option(lambda o: o.set_name("nereden").set_description("Şu anki sıra").set_required(True).set_min_value(1))
        .add_integer_option(lambda o: o.set_name("nereye").set_description("Yeni sıra").set_required(True).set_min_value(1)),
        cmd("temizle", "Sırayı temizle (çalan şarkı devam eder)"),
        cmd("ayril", "Ses kanalından ayrıl"),
        cmd("247", "24/7 modunu aç/kapat (kanaldan hiç ayrılmaz)"),
        cmd("dj-rol", "DJ rolünü ayarla (boş = herkes kontrol edebilir)")
        .add_role_option(lambda o: o.set_name("rol").set_description("DJ rolü")),
    ]


CONTROL_COMMANDS = {"gec", "atla", "onceki", "duraklat", "devam", "durdur", "ses", "dongu", "karistir",
                    "kaldir", "tasi", "temizle", "ayril"}


# ============================================================== bot
class MusicBot:
    def __init__(self, data_path: str = "muzik_data.json", **client_options: Any) -> None:
        self.settings = Settings(data_path)
        self.client = Client(intents=[GatewayIntentBits.Guilds, GatewayIntentBits.GuildVoiceStates,
                                      GatewayIntentBits.GuildMembers], **client_options)
        self.music: Dict[str, GuildMusic] = {}
        self.search_results: Dict[str, List[Track]] = {}
        self._tasks: set = set()
        self.client.on("ready", self.on_ready)
        self.client.on("interactionCreate", self.on_interaction)
        self.client.on("voiceStateUpdate", self.on_voice_state)

    def spawn(self, coro) -> None:
        task = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def get_music(self, guild_id: str) -> GuildMusic:
        if guild_id not in self.music:
            self.music[guild_id] = GuildMusic(self, guild_id, self.settings.get(guild_id)["volume"])
        return self.music[guild_id]

    async def on_ready(self, _client) -> None:
        try:
            await self.client.application.commands.set(build_commands())
        except HTTPException as exc:
            log.error("Komutlar kaydedilemedi: %s", exc)
        print(f"🎵 {self.client.user.username} hazır!")

    # ---------------------------------------------------------- kontroller
    @staticmethod
    def user_voice(interaction) -> Optional[str]:
        member = interaction.member
        return member.voice.channel_id if member is not None else None

    def is_dj(self, interaction, gm: Optional[GuildMusic] = None) -> bool:
        member = interaction.member
        if member is None:
            return True
        guild = interaction.guild
        if (guild is not None and guild.owner_id == member.id) or member.permissions.has("ManageGuild"):
            return True
        dj_role = self.settings.get(interaction.guild_id)["dj_role"]
        if not dj_role or dj_role in member.roles:
            return True
        # Sadece kendi şarkısını geçebilir
        return gm is not None and gm.current is not None and gm.current.requester_id == member.id

    def check_control(self, interaction, gm: GuildMusic) -> Optional[str]:
        """Kontrol komutları için hata metni döndürür (sorun yoksa None)."""
        if gm.connection is None:
            return "Şu an bir ses kanalında değilim."
        user_channel = self.user_voice(interaction)
        if user_channel and user_channel != gm.connection.channel_id:
            return f"Benimle aynı ses kanalında olmalısın: <#{gm.connection.channel_id}>"
        if not self.is_dj(interaction, gm):
            return "Bu işlem için **DJ** rolü gerekli."
        return None

    # --------------------------------------------------------- etkileşimler
    async def on_interaction(self, interaction) -> None:
        if not interaction.guild_id:
            return
        try:
            if interaction.is_command():
                handler = getattr(self, "cmd_" + interaction.command_name.replace("-", "_"), None)
                if interaction.command_name == "247":
                    handler = self.cmd_stay
                if handler is None:
                    return
                gm = self.get_music(interaction.guild_id)
                if interaction.command_name in CONTROL_COMMANDS:
                    problem = self.check_control(interaction, gm)
                    if problem:
                        return await respond(interaction, embeds=[err(problem)], ephemeral=True)
                await handler(interaction, gm)
            elif interaction.is_button() and interaction.custom_id.startswith("music:"):
                await self.on_button(interaction)
            elif interaction.is_select_menu() and interaction.custom_id == "music:search":
                await self.on_search_pick(interaction)
        except Exception as exc:  # noqa: BLE001
            log.exception("Etkileşim hatası")
            try:
                await respond(interaction, embeds=[err(f"Bir hata oluştu: {exc}")], ephemeral=True)
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------ çözümleme
    async def resolve(self, query: str, requester_id: str) -> List[Track]:
        """Sorguyu şarkı listesine çevirir: yerel dosya, çalma listesi, link veya arama."""
        if os.path.isfile(query):
            return [Track(os.path.basename(query), query, 0, None, requester_id)]
        if query.startswith("http") and ("list=" in query or "/playlist" in query or "/sets/" in query):
            return await self.resolve_playlist(query, requester_id)
        info = await probe_audio_info(query)
        return [Track(info.title, info.url, info.duration, info.thumbnail, requester_id)]

    async def _yt_dlp_json(self, *args: str) -> Dict[str, Any]:
        process = await asyncio.create_subprocess_exec(
            *yt_dlp_command(), *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await asyncio.wait_for(process.communicate(), 60)
        if process.returncode != 0:
            raise RuntimeError(stderr.decode(errors="replace").strip()[:300] or "yt-dlp hatası")
        return json.loads(stdout.decode(errors="replace") or "{}")

    @staticmethod
    def _entry_track(entry: Dict[str, Any], requester_id: str) -> Optional[Track]:
        url = entry.get("webpage_url") or entry.get("url")
        if not url and entry.get("id"):
            url = f"https://www.youtube.com/watch?v={entry['id']}"
        if not url:
            return None
        if not url.startswith("http") and entry.get("id"):
            url = f"https://www.youtube.com/watch?v={entry['id']}"
        thumbs = entry.get("thumbnails") or []
        thumb = entry.get("thumbnail") or (thumbs[-1].get("url") if thumbs else None)
        return Track(entry.get("title") or "Bilinmeyen", url, int(entry.get("duration") or 0), thumb, requester_id)

    async def resolve_playlist(self, url: str, requester_id: str) -> List[Track]:
        data = await self._yt_dlp_json("--flat-playlist", "-J", "--no-warnings", "--playlist-end", str(MAX_PLAYLIST), url)
        tracks = [self._entry_track(e, requester_id) for e in data.get("entries") or []]
        return [t for t in tracks if t is not None]

    async def search(self, query: str, requester_id: str, count: int = 5) -> List[Track]:
        data = await self._yt_dlp_json("--flat-playlist", "-J", "--no-warnings", f"ytsearch{count}:{query}")
        tracks = [self._entry_track(e, requester_id) for e in data.get("entries") or []]
        return [t for t in tracks if t is not None]

    # ------------------------------------------------------------- bağlantı
    def ensure_connection(self, gm: GuildMusic, channel_id: str) -> None:
        conn = gm.connection
        if conn is not None and conn.state.status != VoiceConnectionStatus.Destroyed:
            return
        adapter = self.client.voice.adapters.get(gm.guild_id)
        if adapter is None:
            raise RuntimeError("Bu sunucu için ses adaptörü yok (bot sunucuyu henüz görmemiş olabilir).")
        conn = join_voice_channel(channel_id=channel_id, guild_id=gm.guild_id, adapter_creator=adapter)

        def on_state(old, new) -> None:
            if new.status == VoiceConnectionStatus.Disconnected and gm.connection is conn:
                self.spawn(self.leave(gm, notify_text="🔌 Ses kanalı bağlantısı koptu, sıra temizlendi."))

        conn.on("stateChange", on_state)
        conn.on("error", lambda e: log.warning("Ses bağlantı hatası: %s", e))
        conn.subscribe(gm.player)
        gm.connection = conn

    async def leave(self, gm: GuildMusic, notify_text: Optional[str] = None) -> None:
        self._cancel_idle(gm)
        gm.queue.clear()
        gm.current = None
        gm.transition = True
        try:
            gm.player.stop()
        finally:
            gm.transition = False
        conn, gm.connection = gm.connection, None
        if conn is not None:
            conn.destroy()
        if notify_text:
            await self.notify(gm, embeds=[ok(notify_text)])

    def _cancel_idle(self, gm: GuildMusic) -> None:
        if gm.idle_task is not None and not gm.idle_task.done() and gm.idle_task is not asyncio.current_task():
            gm.idle_task.cancel()
        gm.idle_task = None

    def schedule_idle_leave(self, gm: GuildMusic, reason: str) -> None:
        if self.settings.get(gm.guild_id)["stay"] or gm.connection is None:
            return
        self._cancel_idle(gm)

        async def waiter() -> None:
            await asyncio.sleep(IDLE_TIMEOUT)
            await self.leave(gm, notify_text=reason)

        gm.idle_task = asyncio.get_running_loop().create_task(waiter())

    # ----------------------------------------------------------------- çalma
    async def play_next(self, gm: GuildMusic, failed: bool = False) -> None:
        if gm.loop == "track" and gm.current is not None and not failed:
            return await self.play_track(gm, gm.current)
        if gm.current is not None:
            gm.history.append(gm.current)
            if gm.loop == "queue" and not failed:
                gm.queue.append(gm.current)
        if not gm.queue:
            gm.current = None
            await self.notify(gm, embeds=[ok("✅ Sıra bitti. `/cal` ile yeni şarkı ekleyebilirsin.")])
            self.schedule_idle_leave(gm, "👋 Bir süredir bir şey çalmadığı için kanaldan ayrıldım.")
            return
        await self.play_track(gm, gm.queue.pop(0))

    async def play_track(self, gm: GuildMusic, track: Track) -> None:
        self._cancel_idle(gm)
        gm.current = track
        resource = create_audio_resource(track.url, metadata=track)
        resource.set_volume(gm.volume / 100)
        gm.resource = resource
        gm.transition = True
        try:
            gm.player.play(resource)
        finally:
            gm.transition = False
        await self.notify(gm, embeds=[self.now_playing_embed(gm)], components=self.controls(gm))

    def skip(self, gm: GuildMusic) -> None:
        """Mevcut şarkıyı bitmiş say ve sıradakine geç (döngü 'şarkı' ise de geçer)."""
        loop, gm.loop = gm.loop, ("off" if gm.loop == "track" else gm.loop)
        self.spawn(self._skip_then_restore(gm, loop))

    async def _skip_then_restore(self, gm: GuildMusic, loop: str) -> None:
        try:
            await self.play_next(gm)
        finally:
            gm.loop = loop

    async def notify(self, gm: GuildMusic, **message: Any) -> None:
        if not gm.text_channel_id:
            return
        try:
            await self.client.rest.create_message(gm.guild_id, gm.text_channel_id, message)
        except HTTPException as exc:
            log.warning("Mesaj gönderilemedi: %s", exc)

    # ---------------------------------------------------------------- arayüz
    def now_playing_embed(self, gm: GuildMusic) -> EmbedBuilder:
        t = gm.current
        if t is None:
            return ok("Şu an bir şey çalmıyor.")
        status = gm.player.state.status
        icon = "⏸️ Duraklatıldı" if status in (AudioPlayerStatus.Paused, AudioPlayerStatus.AutoPaused) else "🎵 Şimdi Çalıyor"
        embed = (EmbedBuilder().set_title(icon).set_description(f"{t.link}\n\n{progress_bar(gm.position, t.duration)}")
                 .set_color(Colors.Blurple)
                 .add_fields({"name": "İsteyen", "value": f"<@{t.requester_id}>" if t.requester_id else "-", "inline": True},
                             {"name": "Ses", "value": f"🔊 %{gm.volume}", "inline": True},
                             {"name": "Döngü", "value": LOOP_NAMES[gm.loop], "inline": True},
                             {"name": "Sırada", "value": f"{len(gm.queue)} şarkı", "inline": True},
                             {"name": "Sıradaki", "value": gm.queue[0].link if gm.queue else "Yok", "inline": True}))
        if t.thumbnail:
            embed.set_thumbnail(t.thumbnail)
        return embed

    def controls(self, gm: GuildMusic) -> List[ActionRowBuilder]:
        paused = gm.player.state.status in (AudioPlayerStatus.Paused, AudioPlayerStatus.AutoPaused)

        def b(cid: str, emoji: str, style: ButtonStyle = ButtonStyle.Secondary) -> ButtonBuilder:
            return ButtonBuilder().set_custom_id(f"music:{cid}").set_emoji(emoji).set_style(style)

        return [
            ActionRowBuilder().add_components(
                b("prev", "⏮️"), b("pause", "▶️" if paused else "⏸️", ButtonStyle.Primary), b("skip", "⏭️"),
                b("stop", "⏹️", ButtonStyle.Danger), b("loop", "🔁", ButtonStyle.Success if gm.loop != "off" else ButtonStyle.Secondary)),
            ActionRowBuilder().add_components(
                b("voldown", "🔉"), b("volup", "🔊"), b("shuffle", "🔀"), b("queue", "📜"), b("refresh", "🔄")),
        ]

    def queue_embed(self, gm: GuildMusic, page: int = 1) -> EmbedBuilder:
        pages = max(1, (len(gm.queue) + PAGE_SIZE - 1) // PAGE_SIZE)
        page = max(1, min(page, pages))
        start = (page - 1) * PAGE_SIZE
        lines = [f"`{i + 1}.` {t.link} • `{fmt_time(t.duration)}` • <@{t.requester_id}>"
                 for i, t in enumerate(gm.queue[start:start + PAGE_SIZE], start=start)]
        total = sum(t.duration for t in gm.queue)
        now = f"**Çalıyor:** {gm.current.link}\n\n" if gm.current else ""
        return (EmbedBuilder().set_title(f"📜 Şarkı Sırası ({len(gm.queue)})")
                .set_description(now + ("\n".join(lines) or "Sıra boş."))
                .set_footer(text=f"Sayfa {page}/{pages} • Toplam süre {fmt_time(total)} • Döngü: {LOOP_NAMES[gm.loop]}")
                .set_color(Colors.Blurple))

    # ------------------------------------------------------------ komutlar
    async def add_tracks(self, interaction, gm: GuildMusic, tracks: List[Track]) -> None:
        space = MAX_QUEUE - len(gm.queue)
        if space <= 0:
            return await respond(interaction, embeds=[err(f"Sıra dolu (en fazla {MAX_QUEUE}).")])
        tracks = tracks[:space]
        gm.text_channel_id = interaction.channel_id
        self.ensure_connection(gm, self.user_voice(interaction))
        idle = gm.current is None
        gm.queue.extend(tracks)
        if len(tracks) == 1:
            t = tracks[0]
            text = (f"🎵 Çalınıyor: {t.link} `{fmt_time(t.duration)}`" if idle
                    else f"➕ Sıraya eklendi (#{len(gm.queue)}): {t.link} `{fmt_time(t.duration)}`")
            embed = ok(text)
            if t.thumbnail:
                embed.set_thumbnail(t.thumbnail)
        else:
            embed = ok(f"📃 **{len(tracks)}** şarkı sıraya eklendi.")
        await respond(interaction, embeds=[embed])
        if idle:
            await self.play_next(gm)

    async def cmd_cal(self, interaction, gm: GuildMusic) -> None:
        if not self.user_voice(interaction):
            return await respond(interaction, embeds=[err("Önce bir ses kanalına katıl!")], ephemeral=True)
        if gm.connection is not None and self.user_voice(interaction) != gm.connection.channel_id:
            return await respond(interaction, embeds=[err(f"Ben şu an <#{gm.connection.channel_id}> kanalındayım.")],
                                 ephemeral=True)
        await interaction.defer_reply()
        query = interaction.options.get_string("sarki", True)
        tracks = await self.resolve(query, interaction.user.id)
        if not tracks:
            return await respond(interaction, embeds=[err("Hiç sonuç bulunamadı.")])
        await self.add_tracks(interaction, gm, tracks)

    async def cmd_ara(self, interaction, gm: GuildMusic) -> None:
        if not self.user_voice(interaction):
            return await respond(interaction, embeds=[err("Önce bir ses kanalına katıl!")], ephemeral=True)
        await interaction.defer_reply()
        results = await self.search(interaction.options.get_string("sorgu", True), interaction.user.id)
        if not results:
            return await respond(interaction, embeds=[err("Sonuç bulunamadı.")])
        self.search_results[interaction.user.id] = results
        menu = StringSelectMenuBuilder().set_custom_id("music:search").set_placeholder("Bir şarkı seç").add_options(
            *[{"label": t.title[:100], "value": str(i), "description": fmt_time(t.duration)} for i, t in enumerate(results)])
        lines = [f"`{i + 1}.` {t.link} `{fmt_time(t.duration)}`" for i, t in enumerate(results)]
        await respond(interaction, embeds=[ok("\n".join(lines)).set_title("🔎 Arama Sonuçları")],
                      components=[ActionRowBuilder().add_components(menu)])

    async def on_search_pick(self, interaction) -> None:
        results = self.search_results.get(interaction.user.id)
        if not results:
            return await respond(interaction, embeds=[err("Bu arama sana ait değil veya süresi doldu.")], ephemeral=True)
        if not self.user_voice(interaction):
            return await respond(interaction, embeds=[err("Önce bir ses kanalına katıl!")], ephemeral=True)
        track = results[int(interaction.values[0])]
        del self.search_results[interaction.user.id]
        gm = self.get_music(interaction.guild_id)
        await interaction.update(embeds=[ok(f"Seçildi: {track.link}")], components=[])
        await self.add_tracks(interaction, gm, [track])

    async def cmd_sira(self, interaction, gm: GuildMusic) -> None:
        await respond(interaction, embeds=[self.queue_embed(gm, interaction.options.get_integer("sayfa") or 1)])

    async def cmd_simdi(self, interaction, gm: GuildMusic) -> None:
        await respond(interaction, embeds=[self.now_playing_embed(gm)],
                      components=self.controls(gm) if gm.current else None)

    async def cmd_gec(self, interaction, gm: GuildMusic) -> None:
        if gm.current is None:
            return await respond(interaction, embeds=[err("Çalan bir şarkı yok.")], ephemeral=True)
        await respond(interaction, embeds=[ok(f"⏭️ Geçildi: {gm.current.link}")])
        self.skip(gm)

    async def cmd_atla(self, interaction, gm: GuildMusic) -> None:
        index = interaction.options.get_integer("sira", True)
        if index > len(gm.queue):
            return await respond(interaction, embeds=[err(f"Sırada {len(gm.queue)} şarkı var.")], ephemeral=True)
        del gm.queue[: index - 1]
        await respond(interaction, embeds=[ok(f"⏩ {index}. şarkıya atlanıyor: {gm.queue[0].link}")])
        self.skip(gm)

    async def cmd_onceki(self, interaction, gm: GuildMusic) -> None:
        if not gm.history:
            return await respond(interaction, embeds=[err("Önceki şarkı yok.")], ephemeral=True)
        previous = gm.history.pop()
        if gm.current is not None:
            gm.queue.insert(0, gm.current)
        await respond(interaction, embeds=[ok(f"⏮️ Önceki şarkı: {previous.link}")])
        await self.play_track(gm, previous)

    async def cmd_duraklat(self, interaction, gm: GuildMusic) -> None:
        if gm.player.pause():
            return await respond(interaction, embeds=[ok("⏸️ Duraklatıldı.")])
        await respond(interaction, embeds=[err("Şu an çalan bir şey yok.")], ephemeral=True)

    async def cmd_devam(self, interaction, gm: GuildMusic) -> None:
        if gm.player.unpause():
            return await respond(interaction, embeds=[ok("▶️ Devam ediliyor.")])
        await respond(interaction, embeds=[err("Duraklatılmış bir şey yok.")], ephemeral=True)

    async def cmd_durdur(self, interaction, gm: GuildMusic) -> None:
        gm.queue.clear()
        gm.current = None
        gm.transition = True
        try:
            gm.player.stop()
        finally:
            gm.transition = False
        await respond(interaction, embeds=[ok("⏹️ Durduruldu ve sıra temizlendi.")])
        self.schedule_idle_leave(gm, "👋 Bir süredir bir şey çalmadığı için kanaldan ayrıldım.")

    def set_volume(self, gm: GuildMusic, value: int) -> None:
        gm.volume = max(0, min(200, value))
        if gm.resource is not None:
            gm.resource.set_volume(gm.volume / 100)
        self.settings.get(gm.guild_id)["volume"] = gm.volume
        self.settings.save()

    async def cmd_ses(self, interaction, gm: GuildMusic) -> None:
        self.set_volume(gm, interaction.options.get_integer("seviye", True))
        await respond(interaction, embeds=[ok(f"🔊 Ses seviyesi: %{gm.volume}")])

    async def cmd_dongu(self, interaction, gm: GuildMusic) -> None:
        gm.loop = interaction.options.get_string("mod", True)
        await respond(interaction, embeds=[ok(f"Döngü: {LOOP_NAMES[gm.loop]}")])

    async def cmd_karistir(self, interaction, gm: GuildMusic) -> None:
        if len(gm.queue) < 2:
            return await respond(interaction, embeds=[err("Karıştırmak için sırada en az 2 şarkı olmalı.")], ephemeral=True)
        random.shuffle(gm.queue)
        await respond(interaction, embeds=[ok(f"🔀 {len(gm.queue)} şarkı karıştırıldı.")])

    async def cmd_kaldir(self, interaction, gm: GuildMusic) -> None:
        index = interaction.options.get_integer("sira", True)
        if index > len(gm.queue):
            return await respond(interaction, embeds=[err(f"Sırada {len(gm.queue)} şarkı var.")], ephemeral=True)
        removed = gm.queue.pop(index - 1)
        await respond(interaction, embeds=[ok(f"🗑️ Kaldırıldı: {removed.link}")])

    async def cmd_tasi(self, interaction, gm: GuildMusic) -> None:
        src, dst = interaction.options.get_integer("nereden", True), interaction.options.get_integer("nereye", True)
        if src > len(gm.queue) or dst > len(gm.queue):
            return await respond(interaction, embeds=[err(f"Sırada {len(gm.queue)} şarkı var.")], ephemeral=True)
        track = gm.queue.pop(src - 1)
        gm.queue.insert(dst - 1, track)
        await respond(interaction, embeds=[ok(f"↕️ {track.link} → {dst}. sıra")])

    async def cmd_temizle(self, interaction, gm: GuildMusic) -> None:
        count = len(gm.queue)
        gm.queue.clear()
        await respond(interaction, embeds=[ok(f"🧹 Sıradan {count} şarkı temizlendi.")])

    async def cmd_ayril(self, interaction, gm: GuildMusic) -> None:
        await self.leave(gm)
        await respond(interaction, embeds=[ok("👋 Ses kanalından ayrıldım.")])

    async def cmd_stay(self, interaction, gm: GuildMusic) -> None:
        if not self._is_admin(interaction):
            return await respond(interaction, embeds=[err("Bu ayar için **Sunucuyu Yönet** izni gerekli.")], ephemeral=True)
        cfg = self.settings.get(interaction.guild_id)
        cfg["stay"] = not cfg["stay"]
        self.settings.save()
        if cfg["stay"]:
            self._cancel_idle(gm)
        await respond(interaction, embeds=[ok(f"24/7 modu **{'açık' if cfg['stay'] else 'kapalı'}**.")])

    async def cmd_dj_rol(self, interaction, gm: GuildMusic) -> None:
        if not self._is_admin(interaction):
            return await respond(interaction, embeds=[err("Bu ayar için **Sunucuyu Yönet** izni gerekli.")], ephemeral=True)
        role = interaction.options.get_role("rol")
        role_id = str(role.get("id") if isinstance(role, dict) else role) if role else None
        self.settings.get(interaction.guild_id)["dj_role"] = role_id
        self.settings.save()
        await respond(interaction, embeds=[ok(f"🎧 DJ rolü: <@&{role_id}>" if role_id else "🎧 DJ rolü kaldırıldı, herkes kontrol edebilir.")])

    @staticmethod
    def _is_admin(interaction) -> bool:
        member, guild = interaction.member, interaction.guild
        if member is None:
            return False
        return (guild is not None and guild.owner_id == member.id) or member.permissions.has("ManageGuild")

    # ------------------------------------------------------------- butonlar
    async def on_button(self, interaction) -> None:
        gm = self.get_music(interaction.guild_id)
        action = interaction.custom_id.split(":", 1)[1]
        if action == "queue":
            return await respond(interaction, embeds=[self.queue_embed(gm)], ephemeral=True)
        problem = self.check_control(interaction, gm)
        if problem:
            return await respond(interaction, embeds=[err(problem)], ephemeral=True)
        note = None
        if action == "pause":
            if not gm.player.pause():
                gm.player.unpause()
        elif action == "skip":
            if gm.current is None:
                return await respond(interaction, embeds=[err("Çalan bir şarkı yok.")], ephemeral=True)
            await interaction.update(embeds=[ok(f"⏭️ Geçildi: {gm.current.link}")], components=[])
            return self.skip(gm)
        elif action == "prev":
            if not gm.history:
                return await respond(interaction, embeds=[err("Önceki şarkı yok.")], ephemeral=True)
            previous = gm.history.pop()
            if gm.current is not None:
                gm.queue.insert(0, gm.current)
            await interaction.update(embeds=[ok(f"⏮️ Önceki şarkı: {previous.link}")], components=[])
            return await self.play_track(gm, previous)
        elif action == "stop":
            await self.leave(gm)
            return await interaction.update(embeds=[ok("⏹️ Durduruldu ve kanaldan ayrıldım.")], components=[])
        elif action == "loop":
            gm.loop = {"off": "track", "track": "queue", "queue": "off"}[gm.loop]
            note = f"Döngü: {LOOP_NAMES[gm.loop]}"
        elif action == "shuffle":
            random.shuffle(gm.queue)
            note = "🔀 Sıra karıştırıldı."
        elif action in ("volup", "voldown"):
            self.set_volume(gm, gm.volume + (10 if action == "volup" else -10))
        embed = self.now_playing_embed(gm)
        if note:
            embed.set_footer(text=note)
        await interaction.update(embeds=[embed], components=self.controls(gm) if gm.current else [])

    # --------------------------------------------------------- ses olayları
    def on_voice_state(self, data: Dict[str, Any]) -> None:
        """Bot'un kanalında dinleyici kalmazsa duraklatır ve bir süre sonra ayrılır."""
        guild_id = str(data.get("guild_id"))
        gm = self.music.get(guild_id)
        if gm is None or gm.connection is None:
            return
        guild = self.client.guilds.get(guild_id)
        if guild is None:
            return
        bot_id = self.client.user.id if self.client.user else None
        channel = gm.connection.channel_id
        listeners = [m for m in guild.members.values() if m.voice.channel_id == channel and m.id != bot_id and not m.user.bot]
        if listeners:
            if gm.idle_task is not None and gm.current is not None:
                self._cancel_idle(gm)
                gm.player.unpause()
        elif gm.current is not None:
            gm.player.pause()
            self.schedule_idle_leave(gm, "👋 Kanalda kimse kalmadığı için ayrıldım.")

    def run(self, token: str) -> None:
        self.client.run(token)


if __name__ == "__main__":
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise SystemExit("BOT_TOKEN ortam değişkeni ayarlanmamış. Windows: set BOT_TOKEN=tokenin")
    path = os.environ.get("MUZIK_DATA", os.path.join(os.path.dirname(os.path.abspath(__file__)), "muzik_data.json"))
    MusicBot(path).run(token)
