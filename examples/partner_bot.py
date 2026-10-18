"""?partner yazılınca topluluk tanıtım embed'ini gönderen bot.

Çalıştırma (Windows)::

    set BOT_TOKEN=tokenin
    python examples\\partner_bot.py
"""

import os
import time

from jubbiopy import ActionRowBuilder, ButtonBuilder, ButtonStyle, Client, EmbedBuilder, GatewayIntentBits, HTTPException

PREFIX_COMMAND = "?partner"
INVITE_URL = "https://jubbio.com/invite/ac79UK1K"
COOLDOWN = 30  # aynı kanalda tekrar kullanmak için bekleme (sn)
COLOR = 0x00B4D8

TITLE = ":shield: JUBBIO | SİBER GÜVENLİK & BİLİŞİM TOPLULUĞU :computer:"

DESCRIPTION = f"""İnternette güvende kalmak, teknolojiyi daha iyi anlamak ve bilişim dünyasında kendini geliştirmek ister misin? O hâlde doğru yerdesin!

:rotating_light: **Siber tehditlere karşı bilinçlen, teknolojiyi öğren, birlikte gelişelim!**

:globe_with_meridians: **Sunucumuzda seni neler bekliyor?**

:closed_lock_with_key: **Siber Güvenlik Rehberi**
- Güncel dolandırıcılık yöntemleri ve internet tehditleri
- Oltalama (phishing) saldırılarını tanıma ve korunma yolları
- Sahte siteleri, şüpheli bağlantıları ve tehlikeli mesajları ayırt etme
- Hesap güvenliği, gizlilik ve dijital güvenlik önerileri

:computer: **Bilişim ve Teknik Destek**
- Bilgisayar, yazılım ve teknoloji sorunlarına çözüm arama
- Karşılaştığın hataları paylaşma ve birlikte çözüm üretme
- Teknik sorularını sorabileceğin, bilgi alışverişi yapabileceğin bir ortam

:robot_face: **Bot Geliştirme ve Projeler**
- Bot geliştirmeye ilgi duyanlar için bilgi paylaşımı
- Kodlama, otomasyon ve proje geliştirme üzerine fikir alışverişi
- Topluluk büyüdükçe üyelerin kendi botlarını oluşturmasına yardımcı olacak altyapı ve rehberlik çalışmaları

:books: **Birlikte Öğren, Birlikte Geliş!**

İster bilişime yeni başlamış ol, ister deneyimli bir teknoloji meraklısı… Sorularını sorabileceğin, bildiklerini paylaşabileceğin ve yeni şeyler öğrenebileceğin bir topluluğun parçası ol.

Burada amaç sadece sohbet etmek değil; bilgiyi paylaşmak, sorunlara çözüm bulmak ve teknolojiyi daha bilinçli kullanmak.

:fire: Sen de bu topluluğun bir parçası olmak ve gelişimimize katkıda bulunmak istiyorsan aramıza katıl!

:link: **SUNUCUYA KATIL:**
{INVITE_URL}

:shield: Güvenli internet. :computer: Güçlü bilgi. :handshake: Birlikte gelişen topluluk."""

FOOTER = "JUBBIO — Öğren, keşfet, geliştir!"


def partner_embed() -> EmbedBuilder:
    return (EmbedBuilder()
            .set_title(TITLE)
            .set_url(INVITE_URL)
            .set_description(DESCRIPTION)
            .set_color(COLOR)
            .set_footer(text=FOOTER)
            .set_timestamp())


def join_button() -> ActionRowBuilder:
    return ActionRowBuilder().add_components(
        ButtonBuilder().set_label("Sunucuya Katıl").set_emoji("🔗").set_style(ButtonStyle.Link).set_url(INVITE_URL)
    )


async def send_partner(message) -> None:
    """Önce embed + buton dener; izin hatasında daha basit biçimlere düşer ve sebebi yazar."""
    attempts = [
        ("embed + buton", {"embeds": [partner_embed()], "components": [join_button()]}),
        ("sadece embed", {"embeds": [partner_embed()]}),
        ("düz metin", {"content": f"{TITLE}\n\n{DESCRIPTION}\n\n{FOOTER}"}),
    ]
    for index, (name, payload) in enumerate(attempts):
        try:
            await message.channel.send(**payload)
            if index:
                print(f"ℹ️ Mesaj '{name}' olarak gönderildi; önceki biçimler için bot'un izni yok.")
            return
        except HTTPException as exc:
            print(f"⚠️ '{name}' gönderilemedi: HTTP {exc.status} {exc.text}")
            if exc.status != 403:
                return
    print("❌ Bot bu kanala hiç mesaj gönderemiyor. Bot rolüne bu kanalda 'Mesaj Gönder' "
          "(ve embed için 'Bağlantı Yerleştir') iznini verin.")


def create_client(**options) -> Client:
    client = Client(intents=[GatewayIntentBits.Guilds, GatewayIntentBits.GuildMessages,
                             GatewayIntentBits.MessageContent], **options)
    last_used = {}

    @client.on("ready")
    async def on_ready(_c):
        print(f"✅ {client.user.username} hazır! '{PREFIX_COMMAND}' yazınca tanıtım gönderilecek.")

    @client.on("messageCreate")
    async def on_message(message):
        if message.author.bot or message.content.strip().lower() != PREFIX_COMMAND:
            return
        now = time.monotonic()
        if now - last_used.get(message.channel_id, 0) < COOLDOWN:
            return  # spam'i önle
        last_used[message.channel_id] = now
        await send_partner(message)

    return client


if __name__ == "__main__":
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise SystemExit("BOT_TOKEN ayarlanmamış. Windows: set BOT_TOKEN=tokenin")
    create_client().run(token)
