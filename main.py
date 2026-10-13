import asyncio
import json
import os
from datetime import datetime, timezone
from urllib.parse import quote

import discord
import requests
from discord import app_commands
from discord.ext import commands, tasks


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

API_BASE = "https://proxy.royaleapi.dev/v1"

DATABASE_FILE = "season_matches.json"

# Verificare la fiecare 60 de secunde
CHECK_INTERVAL_MINUTES = 1

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

database_lock = asyncio.Lock()

commands_synced = False


# =====================================
# FUNCȚII AUXILIARE
# =====================================

def normalize_tag(player_tag):
    player_tag = str(player_tag).strip().upper()

    player_tag = player_tag.replace(
        "O",
        "0"
    )

    if not player_tag.startswith("#"):
        player_tag = "#" + player_tag

    return player_tag


def get_profile_url(player_tag):
    clean_tag = normalize_tag(
        player_tag
    ).replace("#", "")

    return (
        "https://royaleapi.com/player/"
        + clean_tag
    )


def utc_now_text():
    return datetime.now(
        timezone.utc
    ).isoformat()


def format_date(date_text):
    if not date_text:
        return "Necunoscută"

    try:
        date_value = datetime.fromisoformat(
            date_text.replace(
                "Z",
                "+00:00"
            )
        )

        return date_value.strftime(
            "%d.%m.%Y %H:%M UTC"
        )

    except ValueError:
        return date_text


# =====================================
# BAZA DE DATE
# =====================================

def empty_database():
    return {
        "season_started_at": utc_now_text(),
        "players": {}
    }


def load_database():
    if not os.path.exists(DATABASE_FILE):
        return empty_database()

    try:
        with open(
            DATABASE_FILE,
            "r",
            encoding="utf-8"
        ) as file:
            data = json.load(file)

        if not isinstance(data, dict):
            return empty_database()

        if "players" not in data:
            data["players"] = {}

        if "season_started_at" not in data:
            data["season_started_at"] = (
                utc_now_text()
            )

        return data

    except (
        OSError,
        json.JSONDecodeError
    ) as error:
        print(
            "Eroare citire bază:",
            repr(error)
        )

        return empty_database()


def save_database(database):
    temporary_file = (
        DATABASE_FILE + ".tmp"
    )

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
            DATABASE_FILE
        )

        return True

    except OSError as error:
        print(
            "Eroare salvare bază:",
            repr(error)
        )

        return False


# =====================================
# CLASH ROYALE API
# =====================================

def api_get_player(player_tag):
    encoded_tag = quote(
        normalize_tag(player_tag),
        safe=""
    )

    url = (
        f"{API_BASE}/players/"
        f"{encoded_tag}"
    )

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=30
        )

        if response.status_code != 200:
            print(
                "Eroare profil:",
                player_tag,
                response.status_code,
                response.text[:500]
            )

            return None, (
                f"HTTP {response.status_code}"
            )

        return response.json(), None

    except requests.RequestException as error:
        print(
            "Excepție profil:",
            repr(error)
        )

        return None, str(error)


def api_get_battlelog(player_tag):
    encoded_tag = quote(
        normalize_tag(player_tag),
        safe=""
    )

    url = (
        f"{API_BASE}/players/"
        f"{encoded_tag}/battlelog"
    )

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=30
        )

        if response.status_code != 200:
            print(
                "Eroare battlelog:",
                player_tag,
                response.status_code,
                response.text[:500]
            )

            return None, (
                f"HTTP {response.status_code}"
            )

        data = response.json()

        if not isinstance(data, list):
            return None, (
                "Răspuns battlelog invalid."
            )

        return data, None

    except requests.RequestException as error:
        print(
            "Excepție battlelog:",
            repr(error)
        )

        return None, str(error)


# =====================================
# IDENTIFICARE MECI
# =====================================

def create_battle_id(
    battle,
    tracked_tag
):
    battle_time = str(
        battle.get(
            "battleTime",
            ""
        )
    )

    battle_type = str(
        battle.get(
            "type",
            ""
        )
    )

    tags = []

    for side_name in [
        "team",
        "opponent"
    ]:
        for participant in battle.get(
            side_name,
            []
        ):
            participant_tag = participant.get(
                "tag",
                ""
            )

            if participant_tag:
                tags.append(
                    participant_tag
                )

    tags.sort()

    return "|".join([
        normalize_tag(tracked_tag),
        battle_time,
        battle_type,
        ",".join(tags)
    ])


