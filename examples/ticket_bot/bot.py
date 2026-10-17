"""Gelişmiş Ticket + Hoş Geldin/Ayrılma botu (Jubbio.py).

Özellikler
----------
Ticket sistemi
  • /ticket-panel ile butonlu + kategori menülü panel
  • Kategori seçimi → konu/açıklama formu (modal) → özel ticket kanalı
  • Kanal izinleri: sadece ticket sahibi, yetkili rolü ve bot görür
  • Kullanıcı başına açık ticket limiti
  • Sahiplenme (claim), kullanıcı ekleme/çıkarma, ticket bilgisi
  • Onaylı kapatma: mesaj dökümü (transcript) .txt olarak log kanalına
    ve ticket sahibine DM ile gönderilir, kanal silinir
  • İstatistikler (açılan / kapanan ticket sayısı)

Hoş geldin / ayrılma (join) sistemi
  • Yeni üyeye embed'li hoş geldin mesajı (özelleştirilebilir)
  • Ayrılan üye için ayrılma mesajı
  • Otomatik rol (oto-rol)

Tüm ayarlar sunucu bazında ``ticket_data.json`` dosyasında saklanır.

Çalıştırma (Windows)::

    set BOT_TOKEN=tokenin
    python examples\\ticket_bot\\bot.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from jubbio import (
    ActionRowBuilder,
    ButtonBuilder,
    ButtonStyle,
    ChannelType,
    Client,
    Colors,
    EmbedBuilder,
    File,
    GatewayIntentBits,
    HTTPException,
    ModalBuilder,
    PermissionFlagsBits,
    SlashCommandBuilder,
    StringSelectMenuBuilder,
    TextInputBuilder,
    TextInputStyle,
)

log = logging.getLogger("ticket_bot")

# ============================================================== ayarlar
#: Ticket kategorileri: (kod, etiket, açıklama, emoji)
CATEGORIES = [
    ("destek", "Genel Destek", "Genel sorular ve yardım", "🛠️"),
    ("satin-alim", "Satın Alım", "Ödeme ve satın alma işlemleri", "💳"),
    ("sikayet", "Şikayet", "Kullanıcı veya durum şikayeti", "⚠️"),
    ("basvuru", "Başvuru", "Yetkili / ekip başvuruları", "📝"),
    ("diger", "Diğer", "Diğer konular", "📌"),
]
CATEGORY_MAP = {code: (label, desc, emoji) for code, label, desc, emoji in CATEGORIES}

DEFAULT_WELCOME = "👋 Hoş geldin {kullanici}! **{sunucu}** sunucusuna katıldın. Seninle birlikte **{uye_sayisi}** kişiyiz!"
DEFAULT_LEAVE = "😢 **{isim}** sunucudan ayrıldı. Artık **{uye_sayisi}** kişiyiz."

P = PermissionFlagsBits
TICKET_PERMS = P.ViewChannel | P.SendMessages | P.ReadMessageHistory | P.AttachFiles | P.EmbedLinks
STAFF_PERMS = TICKET_PERMS | P.ManageMessages

DELETE_DELAY = 5  # kapatma onayından sonra kanal silinmeden önce bekleme (sn)


# ============================================================== depolama
class Storage:
    """Sunucu ayarlarını ve açık ticket'ları JSON dosyasında tutar."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.data: Dict[str, Any] = {"guilds": {}}
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                self.data = json.load(fh)
        self._lock = asyncio.Lock()

    def guild(self, guild_id: str) -> Dict[str, Any]:
        guilds = self.data.setdefault("guilds", {})
        if guild_id not in guilds:
            guilds[guild_id] = {
                "staff_role": None, "category_id": None, "log_channel": None, "max_tickets": 1,
                "welcome_channel": None, "welcome_message": DEFAULT_WELCOME,
                "leave_channel": None, "leave_message": DEFAULT_LEAVE, "auto_role": None,
                "counter": 0, "stats": {"opened": 0, "closed": 0}, "tickets": {},
            }
        return guilds[guild_id]

    def ticket(self, guild_id: str, channel_id: str) -> Optional[Dict[str, Any]]:
        return self.guild(guild_id)["tickets"].get(str(channel_id))

    async def save(self) -> None:
        async with self._lock:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)


# ============================================================== yardımcılar
def _id(value: Any) -> Optional[str]:
    """Seçenek değerinden (ham ID, mention veya çözümlenmiş dict) ID çıkarır."""
    if value is None:
        return None
    if isinstance(value, dict):
        value = value.get("id")
    text = str(value).strip("<@&#!>")
    return text or None


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M UTC")


async def respond(interaction, content: Optional[str] = None, **kwargs: Any) -> None:
    """Etkileşimin durumuna göre reply / edit_reply / follow_up seçer."""
    if interaction.deferred:
        kwargs.pop("ephemeral", None)
        await interaction.edit_reply(content, **kwargs)
    elif interaction.replied:
        await interaction.follow_up(content, **kwargs)
    else:
        await interaction.reply(content, **kwargs)


