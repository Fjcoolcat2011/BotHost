import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands


# ============================================================
# CONFIGURATION
# ============================================================

CONFIG_FILE = "config.json"

DISCORD_TOKEN = os.getenv("MTUzOTM5ODk4NjgwMzQ0OTg1Ng.GWmNqk.09N63dRw15TJjrZwmpJqb8ru_mFehuTlcxR8ec", "").strip()


DEFAULT_CONFIG = {
    "guild_id": 0,
    "ticket_category_id": 0,
    "staff_role_id": 0,
    "server_info_channel_id": 0,

    "panel_title": "Support Ticket Center",

    "panel_description": (
        "Select a category from the dropdown menu below to "
        "open a private support ticket with our staff team."
    ),

    "ticket_welcome_message": (
        "Thank you for contacting the staff team.\n\n"
        "A staff member will respond shortly.\n\n"
        "Please provide as much relevant information as "
        "possible so we can assist you quickly."
    ),

    "ticket_types": {
        "general": {
            "label": "General Support",
            "description": "Open a ticket for general assistance.",
            "emoji": "🎫",
            "prefix": "support",
        },
        "bug": {
            "label": "Bug Report",
            "description": "Report a bug or technical issue.",
            "emoji": "🐛",
            "prefix": "bug",
        },
        "report": {
            "label": "Player Report",
            "description": "Report a player to the staff team.",
            "emoji": "🚨",
            "prefix": "report",
        },
    },
}


def load_config():
    if not os.path.exists(CONFIG_FILE):
        save_config(DEFAULT_CONFIG)

    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as file:
            config = json.load(file)

    except (json.JSONDecodeError, OSError):
        config = DEFAULT_CONFIG.copy()
        save_config(config)

    # Make sure new settings get added automatically.
    changed = False

    for key, value in DEFAULT_CONFIG.items():
        if key not in config:
            config[key] = value
            changed = True

    if changed:
        save_config(config)

    return config


def save_config(config):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as file:
            json.dump(
                config,
                file,
                indent=4,
                ensure_ascii=False,
            )
    except OSError:
        logger.exception("Could not save config.json.")


config = load_config()


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger("discord-ticket-bot")


# ============================================================
# HELPERS
# ============================================================

def get_config_id(name: str) -> Optional[int]:
    value = config.get(name, 0)

    try:
        value = int(value)
    except (TypeError, ValueError):
        return None

    if value <= 0:
        return None

    return value


def clean_username(username: str) -> str:
    username = username.lower()

    username = re.sub(
        r"[^a-z0-9_-]",
        "-",
        username,
    )

    username = re.sub(
        r"-+",
        "-",
        username,
    )

    username = username.strip("-_")

    if not username:
        username = "user"

    return username[:70]


def make_error_embed(
    title: str,
    description: str,
) -> discord.Embed:

    embed = discord.Embed(
        title=title,
        description=description,
        color=discord.Color.red(),
        timestamp=datetime.now(timezone.utc),
    )

    embed.set_footer(
        text="Powered by Python Discord Bot"
    )

    return embed


def make_success_embed(
    title: str,
    description: str,
) -> discord.Embed:

    embed = discord.Embed(
        title=title,
        description=description,
        color=discord.Color.green(),
        timestamp=datetime.now(timezone.utc),
    )

    embed.set_footer(
        text="Powered by Python Discord Bot"
    )

    return embed


def make_ticket_topic(
    user_id: int,
    ticket_type: str,
) -> str:

    return (
        f"ticket_owner={user_id};"
        f"ticket_type={ticket_type}"
    )


def get_ticket_type_label(ticket_type: str) -> str:
    ticket = config["ticket_types"].get(ticket_type)

    if ticket:
        return ticket.get(
            "label",
            ticket_type.title(),
        )

    return ticket_type.title()


def is_admin(interaction: discord.Interaction) -> bool:
    if interaction.guild is None:
        return False

    return interaction.user.guild_permissions.administrator


# ============================================================
# INTENTS
# ============================================================

intents = discord.Intents.default()
intents.guilds = True


# ============================================================
# BOT
# ============================================================