def find_player_side(
    battle,
    player_tag
):
    normalized_tag = normalize_tag(
        player_tag
    )

    for participant in battle.get(
        "team",
        []
    ):
        if normalize_tag(
            participant.get("tag", "")
        ) == normalized_tag:
            return "team"

    for participant in battle.get(
        "opponent",
        []
    ):
        if normalize_tag(
            participant.get("tag", "")
        ) == normalized_tag:
            return "opponent"

    return None


def total_crowns(participants):
    crowns = 0

    for participant in participants:
        crowns += int(
            participant.get(
                "crowns",
                0
            )
            or 0
        )

    return crowns


def get_battle_result(
    battle,
    player_tag
):
    player_side = find_player_side(
        battle,
        player_tag
    )

    if player_side is None:
        return "unknown"

    team_crowns = total_crowns(
        battle.get(
            "team",
            []
        )
    )

    opponent_crowns = total_crowns(
        battle.get(
            "opponent",
            []
        )
    )

    if team_crowns == opponent_crowns:
        return "draw"

    team_won = (
        team_crowns > opponent_crowns
    )

    if player_side == "team":
        return (
            "win"
            if team_won
            else "loss"
        )

    return (
        "loss"
        if team_won
        else "win"
    )


# =====================================
# ÎNREGISTRARE PROFIL
# =====================================

def create_player_record(
    profile
):
    clan = profile.get(
        "clan",
        {}
    )

    return {
        "tag": profile.get(
            "tag",
            ""
        ),
        "name": profile.get(
            "name",
            "Jucător necunoscut"
        ),
        "trophies": int(
            profile.get(
                "trophies",
                0
            )
            or 0
        ),
        "best_trophies": int(
            profile.get(
                "bestTrophies",
                0
            )
            or 0
        ),
        "clan_name": clan.get(
            "name",
            "Fără clan"
        ),
        "tracked_since": utc_now_text(),
        "last_checked": None,
        "matches": 0,
        "wins": 0,
        "losses": 0,
        "draws": 0,
        "battle_ids": []
    }


# =====================================
# ACTUALIZARE PROFIL ȘI MECIURI
# =====================================

def update_player_sync(
    database,
    player_tag,
    import_recent=False
):
    player_tag = normalize_tag(
        player_tag
    )

    profile, profile_error = (
        api_get_player(player_tag)
    )

    if profile is None:
        return {
            "success": False,
            "error": profile_error,
            "new_player": False,
            "new_matches": 0
        }

    players = database["players"]

    new_player = (
        player_tag not in players
    )

    if new_player:
        players[player_tag] = (
            create_player_record(profile)
        )

    record = players[player_tag]

    record["name"] = profile.get(
        "name",
        record.get(
            "name",
            "Jucător necunoscut"
        )
    )

    record["trophies"] = int(
        profile.get(
            "trophies",
            0
        )
        or 0
    )

    record["best_trophies"] = int(
        profile.get(
            "bestTrophies",
            0
        )
        or 0
    )

    clan = profile.get(
        "clan",
        {}
    )

    record["clan_name"] = clan.get(
        "name",
        "Fără clan"
    )

    battles, battle_error = (
        api_get_battlelog(player_tag)
    )

    if battles is None:
        return {
            "success": False,
            "error": battle_error,
            "new_player": new_player,
            "new_matches": 0
        }

    known_ids = set(
        record.get(
            "battle_ids",
            []
        )
    )

    # Prima căutare creează baza.
    # Meciurile recente pot fi importate
    # doar când import_recent este True.
    if (
        new_player
        and not import_recent
    ):
        for battle in battles:
            battle_id = create_battle_id(
                battle,
                player_tag
            )

            known_ids.add(battle_id)

        record["battle_ids"] = list(
            known_ids
        )

        record["last_checked"] = (
            utc_now_text()
        )

        return {
            "success": True,
            "error": None,
            "new_player": True,
            "new_matches": 0
        }

    new_matches = 0

    # Ordine cronologică
    for battle in reversed(battles):
        battle_id = create_battle_id(
            battle,
            player_tag
        )

        if battle_id in known_ids:
            continue

        result = get_battle_result(
            battle,
            player_tag
        )

        if result == "unknown":
            continue

        known_ids.add(battle_id)

        record["matches"] += 1
        new_matches += 1

        if result == "win":
            record["wins"] += 1

        elif result == "loss":
            record["losses"] += 1

        elif result == "draw":
            record["draws"] += 1

    # Păstrăm ultimele 300 de ID-uri
    record["battle_ids"] = list(
        known_ids
    )[-300:]

    record["last_checked"] = (
        utc_now_text()
    )

    return {
        "success": True,
        "error": None,
        "new_player": new_player,
        "new_matches": new_matches
    }


