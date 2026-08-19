import logging
import os
import re
import json
from datetime import datetime, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv


load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "").strip()

if not DISCORD_TOKEN:
    print("DISCORD_TOKEN is missing. Add it to your .env file or Render Environment Variables.")
    raise SystemExit(1)

CONFIG_FILE = "config.json"


DEFAULT_CONFIG = {
    "guild_id": None,
    "ticket_category_id": None,
    "staff_role_id": None,
    "server_info_channel_id": None,

    "panel_title": "Support Ticket Center",
    "panel_description": (
        "Select a category from the dropdown menu below "
        "to open a private support ticket with our staff team."
    ),

    "welcome_message": (
        "Thank you for contacting the staff team.\n\n"
        "A staff member will respond shortly.\n\n"
        "Please provide as much relevant information as possible "
        "so we can assist you quickly."
    ),
}


def load_config():
    if not os.path.exists(CONFIG_FILE):
        save_config(DEFAULT_CONFIG.copy())
        return DEFAULT_CONFIG.copy()

    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as file:
            config = json.load(file)

        for key, value in DEFAULT_CONFIG.items():
            if key not in config:
                config[key] = value

        return config

    except Exception:
        logger.exception("Could not load config.json.")
        return DEFAULT_CONFIG.copy()


def save_config(config):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as file:
            json.dump(config, file, indent=4)

    except Exception:
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

        self.add_view(TicketPanelView())

        try:

            guild_id = config.get("guild_id")

            if guild_id:

                guild = discord.Object(id=int(guild_id))

                self.tree.copy_global_to(guild=guild)

                synced = await self.tree.sync(guild=guild)

                logger.info(
                    "Slash commands synchronized: %d command(s).",
                    len(synced),
                )

            else:

                synced = await self.tree.sync()

                logger.info(
                    "Global slash commands synchronized: %d command(s).",
                    len(synced),
                )

        except Exception:
            logger.exception(
                "Error while synchronizing slash commands."
            )

    async def on_ready(self):

        if self.user is None:
            return

        logger.info("========================================")
        logger.info("Bot is online!")
        logger.info("Bot username: %s", self.user)
        logger.info("Bot ID: %s", self.user.id)
        logger.info("Guild count: %d", len(self.guilds))
        logger.info("========================================")


bot = TicketBot()


# ============================================================
# HELPERS
# ============================================================

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


def get_ticket_type_label(ticket_type: str) -> str:

    labels = {
        "general": "General Support",
        "bug": "Bug Report",
        "report": "Player Report",
    }

    return labels.get(
        ticket_type,
        ticket_type.title(),
    )


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


def make_ticket_topic(
    user_id: int,
    ticket_type: str,
) -> str:

    return (
        f"ticket_owner={user_id};"
        f"ticket_type={ticket_type}"
    )