class TicketBot(commands.Bot):

    def __init__(self):

        super().__init__(
            command_prefix="!",
            intents=intents,
            reconnect=True,
        )

    async def setup_hook(self):

        self.add_view(
            TicketPanelView()
        )

        guild_id = get_config_id("guild_id")

        try:

            if guild_id:

                guild = discord.Object(
                    id=guild_id
                )

                self.tree.copy_global_to(
                    guild=guild
                )

                synced = await self.tree.sync(
                    guild=guild
                )

                logger.info(
                    "Synced %d command(s) to guild %s.",
                    len(synced),
                    guild_id,
                )

            else:

                synced = await self.tree.sync()

                logger.info(
                    "Synced %d global command(s).",
                    len(synced),
                )

        except Exception:
            logger.exception(
                "Could not synchronize slash commands."
            )

    async def on_ready(self):

        if self.user is None:
            return

        logger.info(
            "Bot is online!"
        )

        logger.info(
            "Bot username: %s",
            self.user,
        )

        logger.info(
            "Bot ID: %s",
            self.user.id,
        )

        logger.info(
            "Guild count: %d",
            len(self.guilds),
        )


bot = TicketBot()


# ============================================================
# FIND EXISTING TICKET
# ============================================================

async def find_existing_ticket(
    guild: discord.Guild,
    user_id: int,
) -> Optional[discord.TextChannel]:

    category_id = get_config_id(
        "ticket_category_id"
    )

    if category_id is None:
        return None

    category = guild.get_channel(
        category_id
    )

    if not isinstance(
        category,
        discord.CategoryChannel,
    ):
        return None

    owner_marker = (
        f"ticket_owner={user_id};"
    )

    for channel in category.text_channels:

        if (
            channel.topic
            and owner_marker in channel.topic
        ):
            return channel

    return None


# ============================================================
# TICKET DROPDOWN
# ============================================================

class TicketSelect(discord.ui.Select):

    def __init__(self):

        options = []

        ticket_types = config.get(
            "ticket_types",
            {},
        )

        for value, data in ticket_types.items():

            options.append(
                discord.SelectOption(
                    label=data.get(
                        "label",
                        value.title(),
                    )[:100],

                    description=data.get(
                        "description",
                        "Open a support ticket.",
                    )[:100],

                    value=value,

                    emoji=data.get(
                        "emoji",
                        "🎫",
                    ),
                )
            )

        # Discord requires at least one option.
        if not options:

            options.append(
                discord.SelectOption(
                    label="Support",
                    description="Open a support ticket.",
                    value="general",
                    emoji="🎫",
                )
            )

        # Discord allows a maximum of 25 options.
        options = options[:25]

        super().__init__(
            placeholder="Select a ticket category...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="support_ticket_select",
        )

    async def callback(
        self,
        interaction: discord.Interaction,
    ):

        if interaction.guild is None:

            await interaction.response.send_message(
                embed=make_error_embed(
                    "Server Only",
                    "Tickets can only be created inside a server.",
                ),
                ephemeral=True,
            )

            return

        await interaction.response.defer(
            ephemeral=True
        )

        ticket_type = self.values[0]

        try:

            await create_ticket(
                interaction,
                ticket_type,
            )

        except discord.Forbidden:

            logger.warning(
                "Missing permissions while creating ticket."
            )

            await interaction.followup.send(
                embed=make_error_embed(
                    "Permission Error",
                    (
                        "I do not have enough permissions to "
                        "create the ticket channel.\n\n"
                        "Make sure the bot has **Manage Channels** "
                        "permission."
                    ),
                ),
                ephemeral=True,
            )

        except discord.HTTPException as exc:

            logger.error(
                "Discord API error: %s",
                exc,
            )

            await interaction.followup.send(
                embed=make_error_embed(
                    "Discord API Error",
                    "Discord returned an error while creating your ticket.",
                ),
                ephemeral=True,
            )

        except Exception:

            logger.exception(
                "Unexpected ticket creation error."
            )

            await interaction.followup.send(
                embed=make_error_embed(
                    "Ticket Creation Failed",
                    (
                        "Something went wrong while creating "
                        "your ticket."
                    ),
                ),
                ephemeral=True,
            )


