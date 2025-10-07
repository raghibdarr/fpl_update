import discord
from discord.ext import commands
import aiohttp
import asyncio
from fuzzywuzzy import process, fuzz
import difflib
from datetime import datetime, timezone, timedelta
from discord import Embed, Color
import os
import socket
import sys
from dotenv import load_dotenv
from collections import defaultdict
import aiosqlite
from PIL import Image, ImageDraw, ImageFont, ImageColor
import io
import json
from utils.api_helpers import fetch_api_data, fetch_fpl_data
from utils.image_generator import (
    create_table_image,
    create_fixture_grid,
    get_fixture_color,
    get_text_color,
    fit_text_to_width,
    wrap_text_to_two_lines,
    create_leaderboard_image,
)
from repos.db_repo import (
    setup_database,
    upsert_user,
    get_user_by_discord_id,
    upsert_league,
    get_league_id_for_guild,
)
from services.league_service import fetch_league_standings
from services.user_service import fetch_user_team_name, fetch_user_total_points

# Load environment variables
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

# FDR color mapping
def get_fdr_color(difficulty):
    if difficulty == 1:
        return 0x375523  # Dark Green
    elif difficulty == 2:
        return 0x01FC7A  # Light Green
    elif difficulty == 3:
        return 0xE7E7E7  # Grey
    elif difficulty == 4:
        return 0xFF1751  # Light Red
    else:
        return 0x80072D  # Dark Red
    
# Cup colors
CUP_COLORS = {
    "UCL": "#1A3772",
    "UEL": "#F25E27",
    "UECL": "#6CC24A",
    "EFL": "#1D925F",
    "FA": "#D70024"
}
    
# Bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

@bot.event
async def setup_hook():
    # Load cogs at startup to register commands
    await bot.load_extension('cogs.fpl_commands')
    await bot.load_extension('cogs.league_commands')
    await bot.load_extension('cogs.user_commands')
    # Dev-guild-only slash sync for instant availability
    dev_guild_id = os.getenv('DEV_GUILD_ID')
    if dev_guild_id:
        try:
            guild = discord.Object(id=int(dev_guild_id))
            # Copy global commands into the dev guild for instant visibility
            bot.tree.copy_global_to(guild=guild)
            await bot.tree.sync(guild=guild)
            print(f"Slash commands synced to dev guild {dev_guild_id}")
        except Exception as e:
            print(f"Dev guild slash sync failed: {e}")
    # Optional global sync for rollout (propagation can take minutes)
    sync_global = os.getenv('SYNC_GLOBAL', '').lower() in ('1', 'true', 'yes')
    if sync_global:
        try:
            await bot.tree.sync()
            print("Global slash commands synced")
        except Exception as e:
            print(f"Global slash sync failed: {e}")

# Ensure only a single instance of the bot runs per machine
_singleton_socket = None

def acquire_single_instance_lock(port: int) -> bool:
    try:
        global _singleton_socket
        _singleton_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _singleton_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        _singleton_socket.bind(("127.0.0.1", port))
        _singleton_socket.listen(1)
        return True
    except OSError:
        return False

from data.team_aliases import team_aliases

# Base URLs for APIs
FPL_API_BASE = "https://fantasy.premierleague.com/api/"
PULSE_API_BASE = "https://sdp-prem-prod.premier-league-prod.pulselive.com/api/v2/"

# Competition IDs for Pulse API
COMPETITION_IDS = {
    "PL": 1,
    "FA": 4,
    "EFL": 2,
    "UCL": 5,
    "UEL": 6,
    "UECL": 1125
}



# table command moved to cogs.fpl_commands

# create_table_image now imported from utils.image_generator

# Database setup is now imported from repos.db_repo

@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')
    print(f'Bot is in {len(bot.guilds)} guilds')
    # Helpful for diagnosing duplicate instances
    try:
        import os as _os
        print(f'Process PID: {_os.getpid()}')
    except Exception:
        pass
    try:
        # No custom presence needed
        pass
    except Exception:
        pass
    await setup_database()

# Command to say hello
# @bot.command()
async def hello(ctx):
    print(f"Received hello command from {ctx.author}")
    await ctx.send('Hello! I am the FPL Bot.')

