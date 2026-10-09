import os
import discord
from discord import app_commands
from discord.ext import commands

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)

@bot.event
async def on_ready():
    print(f"Conectat ca {bot.user}")

    try:
        synced = await bot.tree.sync()
        print(f"Comenzi sincronizate: {len(synced)}")
    except Exception as e:
        print(e)

@bot.tree.command(
    name="elite",
    description="Verifică dacă botul funcționează"
)
async def elite(interaction: discord.Interaction):

    embed = discord.Embed(
        title="🇲🇩 Moldova Elite Bot",
        description="Bot Online ✅",
        color=0x00ff99
    )

    embed.add_field(
        name="Status",
        value="Conectat la Discord",
        inline=False
    )

    embed.add_field(
        name="Versiune",
        value="0.1",
        inline=False
    )

    await interaction.response.send_message(
        embed=embed
    )

bot.run(DISCORD_TOKEN)

