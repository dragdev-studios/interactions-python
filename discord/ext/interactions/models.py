import logging
import textwrap
from enum import IntEnum
from typing import Any, List, Union
from datetime import datetime

import discord
from discord.ext import commands

from .errors import InteractionsError, ExpiredToken
from aiohttp import ClientSession
from discord import HTTPException
from inspect import Parameter as Param

BASE = "https://discord.com/api/v8"
USERAGENT = "DiscordBot (https://github.com/dragdev-studios/interactions-python, 0.0.1)"


def to_json(d: dict):
    from json import dumps
    return dumps(d, ensure_ascii=True)


class InteractionType(IntEnum):
    PING = 1
    APPLICATION_COMMAND = 2


class InteractionResponseType(IntEnum):
    PONG = 1
    ACKNOWLEDGE = 2
    CHANNEL_MESSAGE = 3
    CHANNEL_MESSAGE_WITH_SOURCE = 4
    ACKNOWLEDGE_WITH_SOURCE = 5


class InteractionResponseFlags(IntEnum):
    EPHEMERAL = 1 << 6
    ASYNC = EPHEMERAL


class ApplicationCommandInteractionDataOption:
    """https://discord.com/developers/docs/interactions/slash-commands#interaction-applicationcommandinteractiondataoption"""

    def __init__(self, name: str, value: Any, options):
        self.name = name
        self.value = value
        self.options: List[ApplicationCommandInteractionDataOption] = options


class ApplicationCommandInteractionData:
    """https://discord.com/developers/docs/interactions/slash-commands#interaction-applicationcommandinteractiondata"""

    def __init__(self, id: str, name: str, options: ApplicationCommandInteractionDataOption):
        self.id = int(id)
        self.name = name
        self.options = options


class ApplicationCommandOptionType(IntEnum):
    SUB_COMMAND = 1
    SUB_COMMAND_GROUP = 2
    STRING = 3
    INTEGER = 4
    BOOLEAN = 5
    USER = 6
    CHANNEL = 7
    ROLE = 8


