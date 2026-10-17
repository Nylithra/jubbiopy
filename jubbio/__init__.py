"""
Jubbio.py — Jubbio platformu için Python bot kütüphanesi.

``@jubbio/core`` ve ``@jubbio/voice`` npm paketlerinin tek pakette birleşmiş
Python karşılığıdır. Ses desteği ``jubbio.voice`` modülündedir.

Yapımcı: Lanux Yazılım Hizmetleri
"""

from .builders import (
    ActionRowBuilder,
    ButtonBuilder,
    Colors,
    EmbedBuilder,
    ModalBuilder,
    SelectMenuBuilder,
    SlashCommandAttachmentOption,
    SlashCommandBooleanOption,
    SlashCommandBuilder,
    SlashCommandChannelOption,
    SlashCommandIntegerOption,
    SlashCommandMentionableOption,
    SlashCommandNumberOption,
    SlashCommandOptionType,
    SlashCommandRoleOption,
    SlashCommandStringOption,
    SlashCommandSubcommandBuilder,
    SlashCommandSubcommandGroupBuilder,
    SlashCommandUserOption,
    StringSelectMenuBuilder,
    StringSelectMenuOptionBuilder,
    TextInputBuilder,
)
from .client import Client
from .enums import (
    ActivityType,
    ApplicationCommandOptionType,
    ApplicationCommandType,
    ButtonStyle,
    ChannelType,
    ComponentType,
    GatewayIntentBits,
    GatewayOpcodes,
    InteractionResponseType,
    InteractionType,
    MessageFlags,
    OverwriteType,
    PermissionFlagsBits,
    PresenceStatus,
    TextInputStyle,
)
from .errors import CollectorEnded, GatewayError, HTTPException, JubbioError
from .events import EventEmitter
from .managers import ApplicationCommandManager
from .rest import REST, File
from .sharding import Shard, ShardClientUtil, ShardingManager, ShardStatus
from .structures import (
    AutocompleteInteraction,
    BaseChannel,
    ButtonInteraction,
    ChatInputCommandInteraction,
    Collection,
    CommandInteraction,
    CommandInteractionOptions,
    DMChannel,
    Guild,
    GuildMember,
    Interaction,
    Message,
    ModalFields,
    ModalSubmitInteraction,
    PermissionFlags,
    Permissions,
    SelectMenuInteraction,
    StringSelectMenuInteraction,
    TextChannel,
    User,
    VoiceChannel,
    VoiceState,
    create_channel,
    create_interaction,
)
from .utils import (
    BitField,
    Collector,
    Formatters,
    IntentsBitField,
    InteractionCollector,
    MessageCollector,
    PermissionsBitField,
    ReactionCollector,
    SnowflakeUtil,
    TimestampStyles,
    await_messages,
    await_reactions,
)
from .utils.formatters import (
    block_quote,
    bold,
    channel_mention,
    code_block,
    format_emoji,
    heading,
    hide_link_embed,
    hyperlink,
    inline_code,
    italic,
    ordered_list,
    quote,
    role_mention,
    spoiler,
    strikethrough,
    time,
    underline,
    unordered_list,
    user_mention,
)

__title__ = "jubbio.py"
__author__ = "Lanux Yazılım Hizmetleri"
__license__ = "MIT"
__version__ = "1.0.0"

__all__ = [
    # İstemci
    "Client", "REST", "File", "EventEmitter",
    # Enum'lar
    "ActivityType", "ApplicationCommandOptionType", "ApplicationCommandType", "ButtonStyle", "ChannelType",
    "ComponentType", "GatewayIntentBits", "GatewayOpcodes", "InteractionResponseType", "InteractionType",
    "MessageFlags", "OverwriteType", "PermissionFlagsBits", "PresenceStatus", "TextInputStyle",
    # Hatalar
    "CollectorEnded", "GatewayError", "HTTPException", "JubbioError",
    # Yapılar
    "AutocompleteInteraction", "BaseChannel", "ButtonInteraction", "ChatInputCommandInteraction", "Collection",
    "CommandInteraction", "CommandInteractionOptions", "DMChannel", "Guild", "GuildMember", "Interaction",
    "Message", "ModalFields", "ModalSubmitInteraction", "PermissionFlags", "Permissions",
    "SelectMenuInteraction", "StringSelectMenuInteraction", "TextChannel", "User", "VoiceChannel", "VoiceState",
    "create_channel", "create_interaction", "ApplicationCommandManager",
    # Builder'lar
    "ActionRowBuilder", "ButtonBuilder", "Colors", "EmbedBuilder", "ModalBuilder", "SelectMenuBuilder",
    "SlashCommandAttachmentOption", "SlashCommandBooleanOption", "SlashCommandBuilder",
    "SlashCommandChannelOption", "SlashCommandIntegerOption", "SlashCommandMentionableOption",
    "SlashCommandNumberOption", "SlashCommandOptionType", "SlashCommandRoleOption", "SlashCommandStringOption",
    "SlashCommandSubcommandBuilder", "SlashCommandSubcommandGroupBuilder", "SlashCommandUserOption",
    "StringSelectMenuBuilder", "StringSelectMenuOptionBuilder", "TextInputBuilder",
    # Araçlar
    "BitField", "Collector", "Formatters", "IntentsBitField", "InteractionCollector", "MessageCollector",
    "PermissionsBitField", "ReactionCollector", "SnowflakeUtil", "TimestampStyles", "await_messages",
    "await_reactions", "block_quote", "bold", "channel_mention", "code_block", "format_emoji", "heading",
    "hide_link_embed", "hyperlink", "inline_code", "italic", "ordered_list", "quote", "role_mention", "spoiler",
    "strikethrough", "time", "underline", "unordered_list", "user_mention",
    # Sharding
    "Shard", "ShardClientUtil", "ShardingManager", "ShardStatus",
]
