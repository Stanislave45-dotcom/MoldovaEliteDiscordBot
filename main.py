import asyncio
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import quote

import discord
import requests
from discord.ext import commands


# =====================================
# VARIABILE RAILWAY
# =====================================

DISCORD_TOKEN = os.getenv(
    "DISCORD_TOKEN",
    ""
).strip()

CR_API_TOKEN = os.getenv(
    "CR_API_TOKEN",
    ""
).strip()


# =====================================
# CONFIGURARE
# =====================================

MOLDOVA_LOCATION_ID = 57000155

API_BASE = "https://proxy.royaleapi.dev/v1"

MOLDOVA_DATABASE = "moldova_players.json"
ELITE_DATABASE = "elite_players.json"

MIN_ELITE_TROPHIES = 13800
MAX_ELITE_TROPHIES = 14000

MAX_CLANS = 100

# Câte clanuri se verifică simultan
MAX_WORKERS = 6

HEADERS = {
    "Authorization": f"Bearer {CR_API_TOKEN}",
    "Accept": "application/json"
}


# =====================================
# CONFIGURARE DISCORD
# =====================================

intents = discord.Intents.default()

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)

scan_lock = asyncio.Lock()
commands_synced = False


# =====================================
# BAZA DE DATE JSON
# =====================================

def load_database(file_name):
    if not os.path.exists(file_name):
        return {}

    try:
        with open(
            file_name,
            "r",
            encoding="utf-8"
        ) as file:
            data = json.load(file)

        if isinstance(data, dict):
            return data

        # Acceptă și fișiere create inițial cu []
        if isinstance(data, list):
            database = {}

            for player in data:
                if not isinstance(player, dict):
                    continue

                player_tag = player.get("tag")

                if player_tag:
                    database[player_tag] = player

            return database

        return {}

    except (
        OSError,
        json.JSONDecodeError
    ) as error:
        print(
            f"Eroare la citirea {file_name}:",
            repr(error)
        )

        return {}


def save_database(file_name, database):
    temporary_file = file_name + ".tmp"

    try:
        with open(
            temporary_file,
            "w",
            encoding="utf-8"
        ) as file:
            json.dump(
                database,
                file,
                ensure_ascii=False,
                indent=2
            )

        os.replace(
            temporary_file,
            file_name
        )

        print(
            f"Baza {file_name} a fost salvată."
        )

        return True

    except OSError as error:
        print(
            f"Eroare la salvarea {file_name}:",
            repr(error)
        )

        return False


# =====================================
# TOP 100 CLANURI MOLDOVA
# =====================================

def get_top_moldova_clans():
    url = (
        f"{API_BASE}/locations/"
        f"{MOLDOVA_LOCATION_ID}/rankings/clans"
    )

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            params={
                "limit": MAX_CLANS
            },
            timeout=45
        )

        print(
            "Clasamentul clanurilor:",
            response.status_code
        )

        if response.status_code != 200:
            print(
                "Răspuns API:",
                response.text[:1000]
            )

            return None, (
                f"API Clash Royale a răspuns "
                f"cu HTTP {response.status_code}."
            )

        data = response.json()
        clans = data.get("items", [])

        if not clans:
            return None, (
                "API-ul nu a returnat clanuri "
                "pentru Moldova."
            )

        return clans[:MAX_CLANS], None

    except requests.RequestException as error:
        print(
            "Eroare clasament:",
            repr(error)
        )

        return None, str(error)


# =====================================
# MEMBRII UNUI CLAN
# =====================================

def get_clan_players(clan):
    clan_tag = clan.get("tag")

    if not clan_tag:
        return {
            "success": False,
            "clan_tag": "necunoscut",
            "players": [],
            "error": "Clan fără tag."
        }

    encoded_tag = quote(
        clan_tag,
        safe=""
    )

    url = (
        f"{API_BASE}/clans/"
        f"{encoded_tag}"
    )

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=45
        )

        if response.status_code != 200:
            print(
                "Eroare clan:",
                clan_tag,
                response.status_code,
                response.text[:300]
            )

            return {
                "success": False,
                "clan_tag": clan_tag,
                "players": [],
                "error": (
                    f"HTTP {response.status_code}"
                )
            }

        clan_data = response.json()

        clan_name = clan_data.get(
            "name",
            clan.get(
                "name",
                "Clan necunoscut"
            )
        )

        clan_rank = clan.get(
            "rank",
            0
        )

        members = clan_data.get(
            "memberList",
            []
        )

        players = []

        for member in members:
            player_tag = member.get("tag")

            if not player_tag:
                continue

            players.append({
                "tag": player_tag,
                "name": member.get(
                    "name",
                    "Jucător necunoscut"
                ),
                "trophies": int(
                    member.get(
                        "trophies",
                        0
                    )
                    or 0
                ),
                "role": member.get(
                    "role",
                    "member"
                ),
                "clan_tag": clan_tag,
                "clan_name": clan_name,
                "clan_rank": clan_rank
            })

        return {
            "success": True,
            "clan_tag": clan_tag,
            "players": players,
            "error": None
        }

    except requests.RequestException as error:
        print(
            "Excepție la clan:",
            clan_tag,
            repr(error)
        )

        return {
            "success": False,
            "clan_tag": clan_tag,
            "players": [],
            "error": str(error)
        }