class TicketPanelView(discord.ui.View):

    def __init__(self):

        super().__init__(
            timeout=None
        )

        self.add_item(
            TicketSelect()
        )


# ============================================================
# CREATE TICKET
# ============================================================

async def create_ticket(
    interaction: discord.Interaction,
    ticket_type: str,
):

    guild = interaction.guild

    if guild is None:
        return

    category_id = get_config_id(
        "ticket_category_id"
    )

    staff_role_id = get_config_id(
        "staff_role_id"
    )

    if category_id is None:

        await interaction.followup.send(
            embed=make_error_embed(
                "Configuration Error",
                (
                    "No ticket category has been configured.\n\n"
                    "An administrator should use "
                    "`/config category`."
                ),
            ),
            ephemeral=True,
        )

        return

    if staff_role_id is None:

        await interaction.followup.send(
            embed=make_error_embed(
                "Configuration Error",
                (
                    "No staff role has been configured.\n\n"
                    "An administrator should use "
                    "`/config staffrole`."
                ),
            ),
            ephemeral=True,
        )

        return

    category = guild.get_channel(
        category_id
    )

    if not isinstance(
        category,
        discord.CategoryChannel,
    ):

        await interaction.followup.send(
            embed=make_error_embed(
                "Ticket Category Missing",
                "The configured ticket category could not be found.",
            ),
            ephemeral=True,
        )

        return

    staff_role = guild.get_role(
        staff_role_id
    )

    if staff_role is None:

        await interaction.followup.send(
            embed=make_error_embed(
                "Staff Role Missing",
                "The configured staff role could not be found.",
            ),
            ephemeral=True,
        )

        return

    existing_ticket = await find_existing_ticket(
        guild,
        interaction.user.id,
    )

    if existing_ticket is not None:

        await interaction.followup.send(
            embed=make_error_embed(
                "Ticket Already Open",
                (
                    f"You already have an open ticket:\n"
                    f"{existing_ticket.mention}\n\n"
                    "Please use your existing ticket."
                ),
            ),
            ephemeral=True,
        )

        return

    ticket_data = config["ticket_types"].get(
        ticket_type
    )

    if ticket_data is None:

        ticket_data = {
            "label": "Support",
            "prefix": "ticket",
        }

    username = clean_username(
        interaction.user.name
    )

    prefix = ticket_data.get(
        "prefix",
        "ticket",
    )

    channel_name = (
        f"{prefix}-{username}"
    )[:100]

    everyone_role = guild.default_role

    overwrites = {

        everyone_role:
            discord.PermissionOverwrite(
                view_channel=False,
            ),

        interaction.user:
            discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
            ),

        staff_role:
            discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
                manage_messages=True,
            ),
    }

    channel = await guild.create_text_channel(
        name=channel_name,
        category=category,
        overwrites=overwrites,
        topic=make_ticket_topic(
            interaction.user.id,
            ticket_type,
        ),
        reason=(
            f"Support ticket created by "
            f"{interaction.user}"
        ),
    )

    ticket_label = get_ticket_type_label(
        ticket_type
    )

    welcome_embed = discord.Embed(
        title="Support Ticket Created",
        description=config.get(
            "ticket_welcome_message",
            "Thank you for contacting the staff team.",
        ),
        color=discord.Color.cyan(),
        timestamp=datetime.now(timezone.utc),
    )

    welcome_embed.add_field(
        name="Created By",
        value=interaction.user.mention,
        inline=True,
    )

    welcome_embed.add_field(
        name="Ticket Type",
        value=ticket_label,
        inline=True,
    )

    welcome_embed.set_footer(
        text="Powered by Python Discord Bot"
    )

    try:

        await channel.send(
            content=(
                f"{interaction.user.mention} "
                f"{staff_role.mention}"
            ),
            embed=welcome_embed,
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=True,
            ),
        )

    except discord.HTTPException:

        logger.exception(
            "Could not send ticket welcome message."
        )

    success_embed = make_success_embed(
        "Ticket Created",
        (
            f"Your {ticket_label.lower()} ticket has been created:\n"
            f"{channel.mention}"
        ),
    )

    await interaction.followup.send(
        embed=success_embed,
        ephemeral=True,
    )

    logger.info(
        "Created ticket #%s for %s.",
        channel.id,
        interaction.user,
    )


