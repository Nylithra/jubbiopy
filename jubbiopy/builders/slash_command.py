"""Slash komut oluşturucu."""

from __future__ import annotations

from typing import Any, Callable, Dict, Mapping, Optional, TypeVar, Union

from .._utils import CamelCaseCompat
from ..enums import ApplicationCommandOptionType, ChannelType

T = TypeVar("T", bound="SlashCommandOptionBuilder")


class SlashCommandOptionBuilder(CamelCaseCompat):
    option_type: ApplicationCommandOptionType

    def __init__(self) -> None:
        self.data: Dict[str, Any] = {"type": int(self.option_type)}

    def set_name(self: T, name: str) -> T:
        self.data["name"] = name
        return self

    def set_description(self: T, description: str) -> T:
        self.data["description"] = description
        return self

    def set_required(self: T, required: bool = True) -> T:
        self.data["required"] = required
        return self

    def to_json(self) -> Dict[str, Any]:
        result = dict(self.data)
        if "choices" in result:
            result["choices"] = [dict(c) for c in result["choices"]]
        return result

    to_dict = to_json


class _ChoicesMixin:
    data: Dict[str, Any]

    def add_choices(self, *choices: Mapping[str, Any]):
        self.data.setdefault("choices", []).extend(dict(c) for c in choices)
        return self

    def set_choices(self, *choices: Mapping[str, Any]):
        self.data["choices"] = [dict(c) for c in choices]
        return self

    def set_autocomplete(self, autocomplete: bool = True):
        self.data["autocomplete"] = autocomplete
        return self


class _RangeMixin:
    data: Dict[str, Any]

    def set_min_value(self, min_value: float):
        self.data["min_value"] = min_value
        return self

    def set_max_value(self, max_value: float):
        self.data["max_value"] = max_value
        return self


class SlashCommandStringOption(_ChoicesMixin, SlashCommandOptionBuilder):
    option_type = ApplicationCommandOptionType.String

    def set_min_length(self, min_length: int) -> "SlashCommandStringOption":
        self.data["min_length"] = min_length
        return self

    def set_max_length(self, max_length: int) -> "SlashCommandStringOption":
        self.data["max_length"] = max_length
        return self


class SlashCommandIntegerOption(_ChoicesMixin, _RangeMixin, SlashCommandOptionBuilder):
    option_type = ApplicationCommandOptionType.Integer


class SlashCommandNumberOption(_ChoicesMixin, _RangeMixin, SlashCommandOptionBuilder):
    option_type = ApplicationCommandOptionType.Number


class SlashCommandBooleanOption(SlashCommandOptionBuilder):
    option_type = ApplicationCommandOptionType.Boolean


class SlashCommandUserOption(SlashCommandOptionBuilder):
    option_type = ApplicationCommandOptionType.User


class SlashCommandChannelOption(SlashCommandOptionBuilder):
    option_type = ApplicationCommandOptionType.Channel

    def add_channel_types(self, *types: Union[ChannelType, int]) -> "SlashCommandChannelOption":
        self.data.setdefault("channel_types", []).extend(int(t) for t in types)
        return self


class SlashCommandRoleOption(SlashCommandOptionBuilder):
    option_type = ApplicationCommandOptionType.Role


class SlashCommandMentionableOption(SlashCommandOptionBuilder):
    option_type = ApplicationCommandOptionType.Mentionable


class SlashCommandAttachmentOption(SlashCommandOptionBuilder):
    option_type = ApplicationCommandOptionType.Attachment


OptionFactory = Callable[[Any], Any]