# Command to get current gameweek information
# @bot.command()
async def gameweek(ctx):
    try:
        # Fetch the bootstrap-static data (contains overall FPL data)
        data = await fetch_fpl_data("bootstrap-static/")
        # Find the current gameweek
        current_gameweek = next(gw for gw in data['events'] if gw['is_current'])
        
        # Parse and format the deadline time
        deadline_time = datetime.strptime(current_gameweek['deadline_time'], "%Y-%m-%dT%H:%M:%SZ")
        formatted_deadline = deadline_time.strftime("%A, %d %B %Y at %H:%M UTC")
        
        # Construct the response message
        response = f"Current Gameweek: {current_gameweek['name']}\n"
        response += f"Deadline: {formatted_deadline}\n"
        response += f"Average Score: {current_gameweek['average_entry_score']}"
        
        await ctx.send(response)
    except Exception as e:
        await ctx.send(f"An error occurred: {str(e)}")

# Command to get player information
# @bot.command()
async def player(ctx, *, player_name):
    try:
        # Fetch the bootstrap-static data
        data = await fetch_fpl_data("bootstrap-static/")
        
        print(f"Number of players in data: {len(data.get('elements', []))}")
        
        if not data.get('elements'):
            await ctx.send("Error: Unable to fetch player data. Please try again later.")
            return

        # Get all players, sorted by total_points (descending)
        all_players = sorted(
            data['elements'],
            key=lambda x: x['total_points'],
            reverse=True
        )
        
        print("Top 5 players by total points:")
        for p in all_players[:5]:
            print(f"{p['first_name']} {p['second_name']}: {p['total_points']} points")
        
        # Custom search function
        def match_player(search_term, player):
            full_name = f"{player['first_name']} {player['second_name']}".lower()
            return search_term.lower() in full_name
        
        # Find matching players
        matching_players = [p for p in all_players if match_player(player_name, p)]
        
        print(f"Matching players for '{player_name}': {[f'{p['first_name']} {p['second_name']}' for p in matching_players[:5]]}")
        
        if matching_players:
            player = matching_players[0]  # Take the highest scoring matching player
            
            # Find the team name for the player
            team = next(t['name'] for t in data['teams'] if t['id'] == player['team'])
            
            # Construct the response message
            response = f"Player: {player['first_name']} {player['second_name']} ({team})\n"
            response += f"Price: £{player['now_cost'] / 10}m\n"
            response += f"Total Points: {player['total_points']}"
            
            full_name = f"{player['first_name']} {player['second_name']}"
            if full_name.lower() != player_name.lower():
                response = f"Showing results for '{full_name}':\n\n" + response
            
            await ctx.send(response)
        else:
            await ctx.send(f"Player '{player_name}' not found. Please try a different name.")
    except Exception as e:
        print(f"An error occurred: {str(e)}")
        await ctx.send(f"An error occurred: {str(e)}")