class Interaction:
    def __init__(self, bot, *, id: str, type: int, data: ApplicationCommandInteractionData, guild: discord.Guild,
                 channel: discord.TextChannel, member: discord.Member, token: str, version: int = 1, raw: dict):
        self.bot = bot
        self.id = int(id)
        self.type = InteractionType(type)
        self.data = data
        self.guild = guild
        self.channel = channel
        self.member = member

        # These aren't really useful but we'll include them anyway.
        self.token = token
        self.token_start = datetime.utcnow()
        self.version = version

        # private
        self.__raw = raw

    @classmethod
    async def from_request(cls, bot: Union[commands.Bot, commands.AutoShardedBot], body: dict):
        """
        Creates an Interaction from a request to a server. body should be JSON encoded.

        :param bot: The commands.bot
        :param body: The JSON provided by the discord request
        :return: The resolved Interaction
        """
        guild = bot.get_guild(int(body["guild_id"]))

        kwargs = dict(
            id=body["id"],
            type=body["type"],
            guild=guild,
            channel=bot.get_channel(int(body["channel_id"])),
            member=guild.get_member(body["member"]["id"]) or await guild.fetch_member(body["member"]["id"]),
            token=body["token"],
            version=body["version"],
            raw=body
        )
        return cls(bot, **kwargs)

    def followup(self, content = None, *, tts = False, embed: discord.Embed = None, embeds = None,
                 allowed_mentions = None):
        """
        Returns parsed JSON for you to return to the request made to your interactions endpoint.

        This function takes similar arguments to discord.abc.manageable.send.

        :param content: The content to send. Optional
        :param tts: Boolean denoting whether to send this message with text-to-speech or not.
        :param embed: The embed to include with the message. can NOT be mixed with the embeds parameter.
        :param embeds: A list of embeds. Can not be mixed with the embed parameter.
        :param allowed_mentions: What mentions are allowed to be sent. Defaults to discord.AllowedMentions.none().
        :returns: Dict (JSON encoded)
        """
        if embed and embeds:
            raise TypeError("Can't mix embed and embeds parameters.")

        result = {}

        if content:
            content = str(content)
            result["content"] = content

        if tts:
            result["tts"] = tts

        if embed:
            embeds = [embed]

        if embeds:
            result["embeds"] = [embed.to_dict() for embed in embeds]

        if allowed_mentions is not None:
            if self.bot.allowed_mentions is not None:
                allowed_mentions = self.bot.allowed_mentions.merge(allowed_mentions).to_dict()
            else:
                allowed_mentions = allowed_mentions.to_dict()
        else:
            allowed_mentions = self.bot.allowed_mentions and self.bot.allowed_mentions.to_dict()

        result["allowed_mentions"] = allowed_mentions

        return result

    async def edit_initial_response(self, content = None, *, tts = False, embed: discord.Embed = None, embeds = None,
                                    allowed_mentions = None):
        """Edits your initial response message.

        https://discord.com/developers/docs/interactions/slash-commands#followup-messages
        (PATCH /webhooks/<application_id>/<interaction_token>/messages/@original to edit your initial response to an Interaction)"""
        URI = BASE + "/webhooks/{}/{}/messages/@original".format(str(self.bot.user.id), self.token)
        if (datetime.utcnow() - self.token_start).total_seconds() > 900:
            raise ExpiredToken
        if not self.token:
            raise InteractionsError("No interaction token provided.")

        data = self.followup(content, tts=tts, embed=embed, embeds=embeds, allowed_mentions=allowed_mentions)

        async with ClientSession() as session:
            async with session.patch(
                    URI,
                    data=to_json(data),
                    headers={
                        "Authorization": "Bot " + self.bot.http.token,
                        "User-Agent": USERAGENT
                    }
            ) as response:
                if response.status != 200:
                    raise HTTPException(
                        response,
                        await response.json()
                    )
                res = await response.json()
        return res

    async def delete_initial_response(self, *, delay: float = None):
        """Deletes your initial response message.

        https://discord.com/developers/docs/interactions/slash-commands#followup-messages
        (DELETE /webhooks/<application_id>/<interaction_token>/messages/@original to delete your initial response to an Interaction)"""
        URI = BASE + "/webhooks/{}/{}/messages/@original".format(str(self.bot.user.id), self.token)
        if (datetime.utcnow() - self.token_start).total_seconds() > 900:
            raise ExpiredToken
        if not self.token:
            raise InteractionsError("No interaction token provided.")

        async with ClientSession() as session:
            async with session.delete(
                    URI,
                    headers={
                        "Authorization": "Bot " + self.bot.http.token,
                        "User-Agent": USERAGENT
                    }
            ) as response:
                if response.status != 200:
                    raise HTTPException(
                        response,
                        await response.json()
                    )
                res = await response.json()
        return res

    async def create_new_initial_response(self, *args, **kwargs):
        """Creates a new follow up message"""
        raise NotImplementedError

    @staticmethod
    def verify_request(X_Signature_Ed25519: str, X_Signature_Timestamp: str, raw_body: str, public_key: str):
        """Verifies that a request is real.

        X_Signature_Ed25519 & X_Signature_Timestamp are the headers, replacing _ with -
        raw_body is the request body
        public_key is your application's public key.
        """
        try:
            from nacl.signing import VerifyKey
            from nacl.exceptions import BadSignatureError
        except ImportError as e:
            raise ImportError("You must install PyNaCl before using this function.") from e

        key = VerifyKey(bytes.fromhex(public_key))
        try:
            key.verify(str(X_Signature_Timestamp + raw_body).encode(), bytes.fromhex(X_Signature_Ed25519))
        except BadSignatureError:
            return False
        else:
            return True


