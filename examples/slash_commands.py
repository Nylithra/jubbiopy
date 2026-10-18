"""Slash komutları, modal ve collector örneği.

Çalıştırma:  BOT_TOKEN=... python examples/slash_commands.py
"""

import os

from jubbiopy import (
    ActionRowBuilder,
    Client,
    GatewayIntentBits,
    ModalBuilder,
    SlashCommandBuilder,
    StringSelectMenuBuilder,
    TextInputBuilder,
    TextInputStyle,
)

client = Client(intents=[GatewayIntentBits.Guilds])

COMMANDS = [
    SlashCommandBuilder().set_name("selamla").set_description("Bir kullanıcıyı selamla")
    .add_user_option(lambda o: o.set_name("kullanici").set_description("Selamlanacak kişi").set_required(True)),

    SlashCommandBuilder().set_name("geri-bildirim").set_description("Geri bildirim formu aç"),

    SlashCommandBuilder().set_name("renk").set_description("Favori rengini seç"),
]


@client.on("ready")
async def on_ready(c: Client):
    # Komutları kaydet (tümünü değiştirir)
    await client.application.commands.set(COMMANDS)
    print(f"✅ {len(COMMANDS)} komut kaydedildi")


@client.on("interactionCreate")
async def on_interaction(interaction):
    if interaction.is_command():
        if interaction.command_name == "selamla":
            user = interaction.options.get_user("kullanici", required=True)
            await interaction.reply(f"Merhaba {user}! 👋")

        elif interaction.command_name == "geri-bildirim":
            modal = (ModalBuilder().set_custom_id("geri-bildirim-formu").set_title("Geri Bildirim")
                     .add_components(ActionRowBuilder().add_components(
                         TextInputBuilder().set_custom_id("mesaj").set_label("Mesajınız")
                         .set_style(TextInputStyle.Paragraph).set_required())))
            await interaction.show_modal(modal)

        elif interaction.command_name == "renk":
            menu = (StringSelectMenuBuilder().set_custom_id("renk-menu").set_placeholder("Bir renk seç")
                    .add_options({"label": "Kırmızı", "value": "kirmizi"},
                                 {"label": "Mavi", "value": "mavi"}))
            await interaction.reply("Renk seç:", components=[ActionRowBuilder().add_components(menu)])

    elif interaction.is_select_menu() and interaction.custom_id == "renk-menu":
        await interaction.update(f"Seçimin: **{interaction.values[0]}**", components=[])

    elif interaction.is_modal_submit() and interaction.custom_id == "geri-bildirim-formu":
        text = interaction.fields.get_text_input_value("mesaj")
        await interaction.reply(f"Teşekkürler! Mesajın alındı: {text}", ephemeral=True)


@client.on("messageCreate")
async def on_message(message):
    # Collector örneği: "!tahmin" sonrası 15 sn içinde gelen ilk sayıyı bekle
    if message.content == "!tahmin":
        await message.reply("1-10 arası bir sayı yaz (15 saniye)!")
        try:
            collected = await message.channel.await_messages(
                filter=lambda m, _: m.author.id == message.author.id and m.content.isdigit(),
                max=1, time=15, errors=["time"],
            )
            await message.channel.send(f"Tahminin: {collected.first().content}")
        except Exception:
            await message.channel.send("⏰ Süre doldu!")


client.run(os.environ["BOT_TOKEN"])
