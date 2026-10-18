"""Temel bot örneği: mesaj komutları, embed ve butonlar.

Çalıştırma:  BOT_TOKEN=... python examples/basic_bot.py
"""

import os

from jubbiopy import (
    ActionRowBuilder,
    ButtonBuilder,
    ButtonStyle,
    Client,
    Colors,
    EmbedBuilder,
    GatewayIntentBits,
)

client = Client(intents=[
    GatewayIntentBits.Guilds,
    GatewayIntentBits.GuildMessages,
    GatewayIntentBits.MessageContent,
])


@client.on("ready")
async def on_ready(c: Client):
    print(f"✅ {client.user.username} çevrimiçi! ({len(client.guilds)} sunucu)")


@client.on("messageCreate")
async def on_message(message):
    if message.author.bot:
        return

    if message.content == "!ping":
        await message.reply(f"🏓 Pong! Gecikme: {client.ping}ms")

    elif message.content == "!bilgi":
        embed = (EmbedBuilder()
                 .set_title("Sunucu Bilgisi")
                 .set_description(f"Merhaba {message.author}!")
                 .set_color(Colors.Blue)
                 .add_fields(
                     {"name": "Sunucu", "value": str(message.guild), "inline": True},
                     {"name": "Üye sayısı", "value": str(message.guild.member_count if message.guild else 0), "inline": True},
                 )
                 .set_footer(text="JubbioPy")
                 .set_timestamp())
        row = ActionRowBuilder().add_components(
            ButtonBuilder().set_custom_id("tesekkur").set_label("Teşekkürler!").set_style(ButtonStyle.Success),
            ButtonBuilder().set_url("https://jubbio.com").set_label("Jubbio").set_style(ButtonStyle.Link),
        )
        await message.channel.send(embeds=[embed], components=[row])


@client.on("interactionCreate")
async def on_interaction(interaction):
    if interaction.is_button() and interaction.custom_id == "tesekkur":
        await interaction.reply("Rica ederim! 😊", ephemeral=True)


client.run(os.environ["BOT_TOKEN"])
