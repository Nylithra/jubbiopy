"""Builder, yapı ve yardımcı testleri."""

from __future__ import annotations

import pytest

from jubbiopy import (
    ActionRowBuilder,
    ButtonBuilder,
    ButtonStyle,
    ChannelType,
    Collection,
    Colors,
    CommandInteractionOptions,
    EmbedBuilder,
    IntentsBitField,
    ModalBuilder,
    Permissions,
    PermissionsBitField,
    SlashCommandBuilder,
    SnowflakeUtil,
    StringSelectMenuBuilder,
    StringSelectMenuOptionBuilder,
    TextInputBuilder,
    TextInputStyle,
    code_block,
    hyperlink,
    ordered_list,
)


def test_embed_builder():
    embed = (EmbedBuilder()
             .set_title("Merhaba")
             .set_color(Colors.Blue)
             .set_author(name="Yazar", icon_url="http://i")
             .add_fields({"name": "a", "value": "1", "inline": True}, [{"name": "b", "value": "2"}])
             .set_image("http://img"))
    data = embed.to_json()
    assert data["color"] == 0x3498DB
    assert data["author"] == {"name": "Yazar", "icon_url": "http://i"}
    assert [f["name"] for f in data["fields"]] == ["a", "b"]
    assert data["image"] == {"url": "http://img"}
    assert EmbedBuilder().set_color("Red").data["color"] == 0xED4245
    assert EmbedBuilder().set_color((255, 0, 0)).data["color"] == 0xFF0000
    assert EmbedBuilder().set_color("#00ff00").data["color"] == 0x00FF00
    assert "title" not in embed.set_title(None).data
    with pytest.raises(ValueError):
        EmbedBuilder().add_fields([{"name": str(i), "value": "v"} for i in range(26)])
    copy = EmbedBuilder.from_(embed)
    copy.data["fields"].append({"name": "c", "value": "3"})
    assert len(embed.data["fields"]) == 2


def test_components():
    row = ActionRowBuilder().add_components(
        ButtonBuilder().set_custom_id("ok").set_label("Tamam").set_style(ButtonStyle.Success).set_emoji("✅"),
        [ButtonBuilder().set_url("https://jubbio.com").set_style(ButtonStyle.Link).set_label("Site")],
    )
    data = row.to_json()
    assert data["type"] == 1
    assert data["components"][0] == {"type": 2, "custom_id": "ok", "label": "Tamam", "style": 3, "emoji": {"name": "✅"}}
    assert data["components"][1]["style"] == 5

    menu = StringSelectMenuBuilder().set_custom_id("m").add_options(
        {"label": "A", "value": "a"}, StringSelectMenuOptionBuilder().set_label("B").set_value("b").set_default()
    )
    assert menu.to_json()["options"] == [{"label": "A", "value": "a"}, {"label": "B", "value": "b", "default": True}]

    modal = ModalBuilder().set_custom_id("f").set_title("Form").add_components(
        ActionRowBuilder().add_components(
            TextInputBuilder().set_custom_id("ad").set_label("Ad").set_style(TextInputStyle.Short).set_required()
        )
    )
    assert modal.to_json()["components"][0]["components"][0]["type"] == 4


def test_slash_command_builder():
    command = (SlashCommandBuilder()
               .set_name("ayar")
               .set_description("Ayarlar")
               .set_default_member_permissions(8)
               .add_string_option(lambda o: o.set_name("dil").set_description("Dil")
                                  .add_choices({"name": "Türkçe", "value": "tr"}).set_required())
               .add_channel_option(lambda o: o.set_name("kanal").set_description("K").add_channel_types(ChannelType.GuildText))
               .add_subcommand(lambda s: s.set_name("goster").set_description("Göster")
                               .add_integer_option(lambda o: o.set_name("n").set_description("N").set_min_value(1))))
    data = command.to_json()
    assert data["default_member_permissions"] == "8"
    assert data["options"][0] == {"type": 3, "name": "dil", "description": "Dil",
                                  "choices": [{"name": "Türkçe", "value": "tr"}], "required": True}
    assert data["options"][1]["channel_types"] == [0]
    assert data["options"][2]["type"] == 1 and data["options"][2]["options"][0]["min_value"] == 1
    # JS stili camelCase de çalışır
    js = SlashCommandBuilder().setName("x").setDescription("y").addBooleanOption(lambda o: o.setName("b").setDescription("c"))
    assert js.toJSON()["options"][0]["type"] == 5


def test_command_options():
    options = CommandInteractionOptions(None, [  # type: ignore[arg-type]
        {"name": "alt", "type": 1, "options": [
            {"name": "metin", "type": 3, "value": "merhaba"},
            {"name": "kotu", "type": 3, "value": "__import__('os').system('ls')"},
            {"name": "sayi", "type": 4, "value": 0},
            {"name": "aktif", "type": 5, "value": False},
            {"name": "ara", "type": 3, "value": "ab", "focused": True},
        ]},
    ])
    assert options.get_subcommand() == "alt"
    assert options.get_string("metin") == "merhaba"
    assert options.get_string("kotu") == ""  # tehlikeli kalıp temizlendi
    assert options.get_integer("sayi") == 0
    assert options.get_boolean("aktif") is False
    assert options.get_focused() == {"name": "ara", "value": "ab"}
    with pytest.raises(KeyError):
        options.get_string("yok", required=True)


def test_permissions():
    perms = Permissions(PermissionsBitField.Flags["SendMessages"] | PermissionsBitField.Flags["ViewChannel"])
    assert perms.has("SendMessages") and not perms.has("BanMembers")
    assert perms.missing(["SendMessages", "KickMembers"]) == ["KickMembers"]
    assert Permissions("8").has("BanMembers")
    assert Permissions(0, is_owner=True).has("Administrator")
    assert sorted(perms.to_array()) == ["SendMessages", "ViewChannel"]
    assert str(perms.clone().add("KickMembers").remove("ViewChannel")) == str((1 << 11) | (1 << 1))

    field = PermissionsBitField(["KickMembers", "BanMembers"])
    assert field.has("KickMembers") and "BanMembers" in field
    assert PermissionsBitField(8).has("ManageGuild")
    assert not PermissionsBitField(8).has("ManageGuild", check_admin=False)

    intents = IntentsBitField(["Guilds", "MessageContent"])
    assert intents.has_privileged() and intents.get_privileged() == ["MessageContent"]


def test_collection():
    coll = Collection({"a": 1, "b": 2, "c": 3})
    assert coll.cache is coll and coll.size == 3
    assert coll.first() == 1 and coll.last() == 3 and coll.first(2) == [1, 2]
    assert coll.find(lambda v: v > 1) == 2
    assert coll.find(lambda v, k: k == "c") == 3
    assert dict(coll.filter(lambda v, k, c: v % 2)) == {"a": 1, "c": 3}
    assert coll.map(lambda v: v * 10) == [10, 20, 30]
    assert coll.reduce(lambda acc, v: acc + v, 0) == 6
    assert coll.some(lambda v: v == 3) and coll.every(lambda v: v > 0)
    assert coll.delete("a") and not coll.delete("a")


def test_snowflake_and_formatters():
    snowflake = SnowflakeUtil.generate(1700000000000)
    assert SnowflakeUtil.timestamp_from(snowflake) == 1700000000000
    assert SnowflakeUtil.deconstruct(snowflake).timestamp == 1700000000000
    assert code_block("x", "py") == "```py\nx\n```"
    assert hyperlink("a", "http://b", "c") == '[a](http://b "c")'
    assert ordered_list(["x", "y"]) == "1. x\n2. y"