def error_embed(text: str) -> EmbedBuilder:
    return EmbedBuilder().set_description(f"❌ {text}").set_color(Colors.Red)


def ok_embed(text: str) -> EmbedBuilder:
    return EmbedBuilder().set_description(f"✅ {text}").set_color(Colors.Green)


def fill_template(template: str, member_id: str, name: str, guild_name: str, count: int) -> str:
    return (template.replace("{kullanici}", f"<@{member_id}>").replace("{isim}", name)
            .replace("{sunucu}", guild_name or "").replace("{uye_sayisi}", str(count)))


# ============================================================== komutlar
def build_commands() -> List[SlashCommandBuilder]:
    ayarla = (
        SlashCommandBuilder().set_name("ayarla").set_description("Bot ayarlarını yapılandır (Sunucuyu Yönet izni)")
        .add_subcommand(lambda s: s.set_name("ticket").set_description("Ticket sistemini ayarla")
                        .add_role_option(lambda o: o.set_name("yetkili_rol").set_description("Ticket'ları görecek yetkili rolü").set_required(True))
                        .add_channel_option(lambda o: o.set_name("kategori").set_description("Ticket kanallarının açılacağı kategori")
                                            .add_channel_types(ChannelType.GuildCategory))
                        .add_channel_option(lambda o: o.set_name("log_kanal").set_description("Kayıt / döküm kanalı")
                                            .add_channel_types(ChannelType.GuildText))
                        .add_integer_option(lambda o: o.set_name("limit").set_description("Kişi başı açık ticket limiti")
                                            .set_min_value(1).set_max_value(10)))
        .add_subcommand(lambda s: s.set_name("hosgeldin").set_description("Hoş geldin mesajını ayarla")
                        .add_channel_option(lambda o: o.set_name("kanal").set_description("Mesaj kanalı").set_required(True)
                                            .add_channel_types(ChannelType.GuildText))
                        .add_string_option(lambda o: o.set_name("mesaj").set_description(
                            "Değişkenler: {kullanici} {isim} {sunucu} {uye_sayisi}").set_max_length(1000)))
        .add_subcommand(lambda s: s.set_name("ayrilma").set_description("Ayrılma mesajını ayarla")
                        .add_channel_option(lambda o: o.set_name("kanal").set_description("Mesaj kanalı").set_required(True)
                                            .add_channel_types(ChannelType.GuildText))
                        .add_string_option(lambda o: o.set_name("mesaj").set_description(
                            "Değişkenler: {kullanici} {isim} {sunucu} {uye_sayisi}").set_max_length(1000)))
        .add_subcommand(lambda s: s.set_name("otorol").set_description("Yeni üyelere verilecek rol")
                        .add_role_option(lambda o: o.set_name("rol").set_description("Rol (boş bırakılırsa kapatılır)")))
        .add_subcommand(lambda s: s.set_name("kapat").set_description("Bir sistemi kapat")
                        .add_string_option(lambda o: o.set_name("sistem").set_description("Kapatılacak sistem").set_required(True)
                                           .add_choices({"name": "Hoş geldin", "value": "welcome"},
                                                        {"name": "Ayrılma", "value": "leave"},
                                                        {"name": "Oto-rol", "value": "auto_role"})))
        .add_subcommand(lambda s: s.set_name("goster").set_description("Mevcut ayarları ve istatistikleri göster"))
    )
    panel = (SlashCommandBuilder().set_name("ticket-panel").set_description("Ticket açma panelini gönder")
             .add_channel_option(lambda o: o.set_name("kanal").set_description("Panelin gönderileceği kanal")
                                 .add_channel_types(ChannelType.GuildText)))
    ticket = (
        SlashCommandBuilder().set_name("ticket").set_description("Ticket işlemleri")
        .add_subcommand(lambda s: s.set_name("kapat").set_description("Bu ticket'ı kapat")
                        .add_string_option(lambda o: o.set_name("sebep").set_description("Kapatma sebebi")))
        .add_subcommand(lambda s: s.set_name("ekle").set_description("Ticket'a kullanıcı ekle")
                        .add_user_option(lambda o: o.set_name("kullanici").set_description("Eklenecek kullanıcı").set_required(True)))
        .add_subcommand(lambda s: s.set_name("cikar").set_description("Ticket'tan kullanıcı çıkar")
                        .add_user_option(lambda o: o.set_name("kullanici").set_description("Çıkarılacak kullanıcı").set_required(True)))
        .add_subcommand(lambda s: s.set_name("sahiplen").set_description("Ticket'ı sahiplen"))
        .add_subcommand(lambda s: s.set_name("bilgi").set_description("Ticket bilgilerini göster"))
    )
    return [ayarla, panel, ticket]