# ============================================================
# /SETTICKETPANEL
# ============================================================

@bot.tree.command(
    name="setticketpanel",
    description="Post the support ticket panel",
)
async def setticketpanel(
    interaction: discord.Interaction,
):

    if interaction.guild is None:

        await interaction.response.send_message(
            "This command can only be used in a server.",
            ephemeral=True,
        )

        return

    if not is_admin(interaction):

        await interaction.response.send_message(
            "You need Administrator permission to use this command.",
            ephemeral=True,
        )

        return

    panel_embed = discord.Embed(
        title=config.get(
            "panel_title",
            "Support Ticket Center",
        ),
        description=config.get(
            "panel_description",
            "Open a support ticket below.",
        ),
        color=discord.Color.cyan(),
    )

    panel_embed.set_footer(
        text="Powered by Python Discord Bot"
    )

    try:

        await interaction.channel.send(
            embed=panel_embed,
            view=TicketPanelView(),
        )

        await interaction.response.send_message(
            embed=make_success_embed(
                "Ticket Panel Posted",
                "The support ticket panel has been posted.",
            ),
            ephemeral=True,
        )

    except discord.Forbidden:

        await interaction.response.send_message(
            embed=make_error_embed(
                "Permission Error",
                "I cannot send messages in this channel.",
            ),
            ephemeral=True,
        )


# ============================================================
# /SERVERINFO
# ============================================================

@bot.tree.command(
    name="serverinfo",
    description="Display information about the server",
)
async def serverinfo(
    interaction: discord.Interaction,
):

    if interaction.guild is None:

        await interaction.response.send_message(
            "This command can only be used in a server.",
            ephemeral=True,
        )

        return

    channel_id = get_config_id(
        "server_info_channel_id"
    )

    if channel_id is None:

        await interaction.response.send_message(
            embed=make_error_embed(
                "Configuration Error",
                (
                    "No server information channel has been "
                    "configured.\n\n"
                    "Use `/config serverinfochannel`."
                ),
            ),
            ephemeral=True,
        )

        return

    target_channel = interaction.guild.get_channel(
        channel_id
    )

    if not isinstance(
        target_channel,
        discord.TextChannel,
    ):

        await interaction.response.send_message(
            embed=make_error_embed(
                "Channel Missing",
                "The configured channel could not be found.",
            ),
            ephemeral=True,
        )

        return

    guild = interaction.guild

    owner_text = (
        guild.owner.mention
        if guild.owner is not None
        else f"User ID: {guild.owner_id}"
    )

    info_embed = discord.Embed(
        title="Server Information",
        color=discord.Color.green(),
        timestamp=datetime.now(timezone.utc),
    )

    info_embed.add_field(
        name="Server Name",
        value=guild.name,
        inline=True,
    )

    info_embed.add_field(
        name="Server ID",
        value=str(guild.id),
        inline=True,
    )

    info_embed.add_field(
        name="Member Count",
        value=str(guild.member_count),
        inline=True,
    )

    info_embed.add_field(
        name="Server Owner",
        value=owner_text,
        inline=True,
    )

    info_embed.add_field(
        name="Text Channels",
        value=str(len(guild.text_channels)),
        inline=True,
    )

    info_embed.add_field(
        name="Voice Channels",
        value=str(len(guild.voice_channels)),
        inline=True,
    )

    created_timestamp = int(
        guild.created_at.timestamp()
    )

    info_embed.add_field(
        name="Server Created",
        value=f"<t:{created_timestamp}:F>",
        inline=False,
    )

    info_embed.set_footer(
        text="Powered by Python Discord Bot"
    )

    try:

        await target_channel.send(
            embed=info_embed
        )

        await interaction.response.send_message(
            embed=make_success_embed(
                "Server Information Sent",
                (
                    f"The information was posted in "
                    f"{target_channel.mention}."
                ),
            ),
            ephemeral=True,
        )

    except discord.Forbidden:

        await interaction.response.send_message(
            embed=make_error_embed(
                "Permission Error",
                f"I cannot send messages in {target_channel.mention}.",
            ),
            ephemeral=True,
        )


