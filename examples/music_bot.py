"""Müzik botu örneği. Gerekenler: ``pip install "jubbio[voice]" yt-dlp`` (FFmpeg kurmak gerekmez).

Komutlar: /cal <url veya arama>, /duraklat, /devam, /durdur, /ayril

Çalıştırma:  BOT_TOKEN=... python examples/music_bot.py
"""

import os

from jubbiopy import Client, Colors, EmbedBuilder, GatewayIntentBits, SlashCommandBuilder
from jubbiopy.voice import (
    AudioPlayerStatus,
    create_audio_player,
    create_audio_resource_from_url,
    get_voice_connection,
    join_voice_channel,
    probe_audio_info,
)

client = Client(intents=[GatewayIntentBits.Guilds, GatewayIntentBits.GuildVoiceStates])

# Sunucu başına bir çalar
players = {}


def get_player(guild_id):
    if guild_id not in players:
        player = create_audio_player()
        player.on("stateChange", lambda old, new: print(f"[{guild_id}] {old.status.value} -> {new.status.value}"))
        player.on("error", lambda err: print(f"[{guild_id}] Çalma hatası: {err.message}"))
        players[guild_id] = player
    return players[guild_id]


@client.on("ready")
async def on_ready(c: Client):
    await client.application.commands.set([
        SlashCommandBuilder().set_name("cal").set_description("Müzik çal")
        .add_string_option(lambda o: o.set_name("sarki").set_description("URL veya arama").set_required(True)),
        SlashCommandBuilder().set_name("duraklat").set_description("Duraklat"),
        SlashCommandBuilder().set_name("devam").set_description("Devam et"),
        SlashCommandBuilder().set_name("durdur").set_description("Durdur"),
        SlashCommandBuilder().set_name("ayril").set_description("Ses kanalından ayrıl"),
    ])
    print(f"🎵 {client.user.username} hazır!")


@client.on("interactionCreate")
async def on_interaction(interaction):
    if not interaction.is_command():
        return
    guild_id = interaction.guild_id
    player = get_player(guild_id)

    if interaction.command_name == "cal":
        query = interaction.options.get_string("sarki", required=True)
        voice_channel = interaction.member.voice.channel_id if interaction.member else None
        if not voice_channel:
            return await interaction.reply("❌ Önce bir ses kanalına katıl!", ephemeral=True)

        await interaction.defer_reply()
        try:
            info = await probe_audio_info(query)
            connection = get_voice_connection(guild_id)
            if connection is None:
                connection = join_voice_channel(
                    channel_id=voice_channel,
                    guild_id=guild_id,
                    adapter_creator=client.voice.adapters.get(guild_id),
                )
                connection.subscribe(player)

            player.play(create_audio_resource_from_url(info.url, metadata={"title": info.title}))

            minutes, seconds = divmod(info.duration, 60)
            embed = (EmbedBuilder().set_title("🎵 Şimdi Çalıyor").set_description(f"**{info.title}**")
                     .set_color(Colors.Blue).add_fields({"name": "Süre", "value": f"{minutes}:{seconds:02d}", "inline": True})
                     .set_timestamp())
            if info.thumbnail:
                embed.set_thumbnail(info.thumbnail)
            await interaction.edit_reply(embeds=[embed])
        except Exception as exc:  # noqa: BLE001
            await interaction.edit_reply(f"❌ Hata: {exc}")

    elif interaction.command_name == "duraklat":
        await interaction.reply("⏸️ Duraklatıldı" if player.pause() else "Şu an çalan bir şey yok.")

    elif interaction.command_name == "devam":
        await interaction.reply("▶️ Devam ediliyor" if player.unpause() else "Duraklatılmış bir şey yok.")

    elif interaction.command_name == "durdur":
        player.stop()
        await interaction.reply("⏹️ Durduruldu")

    elif interaction.command_name == "ayril":
        connection = get_voice_connection(guild_id)
        if connection is not None:
            connection.destroy()
        player.stop()
        await interaction.reply("👋 Ses kanalından ayrıldım")


client.run(os.environ["BOT_TOKEN"])