# ============================================================== bot
class TicketBot:
    def __init__(self, data_path: str = "ticket_data.json", **client_options: Any) -> None:
        self.store = Storage(data_path)
        self.client = Client(intents=[
            GatewayIntentBits.Guilds,
            GatewayIntentBits.GuildMembers,
            GatewayIntentBits.GuildMessages,
            GatewayIntentBits.MessageContent,
        ], **client_options)
        self.client.on("ready", self.on_ready)
        self.client.on("interactionCreate", self.on_interaction)
        self.client.on("guildMemberAdd", self.on_member_join)
        self.client.on("guildMemberRemove", self.on_member_leave)
        self._closing: set = set()

    @property
    def rest(self):
        return self.client.rest

    # ------------------------------------------------------------ olaylar
    async def on_ready(self, _client: Client) -> None:
        try:
            await self.client.application.commands.set(build_commands())
            log.info("Slash komutları kaydedildi")
        except HTTPException as exc:
            log.error("Komutlar kaydedilemedi: %s", exc)
        print(f"🎫 {self.client.user.username} hazır! {len(self.client.guilds)} sunucuda çalışıyor.")

    async def on_interaction(self, interaction) -> None:
        try:
            if interaction.is_command():
                handler = {
                    "ayarla": self.cmd_settings,
                    "ticket-panel": self.cmd_panel,
                    "ticket": self.cmd_ticket,
                }.get(interaction.command_name)
                if handler:
                    await handler(interaction)
            elif interaction.is_button():
                await self.on_button(interaction)
            elif interaction.is_select_menu() and interaction.custom_id == "ticket:category":
                await self.show_ticket_modal(interaction, interaction.values[0] if interaction.values else "destek")
            elif interaction.is_modal_submit() and interaction.custom_id.startswith("ticket:modal:"):
                await self.create_ticket(interaction, interaction.custom_id.split(":", 2)[2])
        except Exception as exc:  # noqa: BLE001 - kullanıcıya hata göster, botu düşürme
            log.exception("Etkileşim işlenirken hata")
            try:
                await respond(interaction, embeds=[error_embed(f"Bir hata oluştu: {exc}")], ephemeral=True)
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------- yetki kontrol
    def is_admin(self, interaction) -> bool:
        member = interaction.member
        if member is None:
            return False
        guild = interaction.guild
        if guild is not None and guild.owner_id == member.id:
            return True
        return member.permissions.has("ManageGuild")

    def is_staff(self, interaction) -> bool:
        if self.is_admin(interaction):
            return True
        member = interaction.member
        staff_role = self.store.guild(interaction.guild_id)["staff_role"]
        if member is None:
            return False
        return (staff_role is not None and staff_role in member.roles) or member.permissions.has("ManageChannels")

    # ---------------------------------------------------------- /ayarla
    async def cmd_settings(self, interaction) -> None:
        if not interaction.guild_id:
            return await respond(interaction, embeds=[error_embed("Bu komut sadece sunucularda kullanılabilir.")])
        if not self.is_admin(interaction):
            return await respond(interaction, embeds=[error_embed("Bu komut için **Sunucuyu Yönet** izni gerekli.")],
                                 ephemeral=True)
        opts = interaction.options
        cfg = self.store.guild(interaction.guild_id)
        sub = opts.get_subcommand()

        if sub == "ticket":
            cfg["staff_role"] = _id(opts.get_role("yetkili_rol", True))
            cfg["category_id"] = _id(opts.get_channel("kategori"))
            cfg["log_channel"] = _id(opts.get_channel("log_kanal"))
            if opts.get_integer("limit"):
                cfg["max_tickets"] = opts.get_integer("limit")
            category = f"<#{cfg['category_id']}>" if cfg["category_id"] else "Yok"
            log_channel = f"<#{cfg['log_channel']}>" if cfg["log_channel"] else "Yok"
            text = (f"Ticket sistemi ayarlandı.\n• Yetkili rol: <@&{cfg['staff_role']}>\n"
                    f"• Kategori: {category}\n• Log kanalı: {log_channel}\n"
                    f"• Kişi başı limit: {cfg['max_tickets']}\n\nŞimdi `/ticket-panel` ile paneli gönderebilirsin.")
        elif sub in ("hosgeldin", "ayrilma"):
            key = "welcome" if sub == "hosgeldin" else "leave"
            cfg[f"{key}_channel"] = _id(opts.get_channel("kanal", True))
            message = opts.get_string("mesaj")
            if message:
                cfg[f"{key}_message"] = message
            name = "Hoş geldin" if key == "welcome" else "Ayrılma"
            text = f"{name} mesajı <#{cfg[f'{key}_channel']}> kanalına ayarlandı.\nMesaj: {cfg[f'{key}_message']}"
        elif sub == "otorol":
            cfg["auto_role"] = _id(opts.get_role("rol"))
            text = f"Oto-rol: <@&{cfg['auto_role']}>" if cfg["auto_role"] else "Oto-rol kapatıldı."
        elif sub == "kapat":
            system = opts.get_string("sistem", True)
            cfg["auto_role" if system == "auto_role" else f"{system}_channel"] = None
            text = "Sistem kapatıldı."
        else:  # goster
            return await respond(interaction, embeds=[self.settings_embed(interaction.guild_id)], ephemeral=True)

        await self.store.save()
        await respond(interaction, embeds=[ok_embed(text)], ephemeral=True)

    def settings_embed(self, guild_id: str) -> EmbedBuilder:
        cfg = self.store.guild(guild_id)

        def ch(key: str) -> str:
            return f"<#{cfg[key]}>" if cfg.get(key) else "❌ Kapalı"

        def role(key: str) -> str:
            return f"<@&{cfg[key]}>" if cfg.get(key) else "❌ Yok"

        return (EmbedBuilder().set_title("⚙️ Sunucu Ayarları").set_color(Colors.Blurple)
                .add_fields(
                    {"name": "🎫 Ticket", "value": f"Yetkili: {role('staff_role')}\nKategori: {ch('category_id')}\n"
                                                    f"Log: {ch('log_channel')}\nLimit: {cfg['max_tickets']}", "inline": True},
                    {"name": "👋 Giriş / Çıkış", "value": f"Hoş geldin: {ch('welcome_channel')}\nAyrılma: {ch('leave_channel')}\n"
                                                         f"Oto-rol: {role('auto_role')}", "inline": True},
                    {"name": "📊 İstatistik", "value": f"Açılan: {cfg['stats']['opened']}\nKapanan: {cfg['stats']['closed']}\n"
                                                      f"Şu an açık: {len(cfg['tickets'])}", "inline": True},
                ).set_timestamp())

    # ---------------------------------------------------------- panel
    async def cmd_panel(self, interaction) -> None:
        if not self.is_admin(interaction):
            return await respond(interaction, embeds=[error_embed("Bu komut için **Sunucuyu Yönet** izni gerekli.")],
                                 ephemeral=True)
        cfg = self.store.guild(interaction.guild_id)
        if not cfg["staff_role"]:
            return await respond(interaction, embeds=[error_embed("Önce `/ayarla ticket` ile sistemi ayarla.")],
                                 ephemeral=True)
        channel_id = _id(interaction.options.get_channel("kanal")) or interaction.channel_id
        embed = (EmbedBuilder()
                 .set_title("🎫 Destek Sistemi")
                 .set_description("Yardıma mı ihtiyacın var? Aşağıdaki menüden bir **kategori** seç "
                                  "veya **Ticket Aç** butonuna tıkla.\n\nYetkililerimiz en kısa sürede sana dönüş yapacak.")
                 .add_fields(*[{"name": f"{emoji} {label}", "value": desc, "inline": True}
                               for _, label, desc, emoji in CATEGORIES])
                 .set_color(Colors.Blurple)
                 .set_footer(text="Gereksiz ticket açmak yasaktır."))
        menu = StringSelectMenuBuilder().set_custom_id("ticket:category").set_placeholder("📂 Kategori seç...").add_options(
            *[{"label": label, "value": code, "description": desc, "emoji": {"name": emoji}}
              for code, label, desc, emoji in CATEGORIES])
        button = ButtonBuilder().set_custom_id("ticket:open").set_label("Ticket Aç").set_emoji("🎫").set_style(ButtonStyle.Primary)
        await self.rest.create_message(interaction.guild_id, channel_id, {
            "embeds": [embed],
            "components": [ActionRowBuilder().add_components(menu), ActionRowBuilder().add_components(button)],
        })
        await respond(interaction, embeds=[ok_embed(f"Ticket paneli <#{channel_id}> kanalına gönderildi.")], ephemeral=True)

    # ------------------------------------------------------- ticket açma
    def open_ticket_count(self, guild_id: str, user_id: str) -> int:
        return sum(1 for t in self.store.guild(guild_id)["tickets"].values() if t["owner"] == user_id)

    async def show_ticket_modal(self, interaction, category: str) -> None:
        cfg = self.store.guild(interaction.guild_id)
        if not cfg["staff_role"]:
            return await respond(interaction, embeds=[error_embed("Ticket sistemi henüz ayarlanmamış.")], ephemeral=True)
        if self.open_ticket_count(interaction.guild_id, interaction.user.id) >= cfg["max_tickets"]:
            existing = [cid for cid, t in cfg["tickets"].items() if t["owner"] == interaction.user.id]
            return await respond(interaction, embeds=[error_embed(
                f"Zaten açık ticket'ın var: {', '.join(f'<#{c}>' for c in existing)}")], ephemeral=True)
        label = CATEGORY_MAP.get(category, ("Destek",))[0]
        modal = (ModalBuilder().set_custom_id(f"ticket:modal:{category}").set_title(f"🎫 {label} Talebi")
                 .add_components(
                     ActionRowBuilder().add_components(
                         TextInputBuilder().set_custom_id("konu").set_label("Konu").set_style(TextInputStyle.Short)
                         .set_placeholder("Kısaca konunu yaz").set_min_length(3).set_max_length(100).set_required()),
                     ActionRowBuilder().add_components(
                         TextInputBuilder().set_custom_id("aciklama").set_label("Açıklama").set_style(TextInputStyle.Paragraph)
                         .set_placeholder("Sorununu detaylı anlat").set_max_length(1000).set_required(False)),
                 ))
        await interaction.show_modal(modal)

    async def create_ticket(self, interaction, category: str) -> None:
        guild_id, user = interaction.guild_id, interaction.user
        cfg = self.store.guild(guild_id)
        if self.open_ticket_count(guild_id, user.id) >= cfg["max_tickets"]:
            return await respond(interaction, embeds=[error_embed("Ticket limitine ulaştın.")], ephemeral=True)
        await interaction.defer_reply(ephemeral=True)

        subject = interaction.fields.get_text_input_value("konu") or "Belirtilmedi"
        description = interaction.fields.get_text_input_value("aciklama") or "Açıklama yok."
        label, _desc, emoji = CATEGORY_MAP.get(category, ("Destek", "", "🎫"))
        cfg["counter"] += 1
        number = cfg["counter"]

        overwrites = [
            {"id": guild_id, "type": 0, "allow": "0", "deny": str(P.ViewChannel)},  # @everyone
            {"id": user.id, "type": 1, "allow": str(TICKET_PERMS), "deny": "0"},
            {"id": cfg["staff_role"], "type": 0, "allow": str(STAFF_PERMS), "deny": "0"},
        ]
        if self.client.user:
            overwrites.append({"id": self.client.user.id, "type": 1, "allow": str(STAFF_PERMS | P.ManageChannels), "deny": "0"})
        request: Dict[str, Any] = {"name": f"{category}-{number:04d}", "type": 0, "permission_overwrites": overwrites}
        if cfg["category_id"]:
            request["parent_id"] = cfg["category_id"]

        channel = await self.rest.create_channel(guild_id, request)
        channel_id = str((channel or {}).get("id") or (channel or {}).get("channel_id") or "")
        if not channel_id:
            cfg["counter"] -= 1
            return await respond(interaction, embeds=[error_embed("Kanal oluşturulamadı (API kanal ID döndürmedi).")])

        cfg["tickets"][channel_id] = {
            "number": number, "owner": user.id, "owner_name": user.username, "category": category,
            "subject": subject, "created_at": time.time(), "claimed_by": None, "added": [],
        }
        cfg["stats"]["opened"] += 1
        await self.store.save()

        embed = (EmbedBuilder()
                 .set_title(f"{emoji} Ticket #{number:04d} — {label}")
                 .set_description(f"Merhaba <@{user.id}>, ticket'ın oluşturuldu!\nYetkililer kısa süre içinde ilgilenecek.")
                 .add_fields({"name": "📌 Konu", "value": subject},
                             {"name": "📝 Açıklama", "value": description[:1024]},
                             {"name": "👤 Açan", "value": f"<@{user.id}>", "inline": True},
                             {"name": "📂 Kategori", "value": label, "inline": True})
                 .set_color(Colors.Green).set_timestamp())
        buttons = ActionRowBuilder().add_components(
            ButtonBuilder().set_custom_id("ticket:claim").set_label("Sahiplen").set_emoji("🙋").set_style(ButtonStyle.Success),
            ButtonBuilder().set_custom_id("ticket:close").set_label("Kapat").set_emoji("🔒").set_style(ButtonStyle.Danger),
        )
        await self.rest.create_message(guild_id, channel_id, {
            "content": f"<@{user.id}> <@&{cfg['staff_role']}>", "embeds": [embed], "components": [buttons],
        })
        await respond(interaction, embeds=[ok_embed(f"Ticket'ın oluşturuldu: <#{channel_id}>")])
        await self.log(guild_id, EmbedBuilder().set_title("🎫 Ticket Açıldı").set_color(Colors.Green)
                       .add_fields({"name": "Ticket", "value": f"<#{channel_id}> (#{number:04d})", "inline": True},
                                   {"name": "Açan", "value": f"<@{user.id}>", "inline": True},
                                   {"name": "Kategori", "value": label, "inline": True},
                                   {"name": "Konu", "value": subject})
                       .set_timestamp())

    # ----------------------------------------------------------- butonlar
    async def on_button(self, interaction) -> None:
        cid = interaction.custom_id
        if cid == "ticket:open":
            await self.show_ticket_modal(interaction, "destek")
        elif cid == "ticket:claim":
            await self.claim_ticket(interaction)
        elif cid == "ticket:close":
            if not self._ticket_or_none(interaction):
                return await respond(interaction, embeds=[error_embed("Bu kanal bir ticket değil.")], ephemeral=True)
            confirm = ActionRowBuilder().add_components(
                ButtonBuilder().set_custom_id("ticket:close_confirm").set_label("Evet, kapat").set_style(ButtonStyle.Danger),
                ButtonBuilder().set_custom_id("ticket:close_cancel").set_label("İptal").set_style(ButtonStyle.Secondary),
            )
            await interaction.reply(embeds=[EmbedBuilder().set_description("🔒 Bu ticket'ı kapatmak istediğine emin misin?")
                                            .set_color(Colors.Orange)], components=[confirm])
        elif cid == "ticket:close_confirm":
            await self.close_ticket(interaction, reason=None)
        elif cid == "ticket:close_cancel":
            await interaction.update(embeds=[EmbedBuilder().set_description("Kapatma iptal edildi.").set_color(Colors.Grey)],
                                     components=[])

    def _ticket_or_none(self, interaction) -> Optional[Dict[str, Any]]:
        if not interaction.guild_id or not interaction.channel_id:
            return None
        return self.store.ticket(interaction.guild_id, interaction.channel_id)

    # ------------------------------------------------------- /ticket ...
    async def cmd_ticket(self, interaction) -> None:
        ticket = self._ticket_or_none(interaction)
        if ticket is None:
            return await respond(interaction, embeds=[error_embed("Bu komut sadece ticket kanallarında kullanılabilir.")],
                                 ephemeral=True)
        sub = interaction.options.get_subcommand()
        if sub == "kapat":
            await self.close_ticket(interaction, interaction.options.get_string("sebep"))
        elif sub == "sahiplen":
            await self.claim_ticket(interaction)
        elif sub in ("ekle", "cikar"):
            await self.toggle_user(interaction, ticket, add=(sub == "ekle"))
        else:
            await respond(interaction, embeds=[self.ticket_embed(ticket, interaction.channel_id)], ephemeral=True)

    def ticket_embed(self, ticket: Dict[str, Any], channel_id: str) -> EmbedBuilder:
        label = CATEGORY_MAP.get(ticket["category"], ("Destek",))[0]
        claimed = f"<@{ticket['claimed_by']}>" if ticket["claimed_by"] else "Henüz yok"
        added = ", ".join(f"<@{u}>" for u in ticket["added"]) or "Yok"
        return (EmbedBuilder().set_title(f"ℹ️ Ticket #{ticket['number']:04d}").set_color(Colors.Blue)
                .add_fields({"name": "Kanal", "value": f"<#{channel_id}>", "inline": True},
                            {"name": "Açan", "value": f"<@{ticket['owner']}>", "inline": True},
                            {"name": "Kategori", "value": label, "inline": True},
                            {"name": "Sahiplenen", "value": claimed, "inline": True},
                            {"name": "Eklenenler", "value": added, "inline": True},
                            {"name": "Açılış", "value": f"<t:{int(ticket['created_at'])}:R>", "inline": True},
                            {"name": "Konu", "value": ticket["subject"]}))

    async def claim_ticket(self, interaction) -> None:
        ticket = self._ticket_or_none(interaction)
        if ticket is None:
            return await respond(interaction, embeds=[error_embed("Bu kanal bir ticket değil.")], ephemeral=True)
        if not self.is_staff(interaction):
            return await respond(interaction, embeds=[error_embed("Sadece yetkililer ticket sahiplenebilir.")], ephemeral=True)
        if ticket["claimed_by"]:
            return await respond(interaction, embeds=[error_embed(f"Bu ticket zaten <@{ticket['claimed_by']}> tarafından sahiplenildi.")],
                                 ephemeral=True)
        ticket["claimed_by"] = interaction.user.id
        await self.store.save()
        await respond(interaction, embeds=[EmbedBuilder().set_description(
            f"🙋 Bu ticket ile artık <@{interaction.user.id}> ilgileniyor.").set_color(Colors.Gold)])
        await self.log(interaction.guild_id, EmbedBuilder().set_title("🙋 Ticket Sahiplenildi").set_color(Colors.Gold)
                       .set_description(f"<#{interaction.channel_id}> — <@{interaction.user.id}>").set_timestamp())

    async def toggle_user(self, interaction, ticket: Dict[str, Any], add: bool) -> None:
        if not self.is_staff(interaction) and interaction.user.id != ticket["owner"]:
            return await respond(interaction, embeds=[error_embed("Bu işlem için yetkin yok.")], ephemeral=True)
        target = interaction.options.get_user("kullanici", True)
        if target.id == ticket["owner"] and not add:
            return await respond(interaction, embeds=[error_embed("Ticket sahibini çıkaramazsın.")], ephemeral=True)
        if add:
            await self.rest.edit_channel_permissions(interaction.channel_id, target.id,
                                                     {"allow": str(TICKET_PERMS), "deny": "0", "type": 1})
            if target.id not in ticket["added"]:
                ticket["added"].append(target.id)
            text = f"➕ <@{target.id}> ticket'a eklendi."
        else:
            await self.rest.delete_channel_permission(interaction.channel_id, target.id)
            if target.id in ticket["added"]:
                ticket["added"].remove(target.id)
            text = f"➖ <@{target.id}> ticket'tan çıkarıldı."
        await self.store.save()
        await respond(interaction, embeds=[ok_embed(text)])

    # ----------------------------------------------------------- kapatma
    async def close_ticket(self, interaction, reason: Optional[str]) -> None:
        guild_id, channel_id = interaction.guild_id, interaction.channel_id
        ticket = self._ticket_or_none(interaction)
        if ticket is None:
            return await respond(interaction, embeds=[error_embed("Bu kanal bir ticket değil.")], ephemeral=True)
        if not self.is_staff(interaction) and interaction.user.id != ticket["owner"]:
            return await respond(interaction, embeds=[error_embed("Bu ticket'ı kapatma yetkin yok.")], ephemeral=True)
        if channel_id in self._closing:
            return await respond(interaction, embeds=[error_embed("Bu ticket zaten kapatılıyor.")], ephemeral=True)
        self._closing.add(channel_id)

        closing = (EmbedBuilder().set_description(f"🔒 Ticket <@{interaction.user.id}> tarafından kapatıldı. "
                                                  f"Kanal {DELETE_DELAY} saniye içinde silinecek.")
                   .set_color(Colors.Red))
        if interaction.is_button():
            await interaction.update(embeds=[closing], components=[])
        else:
            await respond(interaction, embeds=[closing])

        try:
            transcript = await self.build_transcript(guild_id, channel_id, ticket)
            file = File(f"ticket-{ticket['number']:04d}.txt", transcript.encode("utf-8"), "text/plain")
            label = CATEGORY_MAP.get(ticket["category"], ("Destek",))[0]
            duration = int(time.time() - ticket["created_at"])
            summary = (EmbedBuilder().set_title(f"🔒 Ticket #{ticket['number']:04d} Kapatıldı").set_color(Colors.Red)
                       .add_fields({"name": "Açan", "value": f"<@{ticket['owner']}>", "inline": True},
                                   {"name": "Kapatan", "value": f"<@{interaction.user.id}>", "inline": True},
                                   {"name": "Sahiplenen", "value": f"<@{ticket['claimed_by']}>" if ticket["claimed_by"] else "Yok",
                                    "inline": True},
                                   {"name": "Kategori", "value": label, "inline": True},
                                   {"name": "Süre", "value": f"{duration // 3600} sa {duration % 3600 // 60} dk", "inline": True},
                                   {"name": "Sebep", "value": reason or "Belirtilmedi"},
                                   {"name": "Konu", "value": ticket["subject"]})
                       .set_timestamp())
            await self.log(guild_id, summary, file)
            try:
                await self.rest.create_dm_message_with_file(ticket["owner"], {"embeds": [summary]}, [file])
            except HTTPException as exc:
                log.warning("Ticket sahibine DM gönderilemedi: %s", exc)
        except Exception:  # noqa: BLE001 - döküm başarısız olsa da ticket kapanmalı
            log.exception("Ticket dökümü oluşturulamadı")

        cfg = self.store.guild(guild_id)
        cfg["tickets"].pop(channel_id, None)
        cfg["stats"]["closed"] += 1
        await self.store.save()
        await asyncio.sleep(DELETE_DELAY)
        try:
            await self.rest.delete_channel(guild_id, channel_id)
        finally:
            self._closing.discard(channel_id)

    async def build_transcript(self, guild_id: str, channel_id: str, ticket: Dict[str, Any], limit: int = 1000) -> str:
        """Kanaldaki mesajları (en fazla ``limit``) düz metin dökümüne çevirir."""
        messages: List[Dict[str, Any]] = []
        before: Optional[str] = None
        while len(messages) < limit:
            page = await self.rest.get_messages(guild_id, channel_id, limit=100, before=before)
            if not page:
                break
            messages.extend(page)
            if len(page) < 100:
                break
            before = str(min(page, key=lambda m: int(m.get("id") or 0)).get("id"))

        def sort_key(m: Dict[str, Any]) -> Any:
            try:
                return int(m.get("id"))
            except (TypeError, ValueError):
                return str(m.get("timestamp") or m.get("created_at") or "")

        lines = [
            f"Ticket #{ticket['number']:04d} — {CATEGORY_MAP.get(ticket['category'], ('Destek',))[0]}",
            f"Açan: {ticket['owner_name']} ({ticket['owner']})",
            f"Konu: {ticket['subject']}",
            f"Döküm tarihi: {_now()}",
            "=" * 60,
        ]
        for m in sorted(messages, key=sort_key):
            author = (m.get("author") or {}).get("username") or f"User_{m.get('user_id', '?')}"
            stamp = str(m.get("timestamp") or m.get("created_at") or "")[:19].replace("T", " ")
            content = m.get("content") or ""
            for embed in m.get("embeds") or []:
                parts = [embed.get("title"), embed.get("description")]
                content += " [Embed: " + " | ".join(p for p in parts if p) + "]"
            for attachment in m.get("attachments") or []:
                content += f" [Dosya: {attachment.get('url') or attachment.get('filename')}]"
            lines.append(f"[{stamp}] {author}: {content.strip()}")
        lines.append("=" * 60)
        lines.append(f"Toplam mesaj: {len(messages)}")
        return "\n".join(lines)

    async def log(self, guild_id: str, embed: EmbedBuilder, file: Optional[File] = None) -> None:
        channel_id = self.store.guild(guild_id)["log_channel"]
        if not channel_id:
            return
        try:
            if file is not None:
                await self.rest.create_message_with_file(guild_id, channel_id, {"embeds": [embed], "file": file})
            else:
                await self.rest.create_message(guild_id, channel_id, {"embeds": [embed]})
        except HTTPException as exc:
            log.warning("Log kanalına yazılamadı: %s", exc)

    # ---------------------------------------------- hoş geldin / ayrılma
    @staticmethod
    def _member_info(member: Any) -> tuple:
        """GuildMember nesnesi veya ham dict'ten (guild_id, user_id, isim) çıkarır."""
        if isinstance(member, dict):
            user = member.get("user") or {}
            return (str(member.get("guild_id")), str(user.get("id") or member.get("user_id")),
                    user.get("display_name") or user.get("username") or "Bilinmeyen")
        return str(member.guild.id), member.id, member.display_name

    async def on_member_join(self, member: Any) -> None:
        guild_id, user_id, name = self._member_info(member)
        cfg = self.store.guild(guild_id)
        guild = self.client.guilds.get(guild_id)
        if guild is not None:
            guild.member_count += 1
        if cfg["auto_role"]:
            try:
                await self.rest.add_member_role(guild_id, user_id, cfg["auto_role"], "Oto-rol")
            except HTTPException as exc:
                log.warning("Oto-rol verilemedi: %s", exc)
        if cfg["welcome_channel"]:
            text = fill_template(cfg["welcome_message"], user_id, name, guild.name if guild else "",
                                 guild.member_count if guild else 0)
            embed = (EmbedBuilder().set_title("🎉 Yeni Üye!").set_description(text).set_color(Colors.Green)
                     .add_fields({"name": "👤 Kullanıcı", "value": f"<@{user_id}>", "inline": True},
                                 {"name": "🆔 ID", "value": user_id, "inline": True})
                     .set_footer(text=f"Katılım: {_now()}").set_timestamp())
            avatar = getattr(getattr(member, "user", None), "avatar_url", None)
            if avatar:
                embed.set_thumbnail(avatar)
            try:
                await self.rest.create_message(guild_id, cfg["welcome_channel"], {"content": f"<@{user_id}>", "embeds": [embed]})
            except HTTPException as exc:
                log.warning("Hoş geldin mesajı gönderilemedi: %s", exc)

    async def on_member_leave(self, member: Any) -> None:
        guild_id, user_id, name = self._member_info(member)
        cfg = self.store.guild(guild_id)
        guild = self.client.guilds.get(guild_id)
        if guild is not None and guild.member_count > 0:
            guild.member_count -= 1
        if not cfg["leave_channel"]:
            return
        text = fill_template(cfg["leave_message"], user_id, name, guild.name if guild else "",
                             guild.member_count if guild else 0)
        embed = EmbedBuilder().set_title("👋 Üye Ayrıldı").set_description(text).set_color(Colors.Red).set_timestamp()
        try:
            await self.rest.create_message(guild_id, cfg["leave_channel"], {"embeds": [embed]})
        except HTTPException as exc:
            log.warning("Ayrılma mesajı gönderilemedi: %s", exc)

    def run(self, token: str) -> None:
        self.client.run(token)


if __name__ == "__main__":
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise SystemExit("BOT_TOKEN ortam değişkeni ayarlanmamış. Windows: set BOT_TOKEN=tokenin")
    data_file = os.environ.get("TICKET_DATA", os.path.join(os.path.dirname(os.path.abspath(__file__)), "ticket_data.json"))
    TicketBot(data_file).run(token)
