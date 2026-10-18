"""Jubbio API sabitleri (``@jubbio/core`` enums ile birebir)."""

from __future__ import annotations

from enum import Enum, IntEnum, IntFlag


class GatewayIntentBits(IntFlag):
    Guilds = 1 << 0
    GuildMembers = 1 << 1
    GuildModeration = 1 << 2
    GuildEmojisAndStickers = 1 << 3
    GuildIntegrations = 1 << 4
    GuildWebhooks = 1 << 5
    GuildInvites = 1 << 6
    GuildVoiceStates = 1 << 7
    GuildPresences = 1 << 8
    GuildMessages = 1 << 9
    GuildMessageReactions = 1 << 10
    GuildMessageTyping = 1 << 11
    DirectMessages = 1 << 12
    DirectMessageReactions = 1 << 13
    DirectMessageTyping = 1 << 14
    MessageContent = 1 << 15
    GuildScheduledEvents = 1 << 16
    AutoModerationConfiguration = 1 << 20
    AutoModerationExecution = 1 << 21


class GatewayOpcodes(IntEnum):
    Dispatch = 0
    Heartbeat = 1
    Identify = 2
    PresenceUpdate = 3
    VoiceStateUpdate = 4
    Resume = 6
    Reconnect = 7
    RequestGuildMembers = 8
    InvalidSession = 9
    Hello = 10
    HeartbeatAck = 11


class InteractionType(IntEnum):
    Ping = 1
    ApplicationCommand = 2
    MessageComponent = 3
    ApplicationCommandAutocomplete = 4
    ModalSubmit = 5


class ApplicationCommandType(IntEnum):
    ChatInput = 1
    User = 2
    Message = 3


class ApplicationCommandOptionType(IntEnum):
    Subcommand = 1
    SubcommandGroup = 2
    String = 3
    Integer = 4
    Boolean = 5
    User = 6
    Channel = 7
    Role = 8
    Mentionable = 9
    Number = 10
    Attachment = 11


class ChannelType(IntEnum):
    GuildText = 0
    DM = 1
    GuildVoice = 2
    GroupDM = 3
    GuildCategory = 4
    GuildAnnouncement = 5
    GuildStageVoice = 13
    GuildDirectory = 14
    GuildForum = 15


class InteractionResponseType(IntEnum):
    Pong = 1
    ChannelMessageWithSource = 4
    DeferredChannelMessageWithSource = 5
    DeferredUpdateMessage = 6
    UpdateMessage = 7
    ApplicationCommandAutocompleteResult = 8
    Modal = 9


class MessageFlags(IntFlag):
    Crossposted = 1 << 0
    IsCrosspost = 1 << 1
    SuppressEmbeds = 1 << 2
    SourceMessageDeleted = 1 << 3
    Urgent = 1 << 4
    Ephemeral = 1 << 6
    Loading = 1 << 7
    SuppressNotifications = 1 << 12


class ActivityType(IntEnum):
    Playing = 0
    Streaming = 1
    Listening = 2
    Watching = 3
    Custom = 4
    Competing = 5


class PresenceStatus(str, Enum):
    Online = "online"
    Idle = "idle"
    DoNotDisturb = "dnd"
    Invisible = "invisible"
    Offline = "offline"


class OverwriteType(IntEnum):
    Role = 0
    Member = 1


class ComponentType(IntEnum):
    ActionRow = 1
    Button = 2
    StringSelect = 3
    TextInput = 4


class ButtonStyle(IntEnum):
    Primary = 1
    Secondary = 2
    Success = 3
    Danger = 4
    Link = 5


class TextInputStyle(IntEnum):
    Short = 1
    Paragraph = 2


class _PermissionFlagsBits:
    """İzin bitleri. ``community-service`` permissions.go ile uyumlu."""

    # Genel (0-9)
    CreateInstantInvite = 1 << 0
    KickMembers = 1 << 1
    BanMembers = 1 << 2
    Administrator = 1 << 3
    ManageChannels = 1 << 4
    ManageGuild = 1 << 5
    AddReactions = 1 << 6
    ViewAuditLog = 1 << 7
    ViewGuildInsights = 1 << 8
    Stream = 1 << 9
    ViewChannel = 1 << 10
    # Mesajlar (11-19)
    SendMessages = 1 << 11
    SendTTSMessages = 1 << 12
    ManageMessages = 1 << 13
    EmbedLinks = 1 << 14
    AttachFiles = 1 << 15
    ReadMessageHistory = 1 << 16
    UseExternalEmojis = 1 << 17
    UseSlashCommands = 1 << 18
    MentionEveryone = 1 << 19
    # Ses (20-27)
    Connect = 1 << 20
    Speak = 1 << 21
    MuteMembers = 1 << 22
    DeafenMembers = 1 << 23
    MoveMembers = 1 << 24
    UseVAD = 1 << 25
    ChangeCodec = 1 << 26
    AudioQualityAdmin = 1 << 27
    # Video ve ekran paylaşımı (28-37)
    VideoCall = 1 << 28
    ShareScreen = 1 << 29
    ShareCamera = 1 << 30
    ControlQuality = 1 << 31
    RequestToSpeak = 1 << 32
    ManageEvents = 1 << 33
    AddMembers = 1 << 34
    RemoveMembers = 1 << 35
    ChangeGroupIcon = 1 << 36
    ChangeDMSettings = 1 << 37
    # Gelişmiş (38-43)
    ManageGroup = 1 << 38
    UseActivities = 1 << 39
    ModerateMembers = 1 << 40
    ManageRoles = 1 << 41
    ManageEmojis = 1 << 42
    PrioritySpeaker = 1 << 43

    @classmethod
    def items(cls):
        return [(k, v) for k, v in vars(cls).items() if not k.startswith("_") and isinstance(v, int)]

    @classmethod
    def as_dict(cls):
        return dict(cls.items())


PermissionFlagsBits = _PermissionFlagsBits