# Command to get fixtures
# @bot.command()
async def fixtures(ctx, *, args=""):
    # Parse arguments
    params = args.split()
    num_gameweeks = 6  # Default
    teams = []
    sort_method = "alphabetical"  # Default sorting method
    start_gw = None
    end_gw = None
    show_cups = False  # New parameter for cup fixtures
    
    for param in params:
        if param.lower().startswith("gw"):
            gw = int(param[2:])
            if start_gw is None:
                start_gw = gw
            else:
                end_gw = gw
        elif param.isdigit():
            if start_gw is None:  # Only set num_gameweeks if GW range is not specified
                num_gameweeks = min(int(param), 38)
        elif param.lower() in ["fdr", "alphabetical", "table"]:
            sort_method = param.lower()
        elif param.lower() == "cups":
            show_cups = True
        else:
            teams.extend(param.strip().rstrip(',').lower().split(','))
    
    teams = [team.strip() for team in teams if team.strip()]  # Remove empty strings
    
    # Handle multi-word team names
    multi_word_teams = [name.lower() for name in team_aliases.keys() if ' ' in name]
    for multi_word_team in multi_word_teams:
        words = multi_word_team.split()
        if all(word in teams for word in words):
            for word in words:
                teams.remove(word)
            teams.append(multi_word_team)
    
    # Calculate num_gameweeks based on GW parameters if provided
    if start_gw is not None:
        if end_gw is None:
            end_gw = 38
        num_gameweeks = end_gw - start_gw + 1
    
    num_gameweeks = min(num_gameweeks, 38)  # Cap at 38 gameweeks

    print(f"Teams after parsing: {teams}")
    print(f"Sort method: {sort_method}")
    print(f"Start GW: {start_gw}")
    print(f"End GW: {end_gw}")
    print(f"Number of gameweeks: {num_gameweeks}")
    print(f"Show cups: {show_cups}")
    
    await ctx.send("Generating fixture grid... This may take a moment.")
    
    try:
        fixture_data, actual_start_gw, actual_gameweeks, team_names, gw_dates, cup_fixture_buckets = await fetch_fixture_data(num_gameweeks, teams, sort_method, start_gw, show_cups)
        if not fixture_data:
            await ctx.send("No valid teams found. Please check your team names and try again.")
            return
        
        team_positions = {}
        team_points = {}
        if sort_method == "table":
            async with aiohttp.ClientSession() as session:
                bootstrap_data = await fetch_api_data(session, f"{FPL_API_BASE}bootstrap-static/")
            for team in bootstrap_data['teams']:
                team_positions[team['short_name']] = team['position']
                team_points[team['short_name']] = team['points']

        image = create_fixture_grid(fixture_data, actual_gameweeks, actual_start_gw, team_names, gw_dates, sort_method, team_positions, team_points, cup_fixture_buckets)
        
        img_byte_arr = io.BytesIO()
        image.save(img_byte_arr, format='PNG')
        img_byte_arr.seek(0)
        
        await ctx.send(file=discord.File(fp=img_byte_arr, filename='fixtures.png'))
    except Exception as e:
        await ctx.send(f"An error occurred: {str(e)}")
        print(f"Full error: {e}")

from services.fixtures_service import fetch_fixture_data

# create_fixture_grid now imported from utils.image_generator

# Function to get fixture color
# get_fixture_color and get_text_color now imported from utils.image_generator

# Helper for cup opponents: generate a short abbreviation when not a PL team
def abbreviate_team_name(team_name: str) -> str:
    if not team_name:
        return "?"
    words = [w for w in ''.join(ch if ch.isalnum() or ch.isspace() else ' ' for ch in team_name).split() if w]
    if len(words) == 1:
        return words[0][:3].upper()
    if len(words) == 2:
        return (words[0][0] + words[1][:2]).upper()
    return (words[0][0] + words[1][0] + words[2][0]).upper()

# Helper to fit text into a max pixel width with ellipsis
# fit_text_to_width and wrap_text_to_two_lines now imported from utils.image_generator

