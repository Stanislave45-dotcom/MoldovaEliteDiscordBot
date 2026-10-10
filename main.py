import os
import requests
import discord
from discord import app_commands
from discord.ext import commands

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CR_API_TOKEN = os.getenv("CR_API_TOKEN")

MOLDOVA_LOCATION_ID = 57000155

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
    description="Jucătorii Moldova 13800-14000"
)
async def elite(interaction: discord.Interaction):

    await interaction.response.defer()

    headers = {
        "Authorization": f"Bearer {CR_API_TOKEN}"
    }

    url = (
        "https://proxy.royaleapi.dev/v1/"
        f"locations/{MOLDOVA_LOCATION_ID}"
        "/rankings/players"
    )

    response = requests.get(
        url,
        headers=headers,
        timeout=30
    )

    if response.status_code != 200:

        await interaction.followup.send(
            "❌ Eroare API Clash Royale"
        )

        return

    data = response.json()

    players = data.get("items", [])

    elite_players = []

    for player in players:

        trophies = player.get(
            "trophies",
            0
        )

        if (
            trophies >= 13800
            and trophies <= 14000
        ):

            elite_players.append(
                f"👑 {player['name']} • {trophies}"
            )

    if len(elite_players) == 0:

        await interaction.followup.send(
            "Nu există jucători 13800-14000 momentan."
        )

        return

    embed = discord.Embed(
        title="🏆 Moldova Elite Club",
        description=
        "Jucători între 13800 și 14000 trofee",
        color=0xFFD700
    )

    embed.add_field(
        name="Elite",
        value="\n".join(elite_players[:20]),
        inline=False
    )

    await interaction.followup.send(
        embed=embed
    )


bot.run(DISCORD_TOKEN)