# ============================================================
# CONFIG GROUP
# ============================================================

config_group = app_commands.Group(
    name="config",
    description="Configure the bot",
)


# ============================================================
# /CONFIG SHOW
# ============================================================

@config_group.command(
    name="show",
    description="Show the current bot configuration",
)
async def config_show(
    interaction: discord.Interaction,
):

    if not is_admin(interaction):

        await interaction.response.send_message(
            "You need Administrator permission to use this.",
            ephemeral=True,
        )

        return

    guild = interaction.guild

    category_id = get_config_id(
        "ticket_category_id"
    )

    staff_role_id = get_config_id(
        "staff_role_id"
    )

    server_info_id = get_config_id(
        "server_info_channel_id"
    )

    category = (
        guild.get_channel(category_id).mention
        if guild and category_id
        and guild.get_channel(category_id)
        else "Not configured"
    )

    staff_role = (
        guild.get_role(staff_role_id).mention
        if guild and staff_role_id
        and guild.get_role(staff_role_id)
        else "Not configured"
    )

    server_info = (
        guild.get_channel(server_info_id).mention
        if guild and server_info_id
        and guild.get_channel(server_info_id)
        else "Not configured"
    )

    ticket_types = config.get(
        "ticket_types",
        {},
    )

    ticket_list = "\n".join(
        f"• `{key}` — {data.get('label', key)}"
        for key, data in ticket_types.items()
    )

    embed = discord.Embed(
        title="Bot Configuration",
        color=discord.Color.blue(),
    )

    embed.add_field(
        name="Ticket Category",
        value=category,
        inline=False,
    )

    embed.add_field(
        name="Staff Role",
        value=staff_role,
        inline=False,
    )

    embed.add_field(
        name="Server Info Channel",
        value=server_info,
        inline=False,
    )

    embed.add_field(
        name="Panel Title",
        value=config.get(
            "panel_title",
            "Not configured",
        ),
        inline=False,
    )

    embed.add_field(
        name="Ticket Types",
        value=ticket_list or "None",
        inline=False,
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True,
    )


# ============================================================
# /CONFIG CATEGORY
# ============================================================

@config_group.command(
    name="category",
    description="Set the ticket category",
)
@app_commands.describe(
    category="The Discord category where tickets will be created",
)
async def config_category(
    interaction: discord.Interaction,
    category: discord.CategoryChannel,
):

    if not is_admin(interaction):

        await interaction.response.send_message(
            "You need Administrator permission to use this.",
            ephemeral=True,
        )

        return

    config["ticket_category_id"] = category.id
    save_config(config)

    await interaction.response.send_message(
        embed=make_success_embed(
            "Ticket Category Updated",
            f"Tickets will now be created in {category.mention}.",
        ),
        ephemeral=True,
    )


# ============================================================
# /CONFIG STAFFROLE
# ============================================================

@config_group.command(
    name="staffrole",
    description="Set the staff role",
)
@app_commands.describe(
    role="The role that can access tickets",
)
async def config_staffrole(
    interaction: discord.Interaction,
    role: discord.Role,
):

    if not is_admin(interaction):

        await interaction.response.send_message(
            "You need Administrator permission to use this.",
            ephemeral=True,
        )

        return

    config["staff_role_id"] = role.id
    save_config(config)

    await interaction.response.send_message(
        embed=make_success_embed(
            "Staff Role Updated",
            f"The ticket staff role is now {role.mention}.",
        ),
        ephemeral=True,
    )


# ============================================================
# /CONFIG SERVERINFOCHANNEL
# ============================================================

@config_group.command(
    name="serverinfochannel",
    description="Set the server information channel",
)
@app_commands.describe(
    channel="Channel where /serverinfo posts information",
)
async def config_serverinfochannel(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
):

    if not is_admin(interaction):

        await interaction.response.send_message(
            "You need Administrator permission to use this.",
            ephemeral=True,
        )

        return

    config["server_info_channel_id"] = channel.id
    save_config(config)

    await interaction.response.send_message(
        embed=make_success_embed(
            "Server Info Channel Updated",
            f"Server information will be posted in {channel.mention}.",
        ),
        ephemeral=True,
    )


