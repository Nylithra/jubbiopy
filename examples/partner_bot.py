"""?partner yazılınca topluluk tanıtım embed'ini gönderen bot.

Çalıştırma (Windows)::

    set BOT_TOKEN=tokenin
    python examples\\partner_bot.py
"""

import os
import time

from jubbiopy import ActionRowBuilder, ButtonBuilder, ButtonStyle, Client, EmbedBuilder, GatewayIntentBits, HTTPException

PREFIX_COMMAND = "?partner"
INVITE_URL = "https://jubbio.com/invite/J32qroJv"
COOLDOWN = 30  # aynı kanalda tekrar kullanmak için bekleme (sn)
COLOR = 0x00B4D8

TITLE = "🚀 Jubbio Devs: Jubbio Ekosistemini Birlikte Şekillendiriyoruz!"

DESCRIPTION = f"""Jubbio için bot geliştirmek hiç bu kadar kolay ve esnek olmamıştı!

Jubbio Devs, Jubbio.js kütüphanesini farklı yazılım dillerine uyarlayan ve geliştiricilere güçlü, optimize edilmiş bot altyapıları sunan bağımsız bir toplulukdur. Amacımız, hangi dili kullanırsanız kullanın Jubbio platformunda hayal ettiğiniz botları ve entegrasyonları sorunsuz bir şekilde hayata geçirmenizi sağlamak.

:fire: JubbioPY Yayında!

Python tutkunları müjde! JubbioPY kütüphanemiz tamamlandı ve şu anda yayında. Artık Python’ın sade ve güçlü yapısıyla Jubbio botlarınızı yazabileceksiniz!

:sparkles: Jubbio Devs Size Ne Sunuyor?

:hammer_and_wrench: Çoklu Dil Desteği: Jubbio.js mantığını Python ve diğer dillere taşıyarak özgürce kod yazmanızı sağlıyoruz.

:package: Hazır Bot Altyapıları: Sıfırdan başlamanıza gerek kalmadan, doğrudan projenize odaklanabileceğiniz hazır şablonlar.

:handshake: Geliştirici Topluluğu: Sorularınızı sorabileceğiniz, fikir alışverişinde bulunabileceğiniz ve projenizi tanıtabileceğiniz aktif bir ortam.

:pushpin: Siz de Jubbio ekosisteminde iz bırakmak ve JubbioPY duyurusunu kaçırmamak için topluluğumuza katılın!"""

FOOTER = "Jubbio Devs & Lanux Yazılım Hizmetleri"


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
                print(f"Mesaj '{name}' olarak gönderildi; önceki biçimler için bot'un izni yok.")
            return
        except HTTPException as exc:
            print(f"'{name}' gönderilemedi: HTTP {exc.status} {exc.text}")
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
        print(f"{client.user.username} hazır, '{PREFIX_COMMAND}' yazınca tanıtım gönderilecek.")

    @client.on("messageCreate")
    async def on_message(message):
        if message.author.bot or message.content.strip().lower() != PREFIX_COMMAND:
            return
        now = time.monotonic()
        if now - last_used.get(message.channel_id, 0) < COOLDOWN:
            return  
        last_used[message.channel_id] = now
        await send_partner(message)

    return client


if __name__ == "__main__":
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise SystemExit("BOT_TOKEN ayarlanmamış. Windows: set BOT_TOKEN=tokenin")
    create_client().run(token)