async def find_existing_ticket(
    guild: discord.Guild,
    user_id: int,
) -> Optional[discord.TextChannel]:

    category_id = config.get("ticket_category_id")

    if not category_id:
        return None

    category = guild.get_channel(
        int(category_id)
    )

    if not isinstance(
        category,
        discord.CategoryChannel,
    ):
        return None

    owner_marker = f"ticket_owner={user_id};"

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

        options = [

            discord.SelectOption(
                label="General Support",
                description="Open a ticket for general assistance.",
                value="general",
                emoji="🎫",
            ),

            discord.SelectOption(
                label="Bug Report",
                description="Report a bug or technical issue.",
                value="bug",
                emoji="🐛",
            ),

            discord.SelectOption(
                label="Player Report",
                description="Report a player to the staff team.",
                value="report",
                emoji="🚨",
            ),
        ]

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
                        "I do not have enough permissions to create "
                        "the ticket channel.\n\n"
                        "Make sure the bot has **Manage Channels** "
                        "permission."
                    ),
                ),
                ephemeral=True,
            )

        except discord.HTTPException as exc:

            logger.error(
                "Discord API error while creating ticket: %s",
                exc,
            )

            await interaction.followup.send(
                embed=make_error_embed(
                    "Discord API Error",
                    (
                        "Discord returned an error while creating "
                        "your ticket. Please try again."
                    ),
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
                        "Something went wrong while creating your "
                        "ticket."
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

    category_id = config.get(
        "ticket_category_id"
    )

    staff_role_id = config.get(
        "staff_role_id"
    )

    if not category_id:

        await interaction.followup.send(
            embed=make_error_embed(
                "Configuration Error",
                (
                    "No ticket category has been configured.\n\n"
                    "An administrator needs to run "
                    "`/config category`."
                ),
            ),
            ephemeral=True,
        )

        return

    if not staff_role_id:

        await interaction.followup.send(
            embed=make_error_embed(
                "Configuration Error",
                (
                    "No staff role has been configured.\n\n"
                    "An administrator needs to run "
                    "`/config staffrole`."
                ),
            ),
            ephemeral=True,
        )

        return

    category = guild.get_channel(
        int(category_id)
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
        int(staff_role_id)
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

    username = clean_username(
        interaction.user.name
    )

    prefixes = {
        "general": "support",
        "bug": "bug",
        "report": "report",
    }

    prefix = prefixes.get(
        ticket_type,
        "ticket",
    )

    channel_name = (
        f"{prefix}-{username}"
    )[:100]

    everyone_role = guild.default_role

    overwrites = {

        everyone_role: discord.PermissionOverwrite(
            view_channel=False,
        ),

        interaction.user: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            attach_files=True,
        ),

        staff_role: discord.PermissionOverwrite(
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
            "welcome_message",
            DEFAULT_CONFIG["welcome_message"],
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

    success_embed = discord.Embed(
        title="Ticket Created",
        description=(
            f"Your {ticket_label.lower()} ticket has been created:\n"
            f"{channel.mention}"
        ),
        color=discord.Color.green(),
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
# /setticketpanel
# ============================================================

@bot.tree.command(
    name="setticketpanel",
    description="Post the support ticket dropdown panel",
)
async def setticketpanel(
    interaction: discord.Interaction,
):

    if interaction.guild is None:

        await interaction.response.send_message(
            embed=make_error_embed(
                "Server Only",
                "This command can only be used inside a server.",
            ),
            ephemeral=True,
        )

        return

    if not interaction.user.guild_permissions.manage_guild:

        await interaction.response.send_message(
            embed=make_error_embed(
                "Permission Denied",
                "You need **Manage Server** permission to use this command.",
            ),
            ephemeral=True,
        )

        return

    panel_embed = discord.Embed(
        title=config.get(
            "panel_title",
            DEFAULT_CONFIG["panel_title"],
        ),
        description=config.get(
            "panel_description",
            DEFAULT_CONFIG["panel_description"],
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
            embed=discord.Embed(
                title="Ticket Panel Posted",
                description="The support ticket panel has been posted.",
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )

    except discord.Forbidden:

        if not interaction.response.is_done():

            await interaction.response.send_message(
                embed=make_error_embed(
                    "Permission Error",
                    "I cannot send messages in this channel.",
                ),
                ephemeral=True,
            )


# ============================================================
# /serverinfo
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
            embed=make_error_embed(
                "Server Only",
                "This command can only be used inside a server.",
            ),
            ephemeral=True,
        )

        return

    channel_id = config.get(
        "server_info_channel_id"
    )

    if not channel_id:

        await interaction.response.send_message(
            embed=make_error_embed(
                "Configuration Error",
                "No server information channel has been configured.",
            ),
            ephemeral=True,
        )

        return

    target_channel = interaction.guild.get_channel(
        int(channel_id)
    )

    if not isinstance(
        target_channel,
        discord.TextChannel,
    ):

        await interaction.response.send_message(
            embed=make_error_embed(
                "Channel Missing",
                "The configured server information channel could not be found.",
            ),
            ephemeral=True,
        )

        return

    guild = interaction.guild

    text_channel_count = len(
        guild.text_channels
    )

    voice_channel_count = len(
        guild.voice_channels
    )

    owner_text = (
        guild.owner.mention
        if guild.owner is not None
        else f"User ID: {guild.owner_id}"
    )

    created_timestamp = int(
        guild.created_at.timestamp()
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
        value=str(text_channel_count),
        inline=True,
    )

    info_embed.add_field(
        name="Voice Channels",
        value=str(voice_channel_count),
        inline=True,
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
            embed=discord.Embed(
                title="Server Information Sent",
                description=(
                    f"The server information was posted in "
                    f"{target_channel.mention}."
                ),
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )

    except discord.Forbidden:

        if not interaction.response.is_done():

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

class ConfigGroup(app_commands.Group):

    def __init__(self):

        super().__init__(
            name="config",
            description="Configure the Discord bot",
        )


config_group = ConfigGroup()


# ============================================================
# CONFIG PERMISSION CHECK
# ============================================================

async def check_admin(
    interaction: discord.Interaction,
) -> bool:

    if interaction.guild is None:

        await interaction.response.send_message(
            "This command can only be used inside a server.",
            ephemeral=True,
        )

        return False

    if not interaction.user.guild_permissions.administrator:

        await interaction.response.send_message(
            embed=make_error_embed(
                "Permission Denied",
                "You need **Administrator** permission to use this command.",
            ),
            ephemeral=True,
        )

        return False

    return True


# ============================================================
# /config category
# ============================================================

@config_group.command(
    name="category",
    description="Set the ticket category",
)
@app_commands.describe(
    category="The category where tickets should be created"
)
async def config_category(
    interaction: discord.Interaction,
    category: discord.CategoryChannel,
):

    if not await check_admin(interaction):
        return

    config["ticket_category_id"] = category.id

    if config.get("guild_id") is None:
        config["guild_id"] = interaction.guild.id

    save_config(config)

    await interaction.response.send_message(
        embed=discord.Embed(
            title="Ticket Category Updated",
            description=(
                f"New tickets will now be created in "
                f"{category.mention}."
            ),
            color=discord.Color.green(),
        ),
        ephemeral=True,
    )


# ============================================================
# /config staffrole
# ============================================================

@config_group.command(
    name="staffrole",
    description="Set the staff role",
)
@app_commands.describe(
    role="The role that can access tickets"
)
async def config_staffrole(
    interaction: discord.Interaction,
    role: discord.Role,
):

    if not await check_admin(interaction):
        return

    config["staff_role_id"] = role.id

    if config.get("guild_id") is None:
        config["guild_id"] = interaction.guild.id

    save_config(config)

    await interaction.response.send_message(
        embed=discord.Embed(
            title="Staff Role Updated",
            description=(
                f"Ticket staff role is now {role.mention}."
            ),
            color=discord.Color.green(),
        ),
        ephemeral=True,
    )


# ============================================================
# /config serverinfochannel
# ============================================================

@config_group.command(
    name="serverinfochannel",
    description="Set the server information channel",
)
@app_commands.describe(
    channel="The channel where server information is posted"
)
async def config_serverinfochannel(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
):

    if not await check_admin(interaction):
        return

    config["server_info_channel_id"] = channel.id

    if config.get("guild_id") is None:
        config["guild_id"] = interaction.guild.id

    save_config(config)

    await interaction.response.send_message(
        embed=discord.Embed(
            title="Server Info Channel Updated",
            description=(
                f"Server information will now be posted in "
                f"{channel.mention}."
            ),
            color=discord.Color.green(),
        ),
        ephemeral=True,
    )


# ============================================================
# /config paneltitle
# ============================================================

@config_group.command(
    name="paneltitle",
    description="Change the ticket panel title",
)
@app_commands.describe(
    title="New ticket panel title"
)
async def config_paneltitle(
    interaction: discord.Interaction,
    title: str,
):

    if not await check_admin(interaction):
        return

    config["panel_title"] = title[:256]

    save_config(config)

    await interaction.response.send_message(
        embed=discord.Embed(
            title="Panel Title Updated",
            description=f"New title: **{config['panel_title']}**",
            color=discord.Color.green(),
        ),
        ephemeral=True,
    )


# ============================================================
# /config paneldescription
# ============================================================

@config_group.command(
    name="paneldescription",
    description="Change the ticket panel description",
)
@app_commands.describe(
    description="New ticket panel description"
)
async def config_paneldescription(
    interaction: discord.Interaction,
    description: str,
):

    if not await check_admin(interaction):
        return

    config["panel_description"] = description[:4000]

    save_config(config)

    await interaction.response.send_message(
        embed=discord.Embed(
            title="Panel Description Updated",
            description="The ticket panel description has been updated.",
            color=discord.Color.green(),
        ),
        ephemeral=True,
    )


# ============================================================
# /config welcome
# ============================================================

@config_group.command(
    name="welcome",
    description="Change the ticket welcome message",
)
@app_commands.describe(
    message="New ticket welcome message"
)
async def config_welcome(
    interaction: discord.Interaction,
    message: str,
):

    if not await check_admin(interaction):
        return

    config["welcome_message"] = message[:4000]

    save_config(config)

    await interaction.response.send_message(
        embed=discord.Embed(
            title="Welcome Message Updated",
            description="The ticket welcome message has been updated.",
            color=discord.Color.green(),
        ),
        ephemeral=True,
    )


# ============================================================
# /config show
# ============================================================

@config_group.command(
    name="show",
    description="Show the current bot configuration",
)
async def config_show(
    interaction: discord.Interaction,
):

    if not await check_admin(interaction):
        return

    category_id = config.get("ticket_category_id")
    staff_role_id = config.get("staff_role_id")
    server_info_id = config.get("server_info_channel_id")

    category_text = (
        f"<#{category_id}>"
        if category_id
        else "Not configured"
    )

    staff_text = (
        f"<@&{staff_role_id}>"
        if staff_role_id
        else "Not configured"
    )

    server_info_text = (
        f"<#{server_info_id}>"
        if server_info_id
        else "Not configured"
    )

    embed = discord.Embed(
        title="Bot Configuration",
        color=discord.Color.blurple(),
    )

    embed.add_field(
        name="Ticket Category",
        value=category_text,
        inline=False,
    )

    embed.add_field(
        name="Staff Role",
        value=staff_text,
        inline=False,
    )

    embed.add_field(
        name="Server Info Channel",
        value=server_info_text,
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

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True,
    )


# ============================================================
# /config reload
# ============================================================

@config_group.command(
    name="reload",
    description="Reload configuration from config.json",
)
async def config_reload(
    interaction: discord.Interaction,
):

    if not await check_admin(interaction):
        return

    global config

    config = load_config()

    await interaction.response.send_message(
        embed=discord.Embed(
            title="Configuration Reloaded",
            description="The configuration has been reloaded.",
            color=discord.Color.green(),
        ),
        ephemeral=True,
    )


# ============================================================
# REGISTER CONFIG GROUP
# ============================================================

bot.tree.add_command(
    config_group
)


# ============================================================
# SLASH COMMAND ERROR HANDLER
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

    message = (
        "An unexpected error occurred while processing "
        "the command."
    )

    if isinstance(
        error,
        app_commands.CommandInvokeError,
    ):

        original = error.original

        if isinstance(
            original,
            discord.Forbidden,
        ):

            message = (
                "I do not have the required Discord permissions "
                "to complete this command."
            )

        elif isinstance(
            original,
            discord.HTTPException,
        ):

            message = (
                "Discord returned an API error while processing "
                "the command."
            )

    try:

        error_embed = make_error_embed(
            "Command Error",
            message,
        )

        if interaction.response.is_done():

            await interaction.followup.send(
                embed=error_embed,
                ephemeral=True,
            )

        else:

            await interaction.response.send_message(
                embed=error_embed,
                ephemeral=True,
            )

    except discord.HTTPException:

        logger.exception(
            "Could not send command error response."
        )


# ============================================================
# STARTUP VALIDATION
# ============================================================

def validate_configuration() -> bool:

    if not DISCORD_TOKEN:

        logger.critical(
            "DISCORD_TOKEN is missing."
        )

        return False

    return True


# ============================================================
# RUN BOT
# ============================================================

if __name__ == "__main__":

    if not validate_configuration():

        raise SystemExit(1)

    try:

        bot.run(
            DISCORD_TOKEN,
            reconnect=True,
        )

    except discord.LoginFailure:

        logger.critical(
            "Discord login failed. "
            "Make sure DISCORD_TOKEN is correct."
        )

    except KeyboardInterrupt:

        logger.info(
            "Bot stopped by user."
        )

    except Exception:

        logger.exception(
            "Fatal bot error."
        )