# =====================================
# ACTUALIZARE AUTOMATĂ
# =====================================

@tasks.loop(
    minutes=CHECK_INTERVAL_MINUTES
)
async def automatic_tracker():
    async with database_lock:
        database = load_database()

        player_tags = list(
            database.get(
                "players",
                {}
            ).keys()
        )

        if not player_tags:
            return

        print(
            "Actualizare automată pentru",
            len(player_tags),
            "profiluri."
        )

        for player_tag in player_tags:
            try:
                result = await asyncio.to_thread(
                    update_player_sync,
                    database,
                    player_tag,
                    False
                )

                print(
                    "Actualizare:",
                    player_tag,
                    result
                )

            except Exception as error:
                print(
                    "Eroare actualizare:",
                    player_tag,
                    repr(error)
                )

            await asyncio.sleep(0.25)

        save_database(database)


@automatic_tracker.before_loop
async def before_automatic_tracker():
    await bot.wait_until_ready()


# =====================================
# BOT PORNIT
# =====================================

@bot.event
async def on_ready():
    global commands_synced

    print(
        f"Conectat ca {bot.user}"
    )

    if not commands_synced:
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
                "Eroare sincronizare:",
                repr(error)
            )

    if not automatic_tracker.is_running():
        automatic_tracker.start()


# =====================================
# COMANDA /MECIURI
# =====================================

@bot.tree.command(
    name="meciuri",
    description=(
        "Arată meciurile monitorizate "
        "pentru un profil Clash Royale"
    )
)
@app_commands.describe(
    tag="Tagul jucătorului, ex. #2U0228GUP"
)
async def meciuri(
    interaction: discord.Interaction,
    tag: str
):
    await interaction.response.defer(
        thinking=True
    )

    player_tag = normalize_tag(tag)

    async with database_lock:
        database = load_database()

        try:
            result = await asyncio.to_thread(
                update_player_sync,
                database,
                player_tag,
                False
            )

        except Exception as error:
            print(
                "Eroare /meciuri:",
                repr(error)
            )

            await interaction.followup.send(
                "❌ Nu am putut verifica "
                "profilul.\n"
                f"`{type(error).__name__}: "
                f"{str(error)[:300]}`"
            )

            return

        if not result["success"]:
            await interaction.followup.send(
                "❌ Profilul nu a putut fi "
                "găsit sau verificat.\n"
                f"`{result.get('error')}`"
            )

            return

        save_database(database)

        record = database[
            "players"
        ][player_tag]

    matches = int(
        record.get("matches", 0)
    )

    wins = int(
        record.get("wins", 0)
    )

    losses = int(
        record.get("losses", 0)
    )

    draws = int(
        record.get("draws", 0)
    )

    if matches > 0:
        win_rate = (
            wins / matches
        ) * 100
    else:
        win_rate = 0

    profile_url = get_profile_url(
        player_tag
    )

    player_name = record.get(
        "name",
        "Jucător necunoscut"
    )

    embed = discord.Embed(
        title=(
            f"🎮 Meciuri monitorizate: "
            f"{player_name}"
        ),
        url=profile_url,
        color=0x3498DB
    )

    embed.add_field(
        name="🏷️ Tag",
        value=player_tag,
        inline=True
    )

    embed.add_field(
        name="🏆 Trofee",
        value=str(
            record.get(
                "trophies",
                0
            )
        ),
        inline=True
    )

    embed.add_field(
        name="🏰 Clan",
        value=record.get(
            "clan_name",
            "Fără clan"
        ),
        inline=True
    )

    embed.add_field(
        name="🎮 Meciuri",
        value=str(matches),
        inline=True
    )

    embed.add_field(
        name="✅ Victorii",
        value=str(wins),
        inline=True
    )

    embed.add_field(
        name="❌ Înfrângeri",
        value=str(losses),
        inline=True
    )

    embed.add_field(
        name="➖ Egaluri",
        value=str(draws),
        inline=True
    )

    embed.add_field(
        name="📊 Rată de victorie",
        value=f"{win_rate:.1f}%",
        inline=True
    )

    embed.add_field(
        name="📅 Monitorizat din",
        value=format_date(
            record.get(
                "tracked_since"
            )
        ),
        inline=False
    )

    if result["new_player"]:
        embed.description = (
            "🆕 Profilul a fost înregistrat.\n"
            "Numărătoarea exactă începe acum."
        )

    elif result["new_matches"] > 0:
        embed.description = (
            f"Au fost găsite "
            f"**{result['new_matches']}** "
            f"meciuri noi."
        )

    else:
        embed.description = (
            "Nu au fost găsite meciuri noi "
            "de la ultima verificare."
        )

    embed.set_footer(
        text=(
            "Battle log-ul este limitat. "
            "Botul numără exact doar meciurile "
            "observate după înregistrare."
        )
    )

    view = discord.ui.View()

    view.add_item(
        discord.ui.Button(
            label="Vezi profilul pe RoyaleAPI",
            url=profile_url,
            emoji="👤"
        )
    )

    await interaction.followup.send(
        embed=embed,
        view=view
    )