# Command to get schedule
# @bot.command()
async def schedule(ctx, *, team_name=None):
    try:
        fixtures_data = await fetch_fpl_data("fixtures/")
        teams_data = await fetch_fpl_data("bootstrap-static/")
        
        team_map = {team['id']: team for team in teams_data['teams']}
        current_gw = next(gw for gw in teams_data['events'] if gw['is_current'])['id']
        
        if team_name:
            team_name_lower = team_name.lower()
            matched_team = None
            for full_name, aliases in team_aliases.items():
                if team_name_lower in [alias.lower() for alias in aliases] or team_name_lower == full_name.lower():
                    matched_team = full_name
                    break
            
            if matched_team:
                team_id = next((team['id'] for team in teams_data['teams'] 
                                if team['name'] == matched_team), None)
                print(f"Matched team: {matched_team}, Team ID: {team_id}")
            else:
                await ctx.send(f"Team '{team_name}' not found. Please check the spelling.")
                return

            if team_id is None:
                await ctx.send(f"Error: Unable to find team ID for {matched_team}. Please try again later.")
                return

            current_time = datetime.now(timezone.utc)

            upcoming_fixtures = [
                fixture for fixture in fixtures_data
                if datetime.strptime(fixture['kickoff_time'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc) > current_time
            ]

            team_fixtures = [f for f in upcoming_fixtures if f['team_h'] == team_id or f['team_a'] == team_id]
            team_fixtures.sort(key=lambda x: x['event'])

            title_embed = Embed(title=f"Upcoming fixtures for {matched_team.title()}", color=Color.blue())
            embeds = [title_embed]

            for fixture in team_fixtures[:5]:
                is_home = fixture['team_h'] == team_id
                opponent = team_map[fixture['team_a' if is_home else 'team_h']]['name']
                fdr = fixture['team_h_difficulty' if is_home else 'team_a_difficulty']
                gw = fixture['event']
                kickoff_time = datetime.strptime(fixture['kickoff_time'], "%Y-%m-%dT%H:%M:%SZ")
                
                # Convert to Unix timestamp for Discord
                unix_timestamp = int(kickoff_time.timestamp())
                
                # Create Discord timestamp
                discord_timestamp = f"<t:{unix_timestamp}:R> (<t:{unix_timestamp}:f>)"
                
                fixture_text = f"GW{gw} - {discord_timestamp} - {'(H)' if is_home else '(A)'} vs {opponent} - FDR: {fdr}"
                
                embed = Embed(description=fixture_text, color=get_fdr_color(fdr))
                embeds.append(embed)

            print(f"Team ID for {matched_team}: {team_id}")
            print(f"Number of fixtures found: {len(team_fixtures)}")
            for fixture in team_fixtures[:5]:
                print(f"Fixture: {fixture}")

            await ctx.send(embeds=embeds)
        else:
            upcoming_fixtures = [f for f in fixtures_data if f['event'] == current_gw + 1]
            upcoming_fixtures.sort(key=lambda x: x['kickoff_time'])
            
            # Group fixtures by day
            fixtures_by_day = defaultdict(list)
            for fixture in upcoming_fixtures:
                kickoff_time = datetime.strptime(fixture['kickoff_time'], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                day_key = kickoff_time.strftime("%A, %d %B %Y")  # Get day name and date
                fixtures_by_day[day_key].append(fixture)
            
            embed = discord.Embed(title=f"Upcoming Fixtures - Gameweek {current_gw + 1}", color=discord.Color.blue())
            
            for day, fixtures in fixtures_by_day.items():
                fixture_strings = []
                for fixture in fixtures:
                    home_team = team_map[fixture['team_h']]['name']
                    away_team = team_map[fixture['team_a']]['name']
                    kickoff_time = datetime.strptime(fixture['kickoff_time'], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                    unix_timestamp = int(kickoff_time.timestamp())
                    fixture_str = f"• {home_team} vs {away_team} - <t:{unix_timestamp}:R>, <t:{unix_timestamp}:t>"
                    fixture_strings.append(fixture_str)
                
                # Join all fixtures for this day into a single string
                day_fixtures = "\n".join(fixture_strings)
                embed.add_field(name=f"**{day}**", value=day_fixtures, inline=False)
            
            await ctx.send(embed=embed)

    except Exception as e:
        print(f"An error occurred: {str(e)}")
        await ctx.send(f"An error occurred while fetching fixtures. Please try again later.")

# Command to link FPL ID
async def link(ctx, fpl_id: int = None):
    if fpl_id is None:
        await ctx.send("Please provide your FPL ID. Usage: !link <your_fpl_id>")
        return

    try:
        team_name = await fetch_user_team_name(fpl_id)

        await upsert_user(ctx.author.id, fpl_id, team_name)

        await ctx.send(f"Successfully linked your Discord account to FPL team: {team_name}")
    except Exception as e:
        print(f"An error occurred: {str(e)}")
        await ctx.send("An error occurred while linking your account. Please check your FPL ID and try again.")

# Error handler for MissingRequiredArgument
# @link.error
async def link_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("Please provide your FPL ID. Usage: !link <your_fpl_id>")

# Command to get my team
async def myteam(ctx):
    try:
        result = await get_user_by_discord_id(ctx.author.id)

        if result:
            fpl_id, team_name = result
            await ctx.send(f"Your linked FPL team is: {team_name} (ID: {fpl_id})")
        else:
            await ctx.send("You haven't linked an FPL team yet. Use the !link command to link your team.")
    except Exception as e:
        print(f"An error occurred: {str(e)}")
        await ctx.send("An error occurred while fetching your team information.")

# Command to get my points
async def mypoints(ctx):
    try:
        result = await get_user_by_discord_id(ctx.author.id)

        if result:
            fpl_id = result[0]
            total_points = await fetch_user_total_points(fpl_id)
            await ctx.send(f"Your total FPL points: {total_points}")
        else:
            await ctx.send("You haven't linked an FPL team yet. Use the !link command to link your team.")
    except Exception as e:
        print(f"An error occurred: {str(e)}")
        await ctx.send("An error occurred while fetching your points.")

# Function to get league standings
async def fetch_league_standings(league_id):
    async with aiohttp.ClientSession() as session:
        # Fetch league standings
        league_url = f"https://fantasy.premierleague.com/api/leagues-classic/{league_id}/standings/"
        async with session.get(league_url) as resp:
            if resp.status != 200:
                raise Exception(f"League API request failed with status {resp.status}")
            league_data = await resp.json()

    standings = league_data['standings']['results']

    async def fetch_team_data(entry):
        team_id = entry['entry']
        async with aiohttp.ClientSession() as session:
            team_url = f"https://fantasy.premierleague.com/api/entry/{team_id}/"
            try:
                async with session.get(team_url) as resp:
                    if resp.status == 200:
                        team_data = await resp.json()
                        entry['value'] = team_data.get('last_deadline_value', 0)
                        entry['overall_rank'] = team_data.get('summary_overall_rank', 'N/A')
                        print(f"Team {team_id}: Raw data: {team_data}")
                    else:
                        print(f"Team {team_id}: API request failed with status {resp.status}")
                        entry['value'] = 0
                        entry['overall_rank'] = 'N/A'
            except Exception as e:
                print(f"Team {team_id}: Error fetching data: {str(e)}")
                entry['value'] = 0
                entry['overall_rank'] = 'N/A'
        print(f"Team {team_id}: Value={entry['value']}, OR={entry['overall_rank']}")

    # Fetch team data concurrently
    await asyncio.gather(*[fetch_team_data(entry) for entry in standings])

    return standings

# create_leaderboard_image now imported from utils.image_generator

# Command to get league standings as a leaderboard image
# @bot.command()
async def leaderboard(ctx):
    try:
        league_id = await get_league_id_for_guild(ctx.guild.id)
        
        if league_id is not None:
            await ctx.send("Fetching leaderboard data... This may take a moment.")
            standings = await fetch_league_standings(league_id)
            print(f"Fetched standings: {standings[:2]}")  # Print first two entries for debugging
            image = create_leaderboard_image(standings)
            if image is None:
                await ctx.send("An error occurred while creating the leaderboard image. Check the console for details.")
                return
            await ctx.send(file=discord.File(fp=image, filename='leaderboard.png'))
        else:
            await ctx.send("No league has been set. Use !set_league command to set a league ID.")
    except Exception as e:
        print(f"An error occurred in leaderboard command: {str(e)}")
        await ctx.send(f"An error occurred while fetching the leaderboard: {str(e)}")

# Command to set league ID
# @bot.command()
async def set_league(ctx, league_id: int):
    try:
        await upsert_league(ctx.guild.id, league_id)
        await ctx.send(f"League ID set to {league_id}")
    except Exception as e:
        print(f"An error occurred: {str(e)}")
        await ctx.send("An error occurred while setting the league ID.")

# Command to get league ID
# @bot.command()
async def get_league(ctx):
    try:
        league_id = await get_league_id_for_guild(ctx.guild.id)
        if league_id is not None:
            await ctx.send(f"The current league ID is {league_id}")
        else:
            await ctx.send("No league ID has been set. Use !set_league to set one.")
    except Exception as e:
        print(f"An error occurred: {str(e)}")
        await ctx.send("An error occurred while fetching the league ID.")

if __name__ == "__main__":
    if not acquire_single_instance_lock(49721):
        print("Another instance of the bot is already running. Exiting.")
        sys.exit(0)
    print("Registering commands...")
    print(f"Registered commands: {[command.name for command in bot.commands]}")
    bot.run(TOKEN)