class SlashCommand:
    BASE_TYPES = {
        str: ApplicationCommandOptionType.STRING,
        int: ApplicationCommandOptionType.INTEGER,
        bool: ApplicationCommandOptionType.BOOLEAN,
        discord.User: ApplicationCommandOptionType.USER,
        discord.TextChannel: ApplicationCommandOptionType.CHANNEL,
        discord.Role: ApplicationCommandOptionType.ROLE,
        commands.UserConverter: ApplicationCommandOptionType.USER,
        commands.TextChannelConverter: ApplicationCommandOptionType.CHANNEL,
        commands.RoleConverter: ApplicationCommandOptionType.ROLE
    }

    @staticmethod
    def _resolve_options(command):
        command = command
        content = {
            "name": command.name,
            "description": textwrap.shorten(command.short_doc, 100),
            "type": 1 if isinstance(command, commands.Command) else 2,
            "options": []
        }
        if isinstance(command, commands.Group):
            _options = []
            for cmd in command.walk_commands():
                _options.append(SlashCommand._resolve_options(cmd))
            content["options"] += _options
        else:
            args: Union[str, Param] = command.clean_params
            _options = []
            for argument in args:
                if isinstance(argument, str):
                    continue
                _type = SlashCommand.BASE_TYPES.get(argument, ApplicationCommandOptionType.STRING)
                required = argument.default == Param.empty
                # default = None if required else Param.default
                e = {
                    "name": textwrap.shorten(argument.name, 32),
                    "description": "[No Description]",
                    "type": _type,
                    "required": required
                }
                # if default:
                #     e["default"] = default
                _options.append(e)
            content["options"] += _options
        return content

    @staticmethod
    async def create_global_commands(client_id: int, token, *_commands):
        async with ClientSession() as session:
            for command in _commands:
                payload = command
                uri = payload.pop("uri", "/applications/{client_id}/commands").format(
                    client_id=str(client_id),
                    guild_id=str(payload.pop("guild_id", ""))
                )
                async with session.post(
                        BASE + "/applications/{}/commands".format(str(client_id)),
                        data=to_json(payload),
                        headers={
                            "Authorization": "Bot " + token,
                            "User-Agent": USERAGENT
                        }
                ) as response:
                    if response.status != 200:
                        raise HTTPException(
                            response,
                            await response.json()
                        )

    @staticmethod
    def _validate_schema(s):
        logging.warning("Schema validator is not fully implemented, only partial validation is available.")
        name = s["name"]
        description = s["description"]
        if len(name) > 32 or len(name) < 3:
            raise IndexError("Name \"{}\" is too long or short. Names must be between 3 and 32 characters.")
        if len(description) > 100 or len(description) < 1:
            raise IndexError("Description \"{}\" is too long or short. Description must be between 1 and 100 characters."
                             .format(description))
        for option in s["options"]:
            name = option["name"]
            description = option["description"]
            if len(name) > 32 or len(name) < 1:
                raise IndexError("Option name \"{}\" is too long or short. Names must be between 1 and 32 characters.")
            if len(description) > 100 or len(description) < 1:
                raise IndexError(
                    "Option description \"{}\" is too long or short. Description must be between 1 and 100 characters."
                    .format(description))
            if len(option.get("choices", [])) > 10:
                raise IndexError("Option {} has too many choices - There's a limit of 10.".format(name))
        return True


class SlashCommandContainer:
    """Simple container class that automatically generates and publishes slash commands."""

    def __init__(self, bot, exclude: List[Union[commands.Command, commands.Group]] = None):
        """
        creates the class

        :param bot: The bot instance (or something with a commands attribute)
        :param exclude: A list of commands, or groups, to exclude from slash commands.
        """
        self.bot = bot
        self.excluded = exclude or []
        self._publish = []

    def add_command(self, obj: Union[commands.Command, commands.Group], guild: discord.Guild = None,
                    auto_generate_schema: bool = True, **kwargs):
        """
        Adds a command to publish as a slash command.

        :param obj: The command/group function
        :param guild: If this command is guild-only, this is the guild to assign it to.
        :param auto_generate_schema: Whether to automatically generate the schema (payload data). If False, you must provide it in kwargs.
        """
        if obj in self._publish:
            raise IndexError("Command \"{}\" is already registered as a slash command.".format(repr(obj)))

        if auto_generate_schema:
            schema = SlashCommand._resolve_options(obj)
        else:
            schema = kwargs
            SlashCommand._validate_schema(schema)
        if guild:
            schema["guild_id"] = guild.id
            schema["uri"] = "/applications/{client_id}/guilds/{guild_id}/commands"
        self._publish.append(schema)
