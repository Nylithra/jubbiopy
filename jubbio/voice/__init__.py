"""Jubbio ses desteği (``@jubbio/voice`` karşılığı, LiveKit altyapısı).

Kurulum: ``pip install "jubbio.py[voice]" yt-dlp`` — ses PyAV ile çözülür, ayrı
FFmpeg kurulumu gerekmez (FFmpeg programı varsa o kullanılır).

Örnek::

    from jubbio.voice import join_voice_channel, create_audio_player, create_audio_resource

    connection = join_voice_channel(
        channel_id="123456789",
        guild_id="987654321",
        adapter_creator=client.voice.adapters.get("987654321"),
    )
    player = create_audio_player()
    connection.subscribe(player)
    player.play(create_audio_resource("muzik.mp3"))
"""

from .connection import (
    VoiceConnection,
    VoiceConnectionState,
    enters_state,
    get_voice_connection,
    get_voice_connections,
    join_voice_channel,
)
from .enums import AudioPlayerStatus, NoSubscriberBehavior, StreamType, VoiceConnectionStatus
from .player import AudioPlayer, AudioPlayerError, AudioPlayerState, create_audio_player
from .resource import (
    AudioInfo,
    AudioResource,
    create_audio_resource,
    create_audio_resource_from_url,
    probe_audio_info,
)

# JS isimleriyle takma adlar
joinVoiceChannel = join_voice_channel
getVoiceConnection = get_voice_connection
createAudioPlayer = create_audio_player
createAudioResource = create_audio_resource
createAudioResourceFromUrl = create_audio_resource_from_url
probeAudioInfo = probe_audio_info
entersState = enters_state

__all__ = [
    "AudioInfo", "AudioPlayer", "AudioPlayerError", "AudioPlayerState", "AudioPlayerStatus", "AudioResource",
    "NoSubscriberBehavior", "StreamType", "VoiceConnection", "VoiceConnectionState", "VoiceConnectionStatus",
    "create_audio_player", "create_audio_resource", "create_audio_resource_from_url", "enters_state",
    "get_voice_connection", "get_voice_connections", "join_voice_channel", "probe_audio_info",
    "joinVoiceChannel", "getVoiceConnection", "createAudioPlayer", "createAudioResource",
    "createAudioResourceFromUrl", "probeAudioInfo", "entersState",
]