# =====================================
# SCANARE MOLDOVA
# =====================================

def scan_moldova_sync():
    started_at = time.time()

    clans, ranking_error = (
        get_top_moldova_clans()
    )

    if clans is None:
        return {
            "success": False,
            "error": ranking_error
        }

    print(
        "Clanuri găsite:",
        len(clans)
    )

    # Scanăm mai multe clanuri simultan
    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:
        results = list(
            executor.map(
                get_clan_players,
                clans
            )
        )

    successful_results = []
    failed_results = []

    for result in results:
        if result["success"]:
            successful_results.append(result)
        else:
            failed_results.append(result)

    current_players = {}

    scan_time = datetime.now(
        timezone.utc
    ).isoformat()

    for result in successful_results:
        for player in result["players"\]:
            player_tag = player["tag"]

            player["last_seen"] = scan_time
            player["source"] = (
                "top_100_moldova_clans"
            )

            current_players[player_tag] = (
                player
            )

    old_database = load_database(
        MOLDOVA_DATABASE
    )

    old_tags = set(
        old_database.keys()
    )

    current_tags = set(
        current_players.keys()
    )

    new_player_tags = (
        current_tags - old_tags
    )

    merged_database = dict(
        old_database
    )

    # Adaugă sau actualizează jucătorii
    for player_tag, player in (
        current_players.items()
    ):
        old_player = merged_database.get(
            player_tag,
            {}
        )

        player["first_seen"] = (
            old_player.get("first_seen")
            or scan_time
        )

        old_record = int(
            old_player.get(
                "highest_trophies",
                0
            )
            or 0
        )

        current_trophies = int(
            player.get(
                "trophies",
                0
            )
            or 0
        )

        player["highest_trophies"] = max(
            old_record,
            current_trophies
        )

        merged_database[player_tag] = player

    # Creează baza Elite
    elite_database = {}

    for player_tag, player in (
        merged_database.items()
    ):
        trophies = int(
            player.get(
                "trophies",
                0
            )
            or 0
        )

        if (
            MIN_ELITE_TROPHIES
            <= trophies
            <= MAX_ELITE_TROPHIES
        ):
            elite_database[player_tag] = (
                player
            )

    moldova_saved = save_database(
        MOLDOVA_DATABASE,
        merged_database
    )

    elite_saved = save_database(
        ELITE_DATABASE,
        elite_database
    )

    failed_tags = [
        result["clan_tag"]
        for result in failed_results
    ]

    if failed_tags:
        print(
            "Clanuri cu eroare:",
            ", ".join(failed_tags)
        )

    duration = round(
        time.time() - started_at,
        1
    )

    if not moldova_saved or not elite_saved:
        return {
            "success": False,
            "error": (
                "Fișierele bazei de date "
                "nu au putut fi salvate."
            )
        }

    return {
        "success": True,
        "error": None,
        "clans_found": len(clans),
        "clans_scanned": len(
            successful_results
        ),
        "failed_clans": len(
            failed_results
        ),
        "players_current": len(
            current_players
        ),
        "players_total": len(
            merged_database
        ),
        "new_players": len(
            new_player_tags
        ),
        "elite_total": len(
            elite_database
        ),
        "duration": duration
    }


# =====================================
# BOT PORNIT
# =====================================

@bot.event
async def on_ready():
    global commands_synced

    print(
        f"Conectat ca {bot.user}"
    )

    if commands_synced:
        return

    try:
        synced = await bot.tree.sync()

        commands_synced = True

        print(
            "Comenzi sincronizate:",
            len(synced)
        )

        for command in synced:
            print(
                "Comandă:",
                command.name
            )

    except Exception as error:
        print(
            "Eroare sincronizare comenzi:",
            repr(error)
        )


# =====================================
# COMANDA /SCANMD
# =====================================

