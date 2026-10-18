"""Gelişmiş Moderasyon Botu altyapısı (JubbioPy).

Özellikler
----------
Moderasyon komutları
  • /ban (süreli ban dahil), /unban, /kick, /sustur (timeout), /susturma-kaldir
  • /uyari ver | liste | sil | temizle — uyarı sistemi, eşiklere göre otomatik ceza
  • /sicil — kullanıcının tüm ceza geçmişi, /vaka — tek bir vaka
  • /temizle — toplu mesaj silme (isteğe bağlı kullanıcı filtresi)
  • /kilit, /kilit-ac — kanalı yazmaya kapat/aç
  • /rol ver | al, /isim — rol ve takma ad yönetimi
  • Her işlem vaka numarasıyla mod-log kanalına yazılır, cezalıya DM gönderilir

Otomatik moderasyon (AutoMod)
  • Küfür / yasaklı kelime filtresi, link engeli, davet engeli
  • Büyük harf (caps) filtresi, toplu etiket (mention) spam'i, mesaj spam'i
  • İhlalde mesaj silinir + otomatik uyarı (spam'de susturma)
  • Muaf roller / kanallar, yetkililer otomatik muaf

Kayıtlar
  • Silinen / düzenlenen mesaj kaydı, giriş / çıkış kaydı (hesap yaşıyla)

Tüm ayarlar ve vakalar ``moderasyon_data.json`` dosyasında kalıcıdır.

Çalıştırma (Windows)::

    set BOT_TOKEN=tokenin
    python examples\\moderasyon_bot\\bot.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from collections import OrderedDict, defaultdict, deque
from typing import Any, Deque, Dict, List, Optional, Tuple

from jubbiopy import (
    ChannelType,
    Client,
    Colors,
    EmbedBuilder,
    GatewayIntentBits,
    HTTPException,
    PermissionFlagsBits,
    SlashCommandBuilder,
    SnowflakeUtil,
)

log = logging.getLogger("moderasyon_bot")

P = PermissionFlagsBits
MAX_TIMEOUT = 28 * 24 * 3600  # sn
MESSAGE_CACHE_SIZE = 5000
LINK_RE = re.compile(r"(https?://|www\.)\S+", re.IGNORECASE)
INVITE_RE = re.compile(r"(jubbio\.(com|gg)/(invite|davet)/|discord\.(gg|com/invite)/)\S+", re.IGNORECASE)
MENTION_RE = re.compile(r"<@[!&]?\d+>")
DURATION_RE = re.compile(r"(\d+)\s*(sn|sa|dk|hf|s|m|h|g|d|w)", re.IGNORECASE)
UNITS = {"s": 1, "sn": 1, "m": 60, "dk": 60, "h": 3600, "sa": 3600, "d": 86400, "g": 86400, "w": 604800, "hf": 604800}

CASE_NAMES = {
    "ban": "🔨 Ban", "tempban": "⏳ Süreli Ban", "unban": "🔓 Ban Kaldırma", "kick": "👢 Atma",
    "timeout": "🔇 Susturma", "untimeout": "🔊 Susturma Kaldırma", "warn": "⚠️ Uyarı",
}
CASE_COLORS = {"ban": Colors.DarkRed, "tempban": Colors.DarkRed, "kick": Colors.Orange, "timeout": Colors.Gold,
               "warn": Colors.Yellow, "unban": Colors.Green, "untimeout": Colors.Green}


# ============================================================== yardımcılar
def parse_duration(text: Optional[str]) -> Optional[int]:
    """'10m', '1sa30dk', '2g', '45s' gibi süreleri saniyeye çevirir."""
    if not text:
        return None
    text = text.strip().lower()
    if text.isdigit():
        return int(text) * 60  # sadece sayı = dakika
    total, consumed = 0, 0
    for match in DURATION_RE.finditer(text):
        total += int(match.group(1)) * UNITS[match.group(2)]
        consumed += len(match.group(0))
    if total <= 0 or consumed < len(text.replace(" ", "")):
        return None
    return total


def fmt_duration(seconds: int) -> str:
    parts = []
    for name, size in (("gün", 86400), ("saat", 3600), ("dakika", 60), ("saniye", 1)):
        if seconds >= size:
            parts.append(f"{seconds // size} {name}")
            seconds %= size
    return " ".join(parts[:2]) or "0 saniye"


def err(text: str) -> EmbedBuilder:
    return EmbedBuilder().set_description(f"❌ {text}").set_color(Colors.Red)


def ok(text: str) -> EmbedBuilder:
    return EmbedBuilder().set_description(f"✅ {text}").set_color(Colors.Green)


async def respond(interaction, content: Optional[str] = None, **kwargs: Any) -> None:
    if interaction.deferred:
        kwargs.pop("ephemeral", None)
        await interaction.edit_reply(content, **kwargs)
    elif interaction.replied:
        await interaction.follow_up(content, **kwargs)
    else:
        await interaction.reply(content, **kwargs)


def _id(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, dict):
        value = value.get("id")
    text = str(value).strip("<@&#!>")
    return text or None


# ============================================================== depolama
class Storage:
    def __init__(self, path: str) -> None:
        self.path = path
        self.data: Dict[str, Any] = {"guilds": {}}
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                self.data = json.load(fh)

    def guild(self, guild_id: str) -> Dict[str, Any]:
        guilds = self.data.setdefault("guilds", {})
        if guild_id not in guilds:
            guilds[guild_id] = {
                "mod_role": None, "log_channel": None, "message_log_channel": None, "join_log_channel": None,
                "warn_actions": [{"count": 3, "action": "timeout", "seconds": 3600},
                                 {"count": 5, "action": "kick", "seconds": 0},
                                 {"count": 7, "action": "ban", "seconds": 0}],
                "automod": {
                    "enabled": False, "bad_words": [], "block_links": False, "block_invites": True,
                    "caps_percent": 0, "caps_min_length": 10, "mention_limit": 5,
                    "spam_count": 5, "spam_seconds": 5, "spam_timeout": 300,
                    "exempt_roles": [], "exempt_channels": [],
                },
                "cases": [], "tempbans": [],
            }
        return guilds[guild_id]

    def save(self) -> None:
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)


# ============================================================== komutlar
def build_commands() -> List[SlashCommandBuilder]:
    def cmd(name: str, desc: str, perm: int) -> SlashCommandBuilder:
        return SlashCommandBuilder().set_name(name).set_description(desc).set_default_member_permissions(perm)

    def user(o, desc="Kullanıcı"):
        return o.set_name("kullanici").set_description(desc).set_required(True)

    def reason(o):
        return o.set_name("sebep").set_description("Sebep").set_max_length(500)

    return [
        cmd("ban", "Kullanıcıyı yasakla", P.BanMembers).add_user_option(user).add_string_option(reason)
        .add_string_option(lambda o: o.set_name("sure").set_description("Süreli ban: 1g, 12sa, 1hf (boş = kalıcı)"))
        .add_integer_option(lambda o: o.set_name("mesaj_sil").set_description("Son kaç günün mesajları silinsin (0-7)")
                            .set_min_value(0).set_max_value(7)),
        cmd("unban", "Yasağı kaldır", P.BanMembers)
        .add_string_option(lambda o: o.set_name("kullanici_id").set_description("Kullanıcı ID").set_required(True))
        .add_string_option(reason),
        cmd("kick", "Kullanıcıyı sunucudan at", P.KickMembers).add_user_option(user).add_string_option(reason),
        cmd("sustur", "Kullanıcıyı sustur (zaman aşımı)", P.ModerateMembers).add_user_option(user)
        .add_string_option(lambda o: o.set_name("sure").set_description("Süre: 10dk, 1sa, 1g (en fazla 28g)").set_required(True))
        .add_string_option(reason),
        cmd("susturma-kaldir", "Susturmayı kaldır", P.ModerateMembers).add_user_option(user).add_string_option(reason),
        cmd("uyari", "Uyarı sistemi", P.ModerateMembers)
        .add_subcommand(lambda s: s.set_name("ver").set_description("Uyarı ver").add_user_option(user)
                        .add_string_option(lambda o: reason(o).set_required(True)))
        .add_subcommand(lambda s: s.set_name("liste").set_description("Uyarıları listele").add_user_option(user))
        .add_subcommand(lambda s: s.set_name("sil").set_description("Bir uyarıyı sil")
                        .add_integer_option(lambda o: o.set_name("vaka").set_description("Vaka numarası").set_required(True)))
        .add_subcommand(lambda s: s.set_name("temizle").set_description("Tüm uyarıları temizle").add_user_option(user)),
        cmd("sicil", "Kullanıcının ceza geçmişi", P.ModerateMembers).add_user_option(user),
        cmd("vaka", "Vaka bilgisini göster", P.ModerateMembers)
        .add_integer_option(lambda o: o.set_name("numara").set_description("Vaka numarası").set_required(True)),
        cmd("temizle", "Toplu mesaj sil", P.ManageMessages)
        .add_integer_option(lambda o: o.set_name("miktar").set_description("1-100").set_required(True).set_min_value(1).set_max_value(100))
        .add_user_option(lambda o: o.set_name("kullanici").set_description("Sadece bu kullanıcının mesajları")),
        cmd("kilit", "Kanalı yazmaya kapat", P.ManageChannels)
        .add_channel_option(lambda o: o.set_name("kanal").set_description("Kanal").add_channel_types(ChannelType.GuildText))
        .add_string_option(reason),
        cmd("kilit-ac", "Kanalın kilidini aç", P.ManageChannels)
        .add_channel_option(lambda o: o.set_name("kanal").set_description("Kanal").add_channel_types(ChannelType.GuildText)),
        cmd("rol", "Rol ver / al", P.ManageRoles)
        .add_subcommand(lambda s: s.set_name("ver").set_description("Rol ver").add_user_option(user)
                        .add_role_option(lambda o: o.set_name("rol").set_description("Rol").set_required(True)))
        .add_subcommand(lambda s: s.set_name("al").set_description("Rol al").add_user_option(user)
                        .add_role_option(lambda o: o.set_name("rol").set_description("Rol").set_required(True))),
        cmd("isim", "Takma adı değiştir", P.ManageGuild).add_user_option(user)
        .add_string_option(lambda o: o.set_name("yeni").set_description("Yeni takma ad (boş = sıfırla)").set_max_length(32)),
        cmd("ayarla", "Moderasyon ayarları", P.ManageGuild)
        .add_subcommand(lambda s: s.set_name("log").set_description("Mod-log kanalı")
                        .add_channel_option(lambda o: o.set_name("kanal").set_description("Kanal").set_required(True)))
        .add_subcommand(lambda s: s.set_name("mesaj-log").set_description("Silinen/düzenlenen mesaj kaydı kanalı")
                        .add_channel_option(lambda o: o.set_name("kanal").set_description("Kanal").set_required(True)))
        .add_subcommand(lambda s: s.set_name("giris-log").set_description("Giriş/çıkış kaydı kanalı")
                        .add_channel_option(lambda o: o.set_name("kanal").set_description("Kanal").set_required(True)))
        .add_subcommand(lambda s: s.set_name("mod-rol").set_description("Moderatör rolü")
                        .add_role_option(lambda o: o.set_name("rol").set_description("Rol").set_required(True)))
        .add_subcommand(lambda s: s.set_name("uyari-cezasi").set_description("Uyarı eşiğine otomatik ceza")
                        .add_integer_option(lambda o: o.set_name("esik").set_description("Uyarı sayısı").set_required(True)
                                            .set_min_value(1).set_max_value(50))
                        .add_string_option(lambda o: o.set_name("eylem").set_description("Ceza").set_required(True)
                                           .add_choices({"name": "Sustur", "value": "timeout"}, {"name": "At", "value": "kick"},
                                                        {"name": "Banla", "value": "ban"}, {"name": "Kaldır", "value": "none"}))
                        .add_string_option(lambda o: o.set_name("sure").set_description("Susturma süresi (ör. 1sa)")))
        .add_subcommand(lambda s: s.set_name("goster").set_description("Ayarları göster")),
        cmd("automod", "Otomatik moderasyon", P.ManageGuild)
        .add_subcommand(lambda s: s.set_name("durum").set_description("AutoMod'u aç/kapat")
                        .add_boolean_option(lambda o: o.set_name("acik").set_description("Açık mı?").set_required(True)))
        .add_subcommand(lambda s: s.set_name("kelime-ekle").set_description("Yasaklı kelime ekle")
                        .add_string_option(lambda o: o.set_name("kelime").set_description("Kelime(ler), virgülle").set_required(True)))
        .add_subcommand(lambda s: s.set_name("kelime-sil").set_description("Yasaklı kelime sil")
                        .add_string_option(lambda o: o.set_name("kelime").set_description("Kelime").set_required(True)))
        .add_subcommand(lambda s: s.set_name("filtre").set_description("Filtreleri ayarla")
                        .add_boolean_option(lambda o: o.set_name("link").set_description("Link engeli"))
                        .add_boolean_option(lambda o: o.set_name("davet").set_description("Davet linki engeli"))
                        .add_integer_option(lambda o: o.set_name("buyuk_harf").set_description("Büyük harf % sınırı (0 = kapalı)")
                                            .set_min_value(0).set_max_value(100))
                        .add_integer_option(lambda o: o.set_name("etiket").set_description("Mesaj başı etiket sınırı (0 = kapalı)")
                                            .set_min_value(0).set_max_value(50))
                        .add_integer_option(lambda o: o.set_name("spam_mesaj").set_description("Spam: kaç mesaj (0 = kapalı)")
                                            .set_min_value(0).set_max_value(30))
                        .add_integer_option(lambda o: o.set_name("spam_saniye").set_description("Spam: kaç saniyede")
                                            .set_min_value(1).set_max_value(60)))
        .add_subcommand(lambda s: s.set_name("muaf").set_description("Rol veya kanalı muaf tut / çıkar")
                        .add_role_option(lambda o: o.set_name("rol").set_description("Rol"))
                        .add_channel_option(lambda o: o.set_name("kanal").set_description("Kanal")))
        .add_subcommand(lambda s: s.set_name("goster").set_description("AutoMod ayarlarını göster")),
    ]


# ============================================================== bot
class ModerationBot:
    def __init__(self, data_path: str = "moderasyon_data.json", **client_options: Any) -> None:
        self.store = Storage(data_path)
        self.client = Client(intents=[
            GatewayIntentBits.Guilds, GatewayIntentBits.GuildMembers, GatewayIntentBits.GuildModeration,
            GatewayIntentBits.GuildMessages, GatewayIntentBits.MessageContent,
        ], **client_options)
        self.messages: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()  # silinen mesaj kaydı için önbellek
        self.spam: Dict[Tuple[str, str], Deque[float]] = defaultdict(deque)
        self._tasks: set = set()
        self._tempban_started = False
        self.client.on("ready", self.on_ready)
        self.client.on("interactionCreate", self.on_interaction)
        self.client.on("messageCreate", self.on_message)
        self.client.on("messageDelete", self.on_message_delete)
        self.client.on("messageUpdate", self.on_message_update)
        self.client.on("guildMemberAdd", self.on_member_join)
        self.client.on("guildMemberRemove", self.on_member_leave)

    @property
    def rest(self):
        return self.client.rest

    def spawn(self, coro) -> None:
        task = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def on_ready(self, _client) -> None:
        try:
            await self.client.application.commands.set(build_commands())
        except HTTPException as exc:
            log.error("Komutlar kaydedilemedi: %s", exc)
        if not self._tempban_started:  # yeniden bağlanmalarda (READY) ikinci kez başlatma
            self._tempban_started = True
            self.spawn(self.tempban_loop())
        print(f"🛡️ {self.client.user.username} hazır! {len(self.client.guilds)} sunucu.")

    # --------------------------------------------------------- yetkiler
    def is_admin(self, member, guild_id: str) -> bool:
        if member is None:
            return False
        guild = self.client.guilds.get(guild_id)
        if guild is not None and guild.owner_id == member.id:
            return True
        return member.permissions.has("Administrator") or member.permissions.has("ManageGuild")

    def is_mod(self, member, guild_id: str, permission: Optional[str] = None) -> bool:
        if self.is_admin(member, guild_id):
            return True
        if member is None:
            return False
        mod_role = self.store.guild(guild_id)["mod_role"]
        if mod_role and mod_role in member.roles:
            return True
        return bool(permission) and member.permissions.has(permission)

    def target_problem(self, interaction, target_id: str) -> Optional[str]:
        """Hedef kullanıcıya işlem yapılabilir mi? Sorun varsa açıklama döndürür."""
        if target_id == interaction.user.id:
            return "Kendine işlem yapamazsın."
        if self.client.user and target_id == self.client.user.id:
            return "Bana işlem yapamazsın."
        guild = interaction.guild
        if guild is not None and guild.owner_id == target_id:
            return "Sunucu sahibine işlem yapılamaz."
        target = guild.members.get(target_id) if guild is not None else None
        if target is not None and self.is_mod(target, interaction.guild_id) and not self.is_admin(interaction.member, interaction.guild_id):
            return "Diğer yetkililere sadece yöneticiler işlem yapabilir."
        return None

    # ------------------------------------------------------------ vakalar
    def new_case(self, guild_id: str, kind: str, user_id: str, user_name: str, mod_id: str, reason: Optional[str],
                 seconds: int = 0) -> Dict[str, Any]:
        """Vaka kaydı hazırlar (kaydetmez; işlem başarılı olunca ``store_case`` ile kaydedilir)."""
        cfg = self.store.guild(guild_id)
        return {"id": len(cfg["cases"]) + 1, "type": kind, "user_id": user_id, "user_name": user_name,
                "mod_id": mod_id, "reason": reason or "Belirtilmedi", "time": time.time(), "seconds": seconds,
                "active": True}

    def store_case(self, guild_id: str, case: Dict[str, Any]) -> None:
        cfg = self.store.guild(guild_id)
        case["id"] = len(cfg["cases"]) + 1
        cfg["cases"].append(case)
        self.store.save()

    def case_embed(self, case: Dict[str, Any]) -> EmbedBuilder:
        embed = (EmbedBuilder().set_title(f"{CASE_NAMES.get(case['type'], case['type'])} | Vaka #{case['id']}")
                 .set_color(CASE_COLORS.get(case["type"], Colors.Blurple))
                 .add_fields({"name": "Kullanıcı", "value": f"<@{case['user_id']}> (`{case['user_id']}`)", "inline": True},
                             {"name": "Yetkili", "value": f"<@{case['mod_id']}>" if case["mod_id"] != "automod" else "🤖 AutoMod",
                              "inline": True},
                             {"name": "Tarih", "value": f"<t:{int(case['time'])}:f>", "inline": True},
                             {"name": "Sebep", "value": case["reason"][:1024]}))
        if case.get("seconds"):
            embed.add_fields({"name": "Süre", "value": fmt_duration(case["seconds"]), "inline": True})
        if not case.get("active", True):
            embed.set_footer(text="Bu vaka kaldırıldı / geçersiz")
        return embed

    async def mod_log(self, guild_id: str, embed: EmbedBuilder, key: str = "log_channel") -> None:
        channel_id = self.store.guild(guild_id).get(key)
        if not channel_id:
            return
        try:
            await self.rest.create_message(guild_id, channel_id, {"embeds": [embed]})
        except HTTPException as exc:
            log.warning("Log yazılamadı: %s", exc)

    async def dm(self, user_id: str, guild_id: str, case: Dict[str, Any]) -> None:
        guild = self.client.guilds.get(guild_id)
        text = {
            "ban": "sunucusundan **yasaklandın**", "tempban": "sunucusundan **süreli yasaklandın**",
            "kick": "sunucusundan **atıldın**", "timeout": "sunucusunda **susturuldun**", "warn": "sunucusunda **uyarı aldın**",
        }.get(case["type"])
        if not text:
            return
        embed = (EmbedBuilder().set_description(f"**{guild.name if guild else 'Bir'}** {text}.").set_color(Colors.Orange)
                 .add_fields({"name": "Sebep", "value": case["reason"][:1024]}))
        if case.get("seconds"):
            embed.add_fields({"name": "Süre", "value": fmt_duration(case["seconds"])})
        try:
            await self.rest.create_dm_message(user_id, {"embeds": [embed]})
        except HTTPException:
            pass  # DM kapalı olabilir

    async def punish(self, guild_id: str, kind: str, user_id: str, user_name: str, mod_id: str,
                     reason: Optional[str], seconds: int = 0, delete_days: int = 0) -> Dict[str, Any]:
        """Cezayı uygular, vaka açar, DM ve log gönderir."""
        audit = f"{reason or 'Belirtilmedi'} (Yetkili: {mod_id})"
        case = self.new_case(guild_id, kind, user_id, user_name, mod_id, reason, seconds)
        # DM işlemden önce: atılan/banlanan kullanıcıya sonra ulaşılamayabilir
        if kind in ("ban", "tempban", "kick", "timeout", "warn"):
            await self.dm(user_id, guild_id, case)
        if kind in ("ban", "tempban"):
            await self.rest.ban_member(guild_id, user_id, delete_message_days=delete_days or None, reason=audit)
            if kind == "tempban":
                self.store.guild(guild_id)["tempbans"].append({"user_id": user_id, "until": time.time() + seconds})
                self.store.save()
        elif kind == "unban":
            await self.rest.unban_member(guild_id, user_id, audit)
            cfg = self.store.guild(guild_id)
            cfg["tempbans"] = [t for t in cfg["tempbans"] if t["user_id"] != user_id]
            self.store.save()
        elif kind == "kick":
            await self.rest.kick_member(guild_id, user_id, audit)
        elif kind == "timeout":
            await self.rest.timeout_member(guild_id, user_id, seconds * 1000, audit)
        elif kind == "untimeout":
            await self.rest.timeout_member(guild_id, user_id, None, audit)
        self.store_case(guild_id, case)
        await self.mod_log(guild_id, self.case_embed(case))
        if kind == "warn":
            await self.check_warn_actions(guild_id, user_id, user_name)
        return case

    def active_warnings(self, guild_id: str, user_id: str) -> List[Dict[str, Any]]:
        return [c for c in self.store.guild(guild_id)["cases"]
                if c["type"] == "warn" and c["user_id"] == user_id and c.get("active", True)]

    async def check_warn_actions(self, guild_id: str, user_id: str, user_name: str) -> None:
        count = len(self.active_warnings(guild_id, user_id))
        for rule in self.store.guild(guild_id)["warn_actions"]:
            if rule["count"] == count:
                reason = f"Otomatik: {count} uyarıya ulaştı"
                kind = rule["action"]
                try:
                    await self.punish(guild_id, kind, user_id, user_name, "automod", reason, rule.get("seconds") or 0)
                except HTTPException as exc:
                    log.warning("Otomatik ceza uygulanamadı: %s", exc)

    async def tempban_loop(self) -> None:
        """Süresi dolan süreli banları kaldırır."""
        while True:
            now = time.time()
            for guild_id, cfg in list(self.store.data.get("guilds", {}).items()):
                for entry in [t for t in cfg.get("tempbans", []) if t["until"] <= now]:
                    try:
                        await self.punish(guild_id, "unban", entry["user_id"], entry["user_id"], "automod", "Süreli ban sona erdi")
                    except HTTPException as exc:
                        log.warning("Süreli ban kaldırılamadı: %s", exc)
                        cfg["tempbans"] = [t for t in cfg["tempbans"] if t is not entry]
                        self.store.save()
            await asyncio.sleep(30)

    # --------------------------------------------------------- etkileşimler
    PERMISSIONS = {
        "ban": "BanMembers", "unban": "BanMembers", "kick": "KickMembers", "sustur": "ModerateMembers",
        "susturma-kaldir": "ModerateMembers", "uyari": "ModerateMembers", "sicil": "ModerateMembers",
        "vaka": "ModerateMembers", "temizle": "ManageMessages", "kilit": "ManageChannels", "kilit-ac": "ManageChannels",
        "rol": "ManageRoles", "isim": "ManageGuild",
    }

    async def on_interaction(self, interaction) -> None:
        if not interaction.is_command() or not interaction.guild_id:
            return
        name = interaction.command_name
        handler = getattr(self, "cmd_" + name.replace("-", "_"), None)
        if handler is None:
            return
        try:
            if name in ("ayarla", "automod"):
                if not self.is_admin(interaction.member, interaction.guild_id):
                    return await respond(interaction, embeds=[err("Bu komut için **Sunucuyu Yönet** izni gerekli.")], ephemeral=True)
            elif not self.is_mod(interaction.member, interaction.guild_id, self.PERMISSIONS.get(name)):
                return await respond(interaction, embeds=[err("Bu komutu kullanma yetkin yok.")], ephemeral=True)
            await handler(interaction)
        except HTTPException as exc:
            await respond(interaction, embeds=[err(f"API hatası ({exc.status}): {exc.text[:300]}")], ephemeral=True)
        except Exception as exc:  # noqa: BLE001
            log.exception("Komut hatası")
            try:
                await respond(interaction, embeds=[err(f"Bir hata oluştu: {exc}")], ephemeral=True)
            except Exception:  # noqa: BLE001
                pass

    def _target(self, interaction):
        user = interaction.options.get_user("kullanici", True)
        return user, self.target_problem(interaction, user.id)

    async def cmd_ban(self, interaction) -> None:
        user, problem = self._target(interaction)
        if problem:
            return await respond(interaction, embeds=[err(problem)], ephemeral=True)
        opts = interaction.options
        duration_text = opts.get_string("sure")
        seconds = parse_duration(duration_text) if duration_text else 0
        if duration_text and not seconds:
            return await respond(interaction, embeds=[err("Geçersiz süre. Örnek: `1g`, `12sa`, `1hf`")], ephemeral=True)
        kind = "tempban" if seconds else "ban"
        case = await self.punish(interaction.guild_id, kind, user.id, user.username, interaction.user.id,
                                 opts.get_string("sebep"), seconds or 0, opts.get_integer("mesaj_sil") or 0)
        extra = f" ({fmt_duration(seconds)})" if seconds else ""
        await respond(interaction, embeds=[ok(f"<@{user.id}> yasaklandı{extra}. Vaka #{case['id']}")])

    async def cmd_unban(self, interaction) -> None:
        user_id = _id(interaction.options.get_string("kullanici_id", True))
        if not user_id or not user_id.isdigit():
            return await respond(interaction, embeds=[err("Geçerli bir kullanıcı ID'si gir.")], ephemeral=True)
        case = await self.punish(interaction.guild_id, "unban", user_id, user_id, interaction.user.id,
                                 interaction.options.get_string("sebep"))
        await respond(interaction, embeds=[ok(f"`{user_id}` kullanıcısının yasağı kaldırıldı. Vaka #{case['id']}")])

    async def cmd_kick(self, interaction) -> None:
        user, problem = self._target(interaction)
        if problem:
            return await respond(interaction, embeds=[err(problem)], ephemeral=True)
        case = await self.punish(interaction.guild_id, "kick", user.id, user.username, interaction.user.id,
                                 interaction.options.get_string("sebep"))
        await respond(interaction, embeds=[ok(f"<@{user.id}> sunucudan atıldı. Vaka #{case['id']}")])

    async def cmd_sustur(self, interaction) -> None:
        user, problem = self._target(interaction)
        if problem:
            return await respond(interaction, embeds=[err(problem)], ephemeral=True)
        seconds = parse_duration(interaction.options.get_string("sure", True))
        if not seconds or seconds > MAX_TIMEOUT:
            return await respond(interaction, embeds=[err("Geçersiz süre (en fazla 28 gün). Örnek: `10dk`, `1sa`, `2g`")],
                                 ephemeral=True)
        case = await self.punish(interaction.guild_id, "timeout", user.id, user.username, interaction.user.id,
                                 interaction.options.get_string("sebep"), seconds)
        await respond(interaction, embeds=[ok(f"<@{user.id}> {fmt_duration(seconds)} susturuldu. Vaka #{case['id']}")])

    async def cmd_susturma_kaldir(self, interaction) -> None:
        user, problem = self._target(interaction)
        if problem:
            return await respond(interaction, embeds=[err(problem)], ephemeral=True)
        case = await self.punish(interaction.guild_id, "untimeout", user.id, user.username, interaction.user.id,
                                 interaction.options.get_string("sebep"))
        await respond(interaction, embeds=[ok(f"<@{user.id}> susturması kaldırıldı. Vaka #{case['id']}")])

    async def cmd_uyari(self, interaction) -> None:
        sub = interaction.options.get_subcommand()
        guild_id = interaction.guild_id
        if sub == "ver":
            user, problem = self._target(interaction)
            if problem:
                return await respond(interaction, embeds=[err(problem)], ephemeral=True)
            case = await self.punish(guild_id, "warn", user.id, user.username, interaction.user.id,
                                     interaction.options.get_string("sebep", True))
            count = len(self.active_warnings(guild_id, user.id))
            return await respond(interaction, embeds=[ok(f"<@{user.id}> uyarıldı ({count}. uyarı). Vaka #{case['id']}")])
        if sub == "sil":
            number = interaction.options.get_integer("vaka", True)
            case = next((c for c in self.store.guild(guild_id)["cases"] if c["id"] == number), None)
            if case is None or case["type"] != "warn":
                return await respond(interaction, embeds=[err("Böyle bir uyarı vakası yok.")], ephemeral=True)
            case["active"] = False
            self.store.save()
            return await respond(interaction, embeds=[ok(f"Vaka #{number} uyarısı silindi.")])
        user = interaction.options.get_user("kullanici", True)
        warnings = self.active_warnings(guild_id, user.id)
        if sub == "temizle":
            for case in warnings:
                case["active"] = False
            self.store.save()
            return await respond(interaction, embeds=[ok(f"<@{user.id}> kullanıcısının {len(warnings)} uyarısı temizlendi.")])
        lines = [f"`#{c['id']}` <t:{int(c['time'])}:d> — {c['reason'][:80]} (<@{c['mod_id']}>)" if c["mod_id"] != "automod"
                 else f"`#{c['id']}` <t:{int(c['time'])}:d> — {c['reason'][:80]} (🤖)" for c in warnings]
        embed = (EmbedBuilder().set_title(f"⚠️ Uyarılar — {user.username} ({len(warnings)})")
                 .set_description("\n".join(lines[-20:]) or "Uyarısı yok.").set_color(Colors.Yellow))
        await respond(interaction, embeds=[embed], ephemeral=True)

    async def cmd_sicil(self, interaction) -> None:
        user = interaction.options.get_user("kullanici", True)
        cases = [c for c in self.store.guild(interaction.guild_id)["cases"] if c["user_id"] == user.id]
        counts: Dict[str, int] = defaultdict(int)
        for case in cases:
            counts[case["type"]] += 1
        summary = " • ".join(f"{CASE_NAMES.get(k, k)}: {v}" for k, v in counts.items()) or "Temiz sicil ✨"
        lines = [f"`#{c['id']}` {CASE_NAMES.get(c['type'], c['type'])} <t:{int(c['time'])}:R> — {c['reason'][:60]}"
                 + ("" if c.get("active", True) else " ~~(silindi)~~") for c in cases[-15:]]
        try:
            created = f"<t:{SnowflakeUtil.timestamp_from(user.id) // 1000}:R>"
        except ValueError:
            created = "?"
        embed = (EmbedBuilder().set_title(f"📋 Sicil — {user.username}").set_color(Colors.Blurple)
                 .add_fields({"name": "Özet", "value": summary}, {"name": "Hesap oluşturma", "value": created, "inline": True},
                             {"name": "Aktif uyarı", "value": str(len(self.active_warnings(interaction.guild_id, user.id))),
                              "inline": True})
                 .set_description("\n".join(lines) or "Kayıt yok."))
        await respond(interaction, embeds=[embed], ephemeral=True)

    async def cmd_vaka(self, interaction) -> None:
        number = interaction.options.get_integer("numara", True)
        case = next((c for c in self.store.guild(interaction.guild_id)["cases"] if c["id"] == number), None)
        if case is None:
            return await respond(interaction, embeds=[err("Böyle bir vaka yok.")], ephemeral=True)
        await respond(interaction, embeds=[self.case_embed(case)], ephemeral=True)

    async def cmd_temizle(self, interaction) -> None:
        amount = interaction.options.get_integer("miktar", True)
        target = interaction.options.get_user("kullanici")
        await interaction.defer_reply(ephemeral=True)
        messages = await self.rest.get_messages(interaction.guild_id, interaction.channel_id, limit=100)
        if target is not None:
            messages = [m for m in messages if str((m.get("author") or {}).get("id") or m.get("user_id")) == target.id]
        ids = [str(m["id"]) for m in messages if m.get("id")][:amount]
        if not ids:
            return await respond(interaction, embeds=[err("Silinecek mesaj bulunamadı.")])
        if len(ids) == 1:
            await self.rest.delete_message(interaction.guild_id, interaction.channel_id, ids[0])
        else:
            await self.rest.bulk_delete_messages(interaction.guild_id, interaction.channel_id, ids)
        who = f" (<@{target.id}>)" if target else ""
        await respond(interaction, embeds=[ok(f"🧹 {len(ids)} mesaj silindi{who}.")])
        await self.mod_log(interaction.guild_id, EmbedBuilder().set_title("🧹 Toplu Mesaj Silme").set_color(Colors.Blurple)
                           .set_description(f"<@{interaction.user.id}> <#{interaction.channel_id}> kanalında "
                                            f"{len(ids)} mesaj sildi{who}.").set_timestamp())

    def _everyone_overwrite(self, guild_id: str, channel_id: str) -> Tuple[int, int]:
        guild = self.client.guilds.get(guild_id)
        channel = guild.channels.get(channel_id) if guild is not None else None
        for ow in (channel or {}).get("permission_overwrites") or []:
            if str(ow.get("id")) == guild_id:
                return int(ow.get("allow") or 0), int(ow.get("deny") or 0)
        return 0, 0

    async def _set_lock(self, interaction, locked: bool) -> str:
        channel_id = _id(interaction.options.get_channel("kanal")) or interaction.channel_id
        guild_id = interaction.guild_id
        allow, deny = self._everyone_overwrite(guild_id, channel_id)
        if locked:
            allow, deny = allow & ~P.SendMessages, deny | P.SendMessages
        else:
            deny &= ~P.SendMessages
        payload = {"allow": str(allow), "deny": str(deny), "type": 0}
        await self.rest.edit_channel_permissions(channel_id, guild_id, payload)
        # Yerel önbelleği güncelle ki kilit/aç sırası tutarlı olsun
        guild = self.client.guilds.get(guild_id)
        if guild is not None:
            channel = guild.channels.setdefault(channel_id, {"id": channel_id})
            overwrites = [o for o in channel.get("permission_overwrites") or [] if str(o.get("id")) != guild_id]
            channel["permission_overwrites"] = overwrites + [{"id": guild_id, **payload}]
        return channel_id

    async def cmd_kilit(self, interaction) -> None:
        channel_id = await self._set_lock(interaction, True)
        reason = interaction.options.get_string("sebep") or "Belirtilmedi"
        await respond(interaction, embeds=[EmbedBuilder().set_description(f"🔒 <#{channel_id}> kilitlendi.\nSebep: {reason}")
                                           .set_color(Colors.Red)])
        await self.mod_log(interaction.guild_id, EmbedBuilder().set_title("🔒 Kanal Kilitlendi").set_color(Colors.Red)
                           .set_description(f"<#{channel_id}> — <@{interaction.user.id}>\nSebep: {reason}").set_timestamp())

    async def cmd_kilit_ac(self, interaction) -> None:
        channel_id = await self._set_lock(interaction, False)
        await respond(interaction, embeds=[ok(f"🔓 <#{channel_id}> kilidi açıldı.")])
        await self.mod_log(interaction.guild_id, EmbedBuilder().set_title("🔓 Kanal Kilidi Açıldı").set_color(Colors.Green)
                           .set_description(f"<#{channel_id}> — <@{interaction.user.id}>").set_timestamp())

    async def cmd_rol(self, interaction) -> None:
        sub = interaction.options.get_subcommand()
        user = interaction.options.get_user("kullanici", True)
        role_id = _id(interaction.options.get_role("rol", True))
        if sub == "ver":
            await self.rest.add_member_role(interaction.guild_id, user.id, role_id, f"Yetkili: {interaction.user.id}")
            text = f"<@{user.id}> kullanıcısına <@&{role_id}> rolü verildi."
        else:
            await self.rest.remove_member_role(interaction.guild_id, user.id, role_id, f"Yetkili: {interaction.user.id}")
            text = f"<@{user.id}> kullanıcısından <@&{role_id}> rolü alındı."
        await respond(interaction, embeds=[ok(text)])
        await self.mod_log(interaction.guild_id, EmbedBuilder().set_title("🎭 Rol Değişikliği").set_color(Colors.Blurple)
                           .set_description(f"{text}\nYetkili: <@{interaction.user.id}>").set_timestamp())

    async def cmd_isim(self, interaction) -> None:
        user = interaction.options.get_user("kullanici", True)
        new = interaction.options.get_string("yeni")
        await self.rest.edit_member(interaction.guild_id, user.id, {"nick": new})
        await respond(interaction, embeds=[ok(f"<@{user.id}> takma adı: **{new}**" if new else f"<@{user.id}> takma adı sıfırlandı.")])

    # ------------------------------------------------------------ ayarlar
    async def cmd_ayarla(self, interaction) -> None:
        cfg = self.store.guild(interaction.guild_id)
        opts = interaction.options
        sub = opts.get_subcommand()
        if sub in ("log", "mesaj-log", "giris-log"):
            key = {"log": "log_channel", "mesaj-log": "message_log_channel", "giris-log": "join_log_channel"}[sub]
            cfg[key] = _id(opts.get_channel("kanal", True))
            text = f"Kayıt kanalı ayarlandı: <#{cfg[key]}>"
        elif sub == "mod-rol":
            cfg["mod_role"] = _id(opts.get_role("rol", True))
            text = f"Moderatör rolü: <@&{cfg['mod_role']}>"
        elif sub == "uyari-cezasi":
            count, action = opts.get_integer("esik", True), opts.get_string("eylem", True)
            cfg["warn_actions"] = [r for r in cfg["warn_actions"] if r["count"] != count]
            if action != "none":
                seconds = (parse_duration(opts.get_string("sure")) or 3600) if action == "timeout" else 0
                cfg["warn_actions"].append({"count": count, "action": action, "seconds": seconds})
                cfg["warn_actions"].sort(key=lambda r: r["count"])
                text = f"{count} uyarıda: **{action}**" + (f" ({fmt_duration(seconds)})" if seconds else "")
            else:
                text = f"{count} uyarı eşiği kaldırıldı."
        else:
            return await respond(interaction, embeds=[self.settings_embed(interaction.guild_id)], ephemeral=True)
        self.store.save()
        await respond(interaction, embeds=[ok(text)], ephemeral=True)

    def settings_embed(self, guild_id: str) -> EmbedBuilder:
        cfg = self.store.guild(guild_id)
        am = cfg["automod"]

        def ch(key: str) -> str:
            return f"<#{cfg[key]}>" if cfg.get(key) else "❌"

        rules = "\n".join(f"{r['count']} uyarı → {r['action']}" + (f" ({fmt_duration(r['seconds'])})" if r.get("seconds") else "")
                          for r in cfg["warn_actions"]) or "Yok"
        return (EmbedBuilder().set_title("🛡️ Moderasyon Ayarları").set_color(Colors.Blurple)
                .add_fields({"name": "Kayıt kanalları", "value": f"Mod-log: {ch('log_channel')}\nMesaj: {ch('message_log_channel')}\n"
                                                                 f"Giriş/çıkış: {ch('join_log_channel')}", "inline": True},
                            {"name": "Mod rolü", "value": f"<@&{cfg['mod_role']}>" if cfg["mod_role"] else "❌", "inline": True},
                            {"name": "Uyarı cezaları", "value": rules, "inline": True},
                            {"name": "AutoMod", "value": "✅ Açık" if am["enabled"] else "❌ Kapalı", "inline": True},
                            {"name": "Toplam vaka", "value": str(len(cfg["cases"])), "inline": True}))

    async def cmd_automod(self, interaction) -> None:
        am = self.store.guild(interaction.guild_id)["automod"]
        opts = interaction.options
        sub = opts.get_subcommand()
        if sub == "durum":
            am["enabled"] = bool(opts.get_boolean("acik", True))
            text = f"AutoMod **{'açıldı' if am['enabled'] else 'kapatıldı'}**."
        elif sub == "kelime-ekle":
            words = [w.strip().lower() for w in opts.get_string("kelime", True).split(",") if w.strip()]
            am["bad_words"] = sorted(set(am["bad_words"]) | set(words))
            text = f"{len(words)} kelime eklendi. Toplam: {len(am['bad_words'])}"
        elif sub == "kelime-sil":
            word = opts.get_string("kelime", True).strip().lower()
            am["bad_words"] = [w for w in am["bad_words"] if w != word]
            text = f"`{word}` listeden çıkarıldı."
        elif sub == "filtre":
            mapping = {"link": ("block_links", opts.get_boolean("link")), "davet": ("block_invites", opts.get_boolean("davet")),
                       "buyuk_harf": ("caps_percent", opts.get_integer("buyuk_harf")),
                       "etiket": ("mention_limit", opts.get_integer("etiket")),
                       "spam_mesaj": ("spam_count", opts.get_integer("spam_mesaj")),
                       "spam_saniye": ("spam_seconds", opts.get_integer("spam_saniye"))}
            changed = []
            for name, (key, value) in mapping.items():
                if value is not None:
                    am[key] = value
                    changed.append(name)
            text = f"Güncellendi: {', '.join(changed)}" if changed else "Değişiklik yapılmadı."
        elif sub == "muaf":
            role, channel = _id(opts.get_role("rol")), _id(opts.get_channel("kanal"))
            parts = []
            for key, value, fmt in (("exempt_roles", role, "<@&{}>"), ("exempt_channels", channel, "<#{}>")):
                if value:
                    if value in am[key]:
                        am[key].remove(value)
                        parts.append(fmt.format(value) + " muafiyeti kaldırıldı")
                    else:
                        am[key].append(value)
                        parts.append(fmt.format(value) + " muaf tutuldu")
            text = ", ".join(parts) or "Rol veya kanal seçmelisin."
        else:
            words = ", ".join(f"||{w}||" for w in am["bad_words"][:30]) or "Yok"
            embed = (EmbedBuilder().set_title("🤖 AutoMod").set_color(Colors.Blurple)
                     .add_fields({"name": "Durum", "value": "✅ Açık" if am["enabled"] else "❌ Kapalı", "inline": True},
                                 {"name": "Link / Davet", "value": f"{'✅' if am['block_links'] else '❌'} / {'✅' if am['block_invites'] else '❌'}",
                                  "inline": True},
                                 {"name": "Büyük harf", "value": f"%{am['caps_percent']}" if am["caps_percent"] else "❌", "inline": True},
                                 {"name": "Etiket sınırı", "value": str(am["mention_limit"] or "❌"), "inline": True},
                                 {"name": "Spam", "value": f"{am['spam_count']} mesaj / {am['spam_seconds']} sn" if am["spam_count"] else "❌",
                                  "inline": True},
                                 {"name": "Yasaklı kelimeler", "value": words},
                                 {"name": "Muaf", "value": " ".join([f"<@&{r}>" for r in am["exempt_roles"]] +
                                                                    [f"<#{c}>" for c in am["exempt_channels"]]) or "Yok"}))
            return await respond(interaction, embeds=[embed], ephemeral=True)
        self.store.save()
        await respond(interaction, embeds=[ok(text)], ephemeral=True)

    # ------------------------------------------------------------- AutoMod
    def check_message(self, am: Dict[str, Any], content: str, guild_id: str, user_id: str) -> Optional[str]:
        """Mesaj bir kuralı ihlal ediyorsa ihlal açıklamasını döndürür."""
        lower = content.lower()
        words = set(re.findall(r"\w+", lower))
        for bad in am["bad_words"]:
            if (" " in bad and bad in lower) or bad in words:
                return "Yasaklı kelime kullanımı"
        if am["block_invites"] and INVITE_RE.search(content):
            return "Davet linki paylaşımı"
        if am["block_links"] and LINK_RE.search(content):
            return "Link paylaşımı"
        if am["mention_limit"] and len(MENTION_RE.findall(content)) > am["mention_limit"]:
            return "Toplu etiket (mention spam)"
        letters = [c for c in content if c.isalpha()]
        if am["caps_percent"] and len(letters) >= am["caps_min_length"]:
            if 100 * sum(c.isupper() for c in letters) / len(letters) >= am["caps_percent"]:
                return "Aşırı büyük harf kullanımı"
        return None

    def is_spam(self, am: Dict[str, Any], guild_id: str, user_id: str) -> bool:
        if not am["spam_count"]:
            return False
        now = time.monotonic()
        stamps = self.spam[(guild_id, user_id)]
        stamps.append(now)
        while stamps and now - stamps[0] > am["spam_seconds"]:
            stamps.popleft()
        if len(stamps) >= am["spam_count"]:
            stamps.clear()
            return True
        return False

    async def on_message(self, message) -> None:
        if not message.guild_id or message.author.bot:
            return
        self.messages[message.id] = {"author_id": message.author.id, "author": message.author.username,
                                     "content": message.content, "channel_id": message.channel_id,
                                     "attachments": [a.get("url") for a in message.attachments]}
        while len(self.messages) > MESSAGE_CACHE_SIZE:
            self.messages.popitem(last=False)

        cfg = self.store.guild(message.guild_id)
        am = cfg["automod"]
        if not am["enabled"] or message.channel_id in am["exempt_channels"]:
            return
        member = message.member
        if member is not None and (self.is_mod(member, message.guild_id, "ManageMessages")
                                   or any(r in am["exempt_roles"] for r in member.roles)):
            return

        if self.is_spam(am, message.guild_id, message.author.id):
            try:
                await self.punish(message.guild_id, "timeout", message.author.id, message.author.username, "automod",
                                  "AutoMod: Mesaj spam'i", am["spam_timeout"])
                await message.channel.send(embeds=[err(f"<@{message.author.id}> spam nedeniyle "
                                                       f"{fmt_duration(am['spam_timeout'])} susturuldu.")])
            except HTTPException as exc:
                log.warning("Spam cezası uygulanamadı: %s", exc)
            return

        violation = self.check_message(am, message.content, message.guild_id, message.author.id)
        if violation is None:
            return
        try:
            await message.delete()
        except HTTPException as exc:
            log.warning("Mesaj silinemedi: %s", exc)
        self.messages.pop(message.id, None)  # silinen mesaj kaydına düşmesin
        try:
            notice = await message.channel.send(embeds=[err(f"<@{message.author.id}>, {violation.lower()} yasak!")])
            self.spawn(self._delete_later(notice, 6))
        except HTTPException:
            pass
        await self.punish(message.guild_id, "warn", message.author.id, message.author.username, "automod", f"AutoMod: {violation}")

    @staticmethod
    async def _delete_later(message, delay: float) -> None:
        await asyncio.sleep(delay)
        try:
            await message.delete()
        except HTTPException:
            pass

    # ------------------------------------------------------------- kayıtlar
    async def on_message_delete(self, data: Dict[str, Any]) -> None:
        guild_id = str(data.get("guild_id") or "")
        cached = self.messages.pop(str(data.get("id")), None)
        if not guild_id or cached is None:
            return
        embed = (EmbedBuilder().set_title("🗑️ Mesaj Silindi").set_color(Colors.Red)
                 .add_fields({"name": "Yazar", "value": f"<@{cached['author_id']}>", "inline": True},
                             {"name": "Kanal", "value": f"<#{cached['channel_id']}>", "inline": True},
                             {"name": "İçerik", "value": (cached["content"] or "*(boş)*")[:1024]})
                 .set_timestamp())
        if cached["attachments"]:
            embed.add_fields({"name": "Ekler", "value": "\n".join(cached["attachments"])[:1024]})
        await self.mod_log(guild_id, embed, "message_log_channel")

    async def on_message_update(self, data: Dict[str, Any]) -> None:
        guild_id = str(data.get("guild_id") or "")
        message_id = str(data.get("id"))
        cached = self.messages.get(message_id)
        new = data.get("content")
        if not guild_id or cached is None or new is None or new == cached["content"]:
            return
        embed = (EmbedBuilder().set_title("✏️ Mesaj Düzenlendi").set_color(Colors.Gold)
                 .add_fields({"name": "Yazar", "value": f"<@{cached['author_id']}>", "inline": True},
                             {"name": "Kanal", "value": f"<#{cached['channel_id']}>", "inline": True},
                             {"name": "Önce", "value": (cached["content"] or "*(boş)*")[:1024]},
                             {"name": "Sonra", "value": new[:1024] or "*(boş)*"})
                 .set_timestamp())
        cached["content"] = new
        await self.mod_log(guild_id, embed, "message_log_channel")
        # Düzenlenen mesaj da AutoMod'dan geçer
        am = self.store.guild(guild_id)["automod"]
        if am["enabled"] and cached["channel_id"] not in am["exempt_channels"]:
            guild = self.client.guilds.get(guild_id)
            member = guild.members.get(cached["author_id"]) if guild else None
            if member is not None and (self.is_mod(member, guild_id, "ManageMessages")
                                       or any(r in am["exempt_roles"] for r in member.roles)):
                return
            violation = self.check_message(am, new, guild_id, cached["author_id"])
            if violation:
                try:
                    await self.rest.delete_message(guild_id, cached["channel_id"], message_id)
                except HTTPException:
                    pass
                await self.punish(guild_id, "warn", cached["author_id"], cached["author"], "automod", f"AutoMod: {violation}")

    @staticmethod
    def _member_info(member: Any) -> Tuple[str, str, str]:
        if isinstance(member, dict):
            user = member.get("user") or {}
            return str(member.get("guild_id")), str(user.get("id") or member.get("user_id")), user.get("username") or "?"
        return str(member.guild.id), member.id, member.user.username

    async def on_member_join(self, member: Any) -> None:
        guild_id, user_id, name = self._member_info(member)
        try:
            created = SnowflakeUtil.timestamp_from(user_id) / 1000
            age_days = (time.time() - created) / 86400
            age = f"<t:{int(created)}:R>" + (" ⚠️ **Yeni hesap!**" if age_days < 7 else "")
        except ValueError:
            age = "?"
        embed = (EmbedBuilder().set_title("📥 Üye Katıldı").set_color(Colors.Green)
                 .add_fields({"name": "Kullanıcı", "value": f"<@{user_id}> ({name})", "inline": True},
                             {"name": "ID", "value": user_id, "inline": True},
                             {"name": "Hesap oluşturma", "value": age, "inline": True})
                 .set_timestamp())
        await self.mod_log(guild_id, embed, "join_log_channel")

    async def on_member_leave(self, member: Any) -> None:
        guild_id, user_id, name = self._member_info(member)
        embed = (EmbedBuilder().set_title("📤 Üye Ayrıldı").set_color(Colors.Red)
                 .add_fields({"name": "Kullanıcı", "value": f"<@{user_id}> ({name})", "inline": True},
                             {"name": "ID", "value": user_id, "inline": True})
                 .set_timestamp())
        await self.mod_log(guild_id, embed, "join_log_channel")

    def run(self, token: str) -> None:
        self.client.run(token)


if __name__ == "__main__":
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise SystemExit("BOT_TOKEN ortam değişkeni ayarlanmamış. Windows: set BOT_TOKEN=tokenin")
    path = os.environ.get("MOD_DATA", os.path.join(os.path.dirname(os.path.abspath(__file__)), "moderasyon_data.json"))
    ModerationBot(path).run(token)