# ============================================================
# /CONFIG PANELTITLE
# ============================================================

@config_group.command(
    name="paneltitle",
    description="Change the ticket panel title",
)
@app_commands.describe(
    title="New ticket panel title",
)
async def config_paneltitle(
    interaction: discord.Interaction,
    title: str,
):

    if not is_admin(interaction):

        await interaction.response.send_message(
            "You need Administrator permission to use this.",
            ephemeral=True,
        )

        return

    title = title[:256]

    config["panel_title"] = title
    save_config(config)

    await interaction.response.send_message(
        embed=make_success_embed(
            "Panel Title Updated",
            f"New title: **{title}**",
        ),
        ephemeral=True,
    )


# ============================================================
# /CONFIG PANELDESCRIPTION
# ============================================================

@config_group.command(
    name="paneldescription",
    description="Change the ticket panel description",
)
@app_commands.describe(
    description="New ticket panel description",
)
async def config_paneldescription(
    interaction: discord.Interaction,
    description: str,
):

    if not is_admin(interaction):

        await interaction.response.send_message(
            "You need Administrator permission to use this.",
            ephemeral=True,
        )

        return

    description = description[:4096]

    config["panel_description"] = description
    save_config(config)

    await interaction.response.send_message(
        embed=make_success_embed(
            "Panel Description Updated",
            "The ticket panel description has been updated.",
        ),
        ephemeral=True,
    )


# ============================================================
# /CONFIG WELCOME
# ============================================================

@config_group.command(
    name="welcome",
    description="Change the ticket welcome message",
)
@app_commands.describe(
    message="Message shown inside newly created tickets",
)
async def config_welcome(
    interaction: discord.Interaction,
    message: str,
):

    if not is_admin(interaction):

        await interaction.response.send_message(
            "You need Administrator permission to use this.",
            ephemeral=True,
        )

        return

    config["ticket_welcome_message"] = message[:4000]
    save_config(config)

    await interaction.response.send_message(
        embed=make_success_embed(
            "Welcome Message Updated",
            "New tickets will use the updated welcome message.",
        ),
        ephemeral=True,
    )


# ============================================================
# /CONFIG RELOAD
# ============================================================

@config_group.command(
    name="reload",
    description="Reload configuration from config.json",
)
async def config_reload(
    interaction: discord.Interaction,
):

    if not is_admin(interaction):

        await interaction.response.send_message(
            "You need Administrator permission to use this.",
            ephemeral=True,
        )

        return

    global config

    config = load_config()

    await interaction.response.send_message(
        embed=make_success_embed(
            "Configuration Reloaded",
            "The configuration has been reloaded.",
        ),
        ephemeral=True,
    )


# ============================================================
# ADD CONFIG GROUP
# ============================================================

bot.tree.add_command(
    config_group
)


# ============================================================
# ERROR HANDLER
# ============================================================

@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError,
):

    logger.error(
        "Application command error: %s",
        error,
        exc_info=True,
    )

    if interaction.response.is_done():
        try:
            await interaction.followup.send(
                embed=make_error_embed(
                    "Command Error",
                    "Something went wrong while processing the command.",
                ),
                ephemeral=True,
            )
        except discord.HTTPException:
            pass

    else:

        try:

            await interaction.response.send_message(
                embed=make_error_embed(
                    "Command Error",
                    "Something went wrong while processing the command.",
                ),
                ephemeral=True,
            )

        except discord.HTTPException:
            pass


# ============================================================
# START BOT
# ============================================================

if not DISCORD_TOKEN:

    raise SystemExit(
        "DISCORD_TOKEN is missing. "
        "Add it to Render Environment Variables."
    )


try:

    bot.run(
        DISCORD_TOKEN,
        reconnect=True,
    )

except discord.LoginFailure:

    logger.critical(
        "Discord login failed. Check your DISCORD_TOKEN."
    )

except KeyboardInterrupt:

    logger.info(
        "Bot stopped."
    )

except Exception:

    logger.exception(
        "Fatal bot error."
    )