# =====================================
# COMANDA /RESETSEZON
# =====================================

@bot.tree.command(
    name="resetsezon",
    description=(
        "Resetează contoarele tuturor "
        "profilurilor monitorizate"
    )
)
@app_commands.default_permissions(
    manage_guild=True
)
async def resetsezon(
    interaction: discord.Interaction
):
    await interaction.response.defer(
        thinking=True,
        ephemeral=True
    )

    async with database_lock:
        database = load_database()

        reset_time = utc_now_text()

        database["season_started_at"] = (
            reset_time
        )

        for record in database.get(
            "players",
            {}
        ).values():
            record["tracked_since"] = (
                reset_time
            )

            record["matches"] = 0
            record["wins"] = 0
            record["losses"] = 0
            record["draws"] = 0

            # Golim ID-urile.
            # La următoarea verificare,
            # battle log-ul recent va putea
            # fi folosit ca nou punct de pornire.
            record["battle_ids"] = []

        save_database(database)

    await interaction.followup.send(
        "✅ Contoarele sezonului au fost "
        "resetate.\n\n"
        "⚠️ Rulează `/meciuri` pentru fiecare "
        "profil înainte de alte meciuri, pentru "
        "a crea noul punct de pornire.",
        ephemeral=True
    )


# =====================================
# COMANDA /STERGEPROFIL
# =====================================

@bot.tree.command(
    name="stergeprofil",
    description=(
        "Șterge un profil din monitorizare"
    )
)
@app_commands.describe(
    tag="Tagul profilului care va fi șters"
)
@app_commands.default_permissions(
    manage_guild=True
)
async def stergeprofil(
    interaction: discord.Interaction,
    tag: str
):
    player_tag = normalize_tag(tag)

    async with database_lock:
        database = load_database()

        players = database.get(
            "players",
            {}
        )

        if player_tag not in players:
            await interaction.response.send_message(
                "❌ Profilul nu este monitorizat.",
                ephemeral=True
            )

            return

        del players[player_tag]

        save_database(database)

    await interaction.response.send_message(
        f"✅ Profilul `{player_tag}` a fost "
        "șters din monitorizare.",
        ephemeral=True
    )


# =====================================
# ERORI COMENZI
# =====================================

@bot.tree.error
async def command_error(
    interaction: discord.Interaction,
    error
):
    print(
        "Eroare comandă:",
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
# VERIFICARE VARIABILE
# =====================================

if not DISCORD_TOKEN:
    raise RuntimeError(
        "Lipsește DISCORD_TOKEN."
    )

if not CR_API_TOKEN:
    raise RuntimeError(
        "Lipsește CR_API_TOKEN."
    )


# =====================================
# PORNIRE BOT
# =====================================

bot.run(DISCORD_TOKEN)