@bot.tree.command(
    name="scanmd",
    description="Scanează Top 100 clanuri Moldova"
)
async def scanmd(
    interaction: discord.Interaction
):
    # Nu permitem două scanări simultan
    if scan_lock.locked():
        await interaction.response.send_message(
            "⏳ O scanare Moldova este deja "
            "în curs.",
            ephemeral=True
        )

        return

    # Confirmă imediat comanda către Discord
    await interaction.response.defer(
        thinking=True
    )

    async with scan_lock:
        try:
            result = await asyncio.to_thread(
                scan_moldova_sync
            )

        except Exception as error:
            print(
                "Eroare /scanmd:",
                repr(error)
            )

            await interaction.followup.send(
                "❌ Scanarea a eșuat.\n"
                f"`{type(error).__name__}: "
                f"{str(error)[:500]}`"
            )

            return

    if not result.get("success"):
        embed = discord.Embed(
            title="❌ Scanare nereușită",
            description=(
                result.get("error")
                or "Eroare necunoscută."
            ),
            color=0xE74C3C
        )

        await interaction.followup.send(
            embed=embed
        )

        return

    embed = discord.Embed(
        title="🇲🇩 Scanare Moldova terminată",
        description=(
            "Baza de date a fost actualizată."
        ),
        color=0x2ECC71
    )

    embed.add_field(
        name="🏰 Clanuri găsite",
        value=str(
            result["clans_found"]
        ),
        inline=True
    )

    embed.add_field(
        name="✅ Clanuri scanate",
        value=str(
            result["clans_scanned"]
        ),
        inline=True
    )

    embed.add_field(
        name="⚠️ Clanuri cu eroare",
        value=str(
            result["failed_clans"]
        ),
        inline=True
    )

    embed.add_field(
        name="👥 Jucători în scanare",
        value=str(
            result["players_current"]
        ),
        inline=True
    )

    embed.add_field(
        name="🆕 Jucători noi",
        value=str(
            result["new_players"]
        ),
        inline=True
    )

    embed.add_field(
        name="🗃️ Total baza Moldova",
        value=str(
            result["players_total"]
        ),
        inline=True
    )

    embed.add_field(
        name="🏆 Elite 13.800–14.000",
        value=str(
            result["elite_total"]
        ),
        inline=True
    )

    embed.add_field(
        name="⏱️ Durată",
        value=(
            f'{result["duration"]} secunde'
        ),
        inline=True
    )

    embed.set_footer(
        text=(
            "Moldova = jucător observat într-un "
            "clan din Top 100 Moldova."
        )
    )

    await interaction.followup.send(
        embed=embed
    )


# =====================================
# COMANDA /ELITE
# =====================================

@bot.tree.command(
    name="elite",
    description="Afișează jucătorii 13800-14000"
)
async def elite(
    interaction: discord.Interaction
):
    await interaction.response.defer(
        thinking=True
    )

    elite_database = load_database(
        ELITE_DATABASE
    )

    if not elite_database:
        await interaction.followup.send(
            "📭 Baza Elite este goală.\n"
            "Execută mai întâi comanda "
            "`/scanmd`."
        )

        return

    players = list(
        elite_database.values()
    )

    players.sort(
        key=lambda player: (
            int(
                player.get(
                    "trophies",
                    0
                )
                or 0
            ),
            str(
                player.get(
                    "name",
                    ""
                )
            ).lower()
        ),
        reverse=True
    )

    # Discord are limite pentru mesaje.
    # În prima versiune afișăm primii 20.
    visible_players = players[:20]

    lines = []

    for position, player in enumerate(
        visible_players,
        start=1
    ):
        player_tag = str(
            player.get(
                "tag",
                ""
            )
        )

        tag_without_hash = (
            player_tag
            .replace("#", "")
            .upper()
        )

        profile_url = (
            "https://royaleapi.com/player/"
            + tag_without_hash
        )

        player_name = str(
            player.get(
                "name",
                "Jucător necunoscut"
            )
        )

        trophies = int(
            player.get(
                "trophies",
                0
            )
            or 0
        )

        clan_name = str(
            player.get(
                "clan_name",
                "Fără clan"
            )
        )

        # Link apăsabil către RoyaleAPI
        player_link = (
            f"[{player_name}]"
            f"({profile_url})"
        )

        lines.append(
            f"**{position}. {player_link}**\n"
            f"🏆 {trophies} trofee\n"
            f"🏰 {clan_name}"
        )

    embed = discord.Embed(
        title="🏆 Moldova Elite Club",
        description="\n\n".join(lines),
        color=0xFFD700
    )

    embed.add_field(
        name="Interval",
        value="13.800–14.000 trofee",
        inline=True
    )

    embed.add_field(
        name="Total găsiți",
        value=str(
            len(players)
        ),
        inline=True
    )

    if len(players) > 20:
        footer_text = (
            f"Sunt afișați primii 20 din "
            f"{len(players)} jucători."
        )
    else:
        footer_text = (
            "Apasă pe numele jucătorului "
            "pentru profilul RoyaleAPI."
        )

    embed.set_footer(
        text=footer_text
    )

    await interaction.followup.send(
        embed=embed
    )


# =====================================
# TRATAREA ERORILOR
# =====================================

@bot.tree.error
async def command_error(
    interaction: discord.Interaction,
    error
):
    print(
        "Eroare comandă Discord:",
        repr(error)
    )

    message = (
        "❌ A apărut o eroare la "
        "executarea comenzii."
    )

    if interaction.response.is_done():
        await interaction.followup.send(
            message,
            ephemeral=True
        )
    else:
        await interaction.response.send_message(
            message,
            ephemeral=True
        )


# =====================================
# VERIFICAREA VARIABILELOR
# =====================================

if not DISCORD_TOKEN:
    raise RuntimeError(
        "Lipsește variabila DISCORD_TOKEN."
    )

if not CR_API_TOKEN:
    raise RuntimeError(
        "Lipsește variabila CR_API_TOKEN."
    )


# =====================================
# PORNIRE BOT
# =====================================

bot.run(DISCORD_TOKEN)