class _OptionsContainer(CamelCaseCompat):
    data: Dict[str, Any]

    def _add(self, option: SlashCommandOptionBuilder, fn: Optional[OptionFactory]):
        result = fn(option) if fn is not None else option
        self.data["options"].append((result or option).to_json())
        return self

    def add_string_option(self, fn: Optional[OptionFactory] = None):
        return self._add(SlashCommandStringOption(), fn)

    def add_integer_option(self, fn: Optional[OptionFactory] = None):
        return self._add(SlashCommandIntegerOption(), fn)

    def add_number_option(self, fn: Optional[OptionFactory] = None):
        return self._add(SlashCommandNumberOption(), fn)

    def add_boolean_option(self, fn: Optional[OptionFactory] = None):
        return self._add(SlashCommandBooleanOption(), fn)

    def add_user_option(self, fn: Optional[OptionFactory] = None):
        return self._add(SlashCommandUserOption(), fn)

    def add_channel_option(self, fn: Optional[OptionFactory] = None):
        return self._add(SlashCommandChannelOption(), fn)

    def add_role_option(self, fn: Optional[OptionFactory] = None):
        return self._add(SlashCommandRoleOption(), fn)

    def add_mentionable_option(self, fn: Optional[OptionFactory] = None):
        return self._add(SlashCommandMentionableOption(), fn)

    def add_attachment_option(self, fn: Optional[OptionFactory] = None):
        return self._add(SlashCommandAttachmentOption(), fn)

    def set_name(self, name: str):
        self.data["name"] = name
        return self

    def set_description(self, description: str):
        self.data["description"] = description
        return self

    def to_json(self) -> Dict[str, Any]:
        result = dict(self.data)
        result["options"] = [dict(o) for o in result.get("options", [])]
        return result

    to_dict = to_json


class SlashCommandSubcommandBuilder(_OptionsContainer):
    """Alt komut oluşturucu."""

    def __init__(self) -> None:
        self.data: Dict[str, Any] = {"type": int(ApplicationCommandOptionType.Subcommand), "options": []}


class SlashCommandSubcommandGroupBuilder(_OptionsContainer):
    """Alt komut grubu oluşturucu."""

    def __init__(self) -> None:
        self.data: Dict[str, Any] = {"type": int(ApplicationCommandOptionType.SubcommandGroup), "options": []}

    def add_subcommand(self, fn: Optional[OptionFactory] = None) -> "SlashCommandSubcommandGroupBuilder":
        sub = SlashCommandSubcommandBuilder()
        result = fn(sub) if fn is not None else sub
        self.data["options"].append((result or sub).to_json())
        return self


class SlashCommandBuilder(_OptionsContainer):
    """Slash komut oluşturucu.

    Örnek::

        command = (SlashCommandBuilder()
                   .set_name("selamla")
                   .set_description("Bir kullanıcıyı selamla")
                   .add_user_option(lambda o: o.set_name("kullanici")
                                               .set_description("Selamlanacak kişi")
                                               .set_required(True)))
    """

    def __init__(self) -> None:
        self.data: Dict[str, Any] = {"options": []}

    def set_default_member_permissions(self, permissions: Union[int, str, None]) -> "SlashCommandBuilder":
        if permissions is None:
            self.data.pop("default_member_permissions", None)
        else:
            self.data["default_member_permissions"] = str(permissions)
        return self

    def set_dm_permission(self, enabled: bool) -> "SlashCommandBuilder":
        self.data["dm_permission"] = enabled
        return self

    def set_nsfw(self, nsfw: bool = True) -> "SlashCommandBuilder":
        self.data["nsfw"] = nsfw
        return self

    def add_subcommand(self, fn: Optional[OptionFactory] = None) -> "SlashCommandBuilder":
        sub = SlashCommandSubcommandBuilder()
        result = fn(sub) if fn is not None else sub
        self.data["options"].append((result or sub).to_json())
        return self

    def add_subcommand_group(self, fn: Optional[OptionFactory] = None) -> "SlashCommandBuilder":
        group = SlashCommandSubcommandGroupBuilder()
        result = fn(group) if fn is not None else group
        self.data["options"].append((result or group).to_json())
        return self


SlashCommandOptionType = ApplicationCommandOptionType
