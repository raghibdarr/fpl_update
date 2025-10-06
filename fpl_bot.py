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

# Team aliases for fuzzy matching
team_aliases = {
    "Arsenal": ["arsenal", "ars", "gunners", "arsenal fc", "the gunners", "the arsenal", "arsenal fc", "gooners", "the gooners", "afc"],
    "Aston Villa": ["aston villa", "villa", "avl", "villians", "aston villa fc", "avfc", "the villians", "villans", "the villans"],
    "Bournemouth": ["bournemouth", "bou", "bournemouth fc", "cherries", "afc bournemouth", "the cherries", "afcb"],
    "Brentford": ["brentford", "bre", "brentford fc", "the bees", "bfc", "bees"],
    "Brighton": ["brighton", "brighton and hove albion", "bha", "seagulls", "brighton fc", "the seagulls", "bhafc"],
    "Chelsea": ["chelsea", "che", "blues", "chels", "chelsea fc", "the blues", "cfc"],
    "Crystal Palace": ["crystal palace", "palace", "cry", "cpfc", "eagles", "crystal palace fc", "the eagles"],
    "Everton": ["everton", "eve", "toffees", "everton fc", "the toffees", "efc"],
    "Fulham": ["fulham", "ful", "fulham fc", "the cottagers", "cottagers", "ffc"],
    "Ipswich": ["ipswich", "ipswich town", "ips", "the tractor boys", "tractor boys", "itfc"],
    "Leicester": ["leicester", "leicester city", "lei", "foxes", "the foxes", "lcfc"],
    "Liverpool": ["liverpool", "liv", "liverpool fc", "pool", "the reds", "reds", "lfc"],
    "Man City": ["manchester city", "man city", "city", "mci", "cityzens", "mcfc", "the citizens", "the blues", "mancity", "mcfc"],
    "Man Utd": ["manchester united", "man united", "united", "mun", "utd", "man utd", "mufc", "mu", "red devils", "reddevils", "the red devils", "the reddevils"],
    "Newcastle": ["newcastle", "newcastle united", "new", "nufc", "newcastle", "magpies", "the magpies", "nufc", "newcastle utd", "newcastle united fc", "newcastle utd fc", "the magpies fc", "the magpies fc"],
    "Nott'm Forest": ["nottingham forest", "nottm forest", "forest", "nfo", "nottingham", "trouts", "forest fc", "nottingham forest fc", "nffc"],
    "Southampton": ["southampton", "saints", "sou", "southampton fc", "the saints", "saints fc", "sfc"],
    "Spurs": ["tottenham", "tottenham hotspur", "spurs", "tot", "thfc", "hotspurs", "spurs fc", "the spurs", "lilywhites", "the lilywhites", "spurs"],
    "West Ham": ["west ham", "west ham united", "whu", "hammers", "west ham united fc", "the hammers", "the irons", "irons", "whufc"],
    "Wolves": ["wolves", "wolverhampton", "wolverhampton wanderers", "wol", "wolves fc", "the wolves", "wolves", "wwfc"]
}

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

# Function to fetch data from an API
async def fetch_api_data(session, url, params=None):
    async with session.get(url, params=params) as response:
        response.raise_for_status()
        return await response.json()

# Convenience wrapper for FPL API endpoints
async def fetch_fpl_data(endpoint: str, params=None):
    async with aiohttp.ClientSession() as session:
        return await fetch_api_data(session, f"{FPL_API_BASE}{endpoint}", params)

# Command to display the league table
@bot.command()
async def table(ctx):
    try:
        async with aiohttp.ClientSession() as session:
            bootstrap_data = await fetch_api_data(session, f"{FPL_API_BASE}bootstrap-static/")
        
        # Sort teams by position
        sorted_teams = sorted(bootstrap_data['teams'], key=lambda x: x['position'])
        
        # Create the table image
        image = create_table_image(sorted_teams)
        
        # Convert image to bytes
        img_byte_arr = io.BytesIO()
        image.save(img_byte_arr, format='PNG')
        img_byte_arr.seek(0)
        
        # Send the image
        await ctx.send(file=discord.File(fp=img_byte_arr, filename='table.png'))
    except Exception as e:
        await ctx.send(f"An error occurred: {str(e)}")
        print(f"Full error: {e}")

# Function to create the table image
def create_table_image(teams):
    # Define image properties
    width = 1000
    height = 50 + len(teams) * 30
    padding = 10
    font = ImageFont.truetype("arial.ttf", 16)
    header_font = ImageFont.truetype("arialbd.ttf", 16)

    # Create image and drawing context
    image = Image.new('RGB', (width, height), color='white')
    draw = ImageDraw.Draw(image)

    # Define column widths
    col_widths = [50, 200, 50, 50, 50, 50, 50, 50, 50, 50]
    
    # Draw headers
    headers = ["Pos", "Team", "Played", "Won", "Drawn", "Lost", "GF", "GA", "GD", "Points"]
    x = padding
    for header, col_width in zip(headers, col_widths):
        draw.text((x, padding), header, font=header_font, fill='black')
        x += col_width

    # Draw team data
    for i, team in enumerate(teams):
        y = 40 + i * 30
        x = padding
        row = [
            str(team['position']),
            team['name'],
            str(team['played']),
            str(team['win']),
            str(team['draw']),
            str(team['loss']),
            str(team.get('goals_for', 'N/A')),
            str(team.get('goals_against', 'N/A')),
            str(team.get('goal_difference', 'N/A')),
            str(team['points'])
        ]
        for text, col_width in zip(row, col_widths):
            draw.text((x, y), text, font=font, fill='black')
            x += col_width

        # Draw alternating row backgrounds
        if i % 2 == 0:
            draw.rectangle([0, y-5, width, y+25], fill='#f0f0f0')

    # Draw horizontal lines
    for i in range(len(teams) + 1):
        y = 35 + i * 30
        draw.line([(0, y), (width, y)], fill='#d0d0d0')

    # Draw vertical lines
    x = 0
    for col_width in col_widths:
        x += col_width
        draw.line([(x, 0), (x, height)], fill='#d0d0d0')

    return image

# Database setup
async def setup_database():
    async with aiosqlite.connect('fpl_users.db') as db:
        # Create users table
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                discord_id INTEGER PRIMARY KEY,
                fpl_id INTEGER,
                team_name TEXT
            )
        ''')
        # Create leagues table
        await db.execute('''
            CREATE TABLE IF NOT EXISTS leagues (
                guild_id INTEGER PRIMARY KEY,
                league_id INTEGER
            )
        ''')
        await db.commit()

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
@bot.command()
async def hello(ctx):
    print(f"Received hello command from {ctx.author}")
    await ctx.send('Hello! I am the FPL Bot.')

# Command to get current gameweek information
@bot.command()
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
@bot.command()
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
@bot.command()
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

# REFACTORED fetch_fixture_data function
async def fetch_fixture_data(num_gameweeks, selected_teams=None, sort_method="alphabetical", start_gw=None, show_cups=False):
    async with aiohttp.ClientSession() as session:
        bootstrap = await fetch_api_data(session, f"{FPL_API_BASE}bootstrap-static/")

    teams = {team['id']: {'short': team['short_name'], 'name': team['name']} for team in bootstrap['teams']}
    team_name_to_short = {team['name']: team['short_name'] for team in bootstrap['teams']}

    alias_to_team = {}
    for team, aliases in team_aliases.items():
        for alias in aliases:
            alias_to_team[alias.lower()] = team

    if selected_teams:
        selected_team_shorts = set()
        for team in selected_teams:
            best_match, score = process.extractOne(team.lower(), alias_to_team.keys())
            if score > 80:
                matched_team_name = alias_to_team[best_match]
                if matched_team_name in team_name_to_short:
                    selected_team_shorts.add(team_name_to_short[matched_team_name])
        
        if selected_team_shorts:
            filtered_teams = {id: team for id, team in teams.items() if team['short'] in selected_team_shorts}
        else:
            filtered_teams = teams
    else:
        filtered_teams = teams

    current_time = datetime.now(timezone.utc)
    current_gw = next((event for event in bootstrap['events'] if event['is_current']), None)
    fpl_fixtures = None
    
    if start_gw is None:
        if current_gw:
            # If all fixtures in the current GW are finished, start at the next GW; otherwise include current GW
            fpl_fixtures = await fetch_fpl_data("fixtures/")
            has_unfinished = any(
                (fx.get('event') == current_gw['id']) and (not fx.get('finished', False))
                for fx in fpl_fixtures
            )
            start_gw = current_gw['id'] if has_unfinished else current_gw['id'] + 1
        else:
            start_gw = next(event['id'] for event in bootstrap['events'] if not event['finished'])

    end_gw = min(start_gw + num_gameweeks - 1, 38)
    actual_gameweeks = end_gw - start_gw + 1

    # Initialize fixture buckets with independent dicts for each GW
    fixture_data = {
        team['short']: [
            {'opponent': '', 'fdr': 0} for _ in range(actual_gameweeks)
        ]
        for team in filtered_teams.values()
    }
    cup_fixture_buckets = defaultdict(list)

    # 1) Populate Premier League fixtures using the official FPL endpoint
    if fpl_fixtures is None:
        async with aiohttp.ClientSession() as session:
            fpl_fixtures = await fetch_api_data(session, f"{FPL_API_BASE}fixtures/")

    for fixture in fpl_fixtures:
        gw = fixture.get('event')
        if gw is None or not (start_gw <= gw <= end_gw):
            continue

        home_id = fixture['team_h']
        away_id = fixture['team_a']
        home_short = teams.get(home_id, {}).get('short')
        away_short = teams.get(away_id, {}).get('short')
        if not home_short or not away_short:
            continue

        gw_index = gw - start_gw
        home_fdr = fixture.get('team_h_difficulty') or 0
        away_fdr = fixture.get('team_a_difficulty') or 0

        if home_short in fixture_data:
            fixture_data[home_short][gw_index] = {'opponent': away_short.upper(), 'fdr': home_fdr}
        if away_short in fixture_data:
            fixture_data[away_short][gw_index] = {'opponent': home_short.lower(), 'fdr': away_fdr}

    # 2) Optionally enrich with cup fixtures via Pulse API
    if show_cups:
        # Use Pulse matches endpoint per competition with kickoff range windows
        # Build monthly windows spanning the GW date range
        start_deadline = next(e for e in bootstrap['events'] if e['id'] == start_gw)['deadline_time']
        end_deadline = next(e for e in bootstrap['events'] if e['id'] == end_gw)['deadline_time']
        start_dt = datetime.fromisoformat(start_deadline.replace('Z', '+00:00'))
        end_dt = datetime.fromisoformat(end_deadline.replace('Z', '+00:00'))

        async with aiohttp.ClientSession() as session:
            tasks = []
            windows = []
            # Iterate months covering [start_dt - 7d, end_dt + 1d]
            probe_start = (start_dt - timedelta(days=7)).replace(day=1)
            probe_end = (end_dt + timedelta(days=1)).replace(day=1)
            cursor = probe_start
            while cursor <= probe_end:
                year = cursor.year
                month = cursor.month
                next_month_year = year + (1 if month == 12 else 0)
                next_month = 1 if month == 12 else month + 1
                kick_from = f"{year}-{month:02d}-01"
                kick_to = f"{next_month_year}-{next_month:02d}-01"
                windows.append((kick_from, kick_to, year))
                cursor = cursor.replace(year=next_month_year, month=next_month, day=1)

            for comp, comp_id in COMPETITION_IDS.items():
                if comp == 'PL':
                    continue
                for kick_from, kick_to, year in windows:
                    params = {
                        'competition': comp_id,
                        'season': year,
                        'kickoff>': kick_from,
                        'kickoff<': kick_to,
                        '_limit': 200
                    }
                    print(f"[CUPS][REQ] comp={comp}({comp_id}) params={params}")
                    tasks.append(fetch_api_data(session, f"{PULSE_API_BASE}matches", params=params))

            pages = await asyncio.gather(*tasks, return_exceptions=True)

        total = 0
        for idx, page in enumerate(pages):
            if isinstance(page, Exception):
                print(f"[CUPS][ERR] page {idx} error: {page}")
                continue
            data = page.get('data') or page.get('content') or []
            print(f"[CUPS][PAGE] {idx} data_count={len(data)} keys={list(page.keys())[:5]}")
            total += len(data)
            for fixture in data:
                # Period may be 'FullTime' for played matches
                period = fixture.get('period')
                if isinstance(period, str) and period.lower() == 'fulltime':
                    continue
                home_name = (fixture.get('homeTeam') or {}).get('name')
                away_name = (fixture.get('awayTeam') or {}).get('name')
                if not home_name or not away_name:
                    continue
                home_short = team_name_to_short.get(home_name)
                away_short = team_name_to_short.get(away_name)
                # Only create entries for PL teams so the CUP column appears only when relevant
                if not home_short and not away_short:
                    continue
                kickoff_str = fixture.get('kickoff')
                if not kickoff_str:
                    continue
                try:
                    kickoff_time = datetime.strptime(kickoff_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
                except Exception:
                    # Fallback: use date portion
                    try:
                        kickoff_time = datetime.strptime(kickoff_str.split(' ')[0], '%Y-%m-%d').replace(tzinfo=timezone.utc)
                    except Exception:
                        continue
                gw_map = next((event['id'] for event in bootstrap['events'] if datetime.fromisoformat(event['deadline_time'].replace('Z', '+00:00')) > kickoff_time), None)
                if not gw_map or not (start_gw <= gw_map <= end_gw):
                    continue
                comp_id = fixture.get('competitionId') or (fixture.get('competition') and fixture['competition'].get('id'))
                cup_name = next((name for name, cid in COMPETITION_IDS.items() if cid == int(comp_id) and name != 'PL'), None) if comp_id else None
                if not cup_name:
                    continue
                if home_short:
                    cup_fixture_buckets[gw_map].append({
                        'team': home_short,
                        'opponent': (away_short or abbreviate_team_name(away_name)),
                        'opponent_full': away_name,
                        'is_home': True,
                        'competition': cup_name
                    })
                if away_short:
                    cup_fixture_buckets[gw_map].append({
                        'team': away_short,
                        'opponent': (home_short or abbreviate_team_name(home_name)),
                        'opponent_full': home_name,
                        'is_home': False,
                        'competition': cup_name
                    })
        print(f"[CUPS][RESP] total_matches={total}")
        print(f"[CUPS][BUCKETS] gw_keys={sorted(cup_fixture_buckets.keys())} sizes={[len(v) for k,v in sorted(cup_fixture_buckets.items())]}")

    team_positions = {team['short_name']: team['position'] for team in bootstrap['teams']}

    if sort_method == "table":
        sorted_teams = sorted(fixture_data.keys(), key=lambda x: team_positions.get(x, 999))
    elif sort_method == "fdr":
        def team_fdr_score(team_key):
            fixtures = fixture_data[team_key]
            # Treat blanks (0) as neutral difficulty 3 to avoid unfairly favoring blanks
            return sum(f.get('fdr') if f.get('fdr') else 3 for f in fixtures)
        sorted_teams = sorted(fixture_data.keys(), key=lambda t: (team_fdr_score(t), t))
    else:
        sorted_teams = sorted(fixture_data.keys())

    fixture_data = {team: fixture_data[team] for team in sorted_teams}
    
    gw_dates = {event['id']: datetime.fromisoformat(event['deadline_time'].replace('Z', '+00:00')).strftime("%d/%m")
                for event in bootstrap['events'] if start_gw <= event['id'] <= end_gw}
                
    return fixture_data, start_gw, actual_gameweeks, {v['short']: v['name'] for v in filtered_teams.values()}, gw_dates, cup_fixture_buckets

# Function to create fixture grid
def create_fixture_grid(fixture_data, num_gameweeks, start_gw, team_names, gw_dates, sort_method, team_positions, team_points, cup_fixture_buckets):
    cell_width, cell_height = 100, 30
    team_column_width = 120
    position_column_width = 40 if sort_method == "table" else 0
    points_column_width = 40 if sort_method == "table" else 0
    spacing = 10
    padding = 20
    header_height_small = 25  # Height for Pos, Club, Pts headers
    header_height_large = 50  # Height for GW headers
    gap_height = 10  # Gap between headers and data
    
    # Calculate total number of columns including cup fixtures
    total_columns = num_gameweeks + sum(1 for gw in range(start_gw, start_gw + num_gameweeks) if gw in cup_fixture_buckets)
    
    width = padding * 2 + position_column_width + team_column_width + points_column_width + spacing + (cell_width * total_columns)
    height = padding * 2 + header_height_large + gap_height + (cell_height * len(fixture_data))
    image = Image.new('RGB', (width, height), color='white')
    draw = ImageDraw.Draw(image)
    
    font = ImageFont.truetype("arial.ttf", 16)
    bold_font = ImageFont.truetype("arialbd.ttf", 16)
    header_font = ImageFont.truetype("arialbd.ttf", 16)
    date_font = ImageFont.truetype("arial.ttf", 14)
    cup_font = ImageFont.truetype("arial.ttf", 12)  # slightly smaller for CUP cells
    cup_bold_font = ImageFont.truetype("arialbd.ttf", 12)
    
    # Draw headers for position, club, and points columns only if sort_method is "table"
    if sort_method == "table":
        draw.rectangle([padding, padding + header_height_large - header_height_small, padding + position_column_width, padding + header_height_large], outline='black')
        draw.text((padding + position_column_width/2, padding + header_height_large - 5), "Pos", font=header_font, fill='black', anchor="mb")
        
        draw.rectangle([padding + position_column_width + team_column_width, padding + header_height_large - header_height_small, padding + position_column_width + team_column_width + points_column_width, padding + header_height_large], outline='black')
        draw.text((padding + position_column_width + team_column_width + points_column_width/2, padding + header_height_large - 5), "Pts", font=header_font, fill='black', anchor="mb")
    
    # Draw club header
    draw.rectangle([padding + position_column_width, padding + header_height_large - header_height_small, padding + position_column_width + team_column_width, padding + header_height_large], outline='black')
    draw.text((padding + position_column_width + 5, padding + header_height_large - 5), "Club", font=header_font, fill='black', anchor="lb")
    
    # Draw headers and dates for gameweeks and cup fixtures
    column = 0
    for i in range(num_gameweeks):
        gw = start_gw + i
        x = padding + position_column_width + team_column_width + points_column_width + spacing + column * cell_width
        draw.rectangle([x, padding, x + cell_width, padding + header_height_large], outline='black')
        draw.text((x + cell_width/2, padding + 10), gw_dates.get(gw, ""), font=date_font, fill='black', anchor="mt")
        draw.text((x + cell_width/2, padding + header_height_large - 10), f"GW{gw}", font=header_font, fill='black', anchor="mb")
        column += 1
        
        if gw in cup_fixture_buckets:
            x = padding + position_column_width + team_column_width + points_column_width + spacing + column * cell_width
            draw.rectangle([x, padding, x + cell_width, padding + header_height_large], fill='lightblue', outline='black')
            draw.text((x + cell_width/2, padding + header_height_large/2), "CUP", font=header_font, fill='black', anchor="mm")
            column += 1
    
    # Draw team names, positions, points, and fixtures
    for i, (team_short, fixtures) in enumerate(fixture_data.items()):
        y = padding + header_height_large + gap_height + i*cell_height
        team_full = team_names[team_short]
        
        # Draw position (in bold) only if sort_method is "table"
        if sort_method == "table":
            draw.rectangle([padding, y, padding + position_column_width, y + cell_height], outline='black')
            draw.text((padding + position_column_width/2, y + cell_height/2), str(team_positions.get(team_short, '')), font=bold_font, fill='black', anchor="mm")
        
        # Draw team name (in bold)
        draw.rectangle([padding + position_column_width, y, padding + position_column_width + team_column_width, y + cell_height], outline='black')
        draw.text((padding + position_column_width + 5, y + cell_height/2), team_full, font=bold_font, fill='black', anchor="lm")
        
        # Draw points (in bold) only if sort_method is "table"
        if sort_method == "table":
            draw.rectangle([padding + position_column_width + team_column_width, y, padding + position_column_width + team_column_width + points_column_width, y + cell_height], outline='black')
            draw.text((padding + position_column_width + team_column_width + points_column_width/2, y + cell_height/2), str(team_points.get(team_short, '')), font=bold_font, fill='black', anchor="mm")
        
        column = 0
        for j in range(num_gameweeks):
            gw = start_gw + j
            x = padding + position_column_width + team_column_width + points_column_width + spacing + column * cell_width
            
            # Draw league fixture
            if j < len(fixtures):
                fixture = fixtures[j]
                color = get_fixture_color(fixture)
                draw.rectangle([x, y, x + cell_width, y + cell_height], fill=color, outline='black')
                
                is_home = fixture['opponent'].isupper()
                text_font = bold_font if is_home else font
                
                draw.text((x + cell_width/2, y + cell_height/2), fixture['opponent'], font=text_font, fill='black', anchor="mm")
            else:
                draw.rectangle([x, y, x + cell_width, y + cell_height], fill='white', outline='black')
            
            column += 1
            
            # Draw cup fixture if exists
            if gw in cup_fixture_buckets:
                x = padding + position_column_width + team_column_width + points_column_width + spacing + column * cell_width
                
                cup_fixture = next((f for f in cup_fixture_buckets[gw] if f['team'] == team_short), None)
                if cup_fixture:
                    cup_color = CUP_COLORS.get(cup_fixture['competition'], 'lightblue')  # Default to lightblue if competition not found
                    draw.rectangle([x, y, x + cell_width, y + cell_height], fill=cup_color, outline='black')
                    
                    # Use full opponent name if available; otherwise use existing opponent text
                    opponent_key = cup_fixture.get('opponent_full') or cup_fixture['opponent']
                    display_text = opponent_key
                    text_font = cup_bold_font if cup_fixture['is_home'] else cup_font
                    
                    # Determine text color based on background color brightness
                    bg_color = ImageColor.getrgb(cup_color)
                    brightness = (bg_color[0] * 299 + bg_color[1] * 587 + bg_color[2] * 114) / 1000
                    text_color = 'black' if brightness > 128 else 'white'
                    
                    # Wrap into up to two lines within the cell
                    max_text_width = cell_width - 8
                    line1, line2 = wrap_text_to_two_lines(draw, display_text, text_font, max_text_width)
                    if line2:
                        ascent, descent = text_font.getmetrics()
                        line_height = ascent + descent
                        gap_px = max(1, int(line_height * 0.15))
                        total_h = line_height * 2 + gap_px
                        top_y = y + (cell_height - total_h) / 2
                        y1 = top_y + line_height / 2
                        y2 = y1 + line_height + gap_px
                        draw.text((x + cell_width/2, y1), line1, font=text_font, fill=text_color, anchor="mm")
                        draw.text((x + cell_width/2, y2), line2, font=text_font, fill=text_color, anchor="mm")
                    else:
                        fitted = fit_text_to_width(draw, line1, text_font, max_text_width)
                        draw.text((x + cell_width/2, y + cell_height/2), fitted, font=text_font, fill=text_color, anchor="mm")
                else:
                    draw.rectangle([x, y, x + cell_width, y + cell_height], fill='lightblue', outline='black')
                
                column += 1
    
    # Draw gridlines for fixture columns only
    for i in range(total_columns + 1):
        x = padding + position_column_width + team_column_width + points_column_width + spacing + i*cell_width
        draw.line([(x, padding + header_height_large + gap_height), (x, height - padding)], fill='black', width=1)
    
    # Draw horizontal gridlines for team rows only, starting below the first team
    for i in range(1, len(fixture_data) + 1):
        y = padding + header_height_large + gap_height + i*cell_height
        draw.line([(padding, y), (padding + position_column_width + team_column_width + points_column_width, y)], fill='black', width=1)
        draw.line([(padding + position_column_width + team_column_width + points_column_width + spacing, y), (width - padding, y)], fill='black', width=1)
    
    # Draw vertical lines for position and points columns, but not connecting to the header boxes
    draw.line([(padding + position_column_width, padding + header_height_large + gap_height), (padding + position_column_width, height - padding)], fill='black', width=1)
    draw.line([(padding + position_column_width + team_column_width, padding + header_height_large + gap_height), (padding + position_column_width + team_column_width, height - padding)], fill='black', width=1)
    
    return image

# Function to get fixture color
def get_fixture_color(fixture):
    if not fixture['opponent']:
        return 'lightgrey'
    fdr = fixture['fdr']
    if fdr == 1:
        return '#375523'  # Dark Green
    elif fdr == 2:
        return '#01FC7A'  # Light Green
    elif fdr == 3:
        return '#E7E7E7'  # Grey
    elif fdr == 4:
        return '#FF1751'  # Light Red
    else:
        return '#80072D'  # Dark Red
    
# Helper function to get text color based on FDR (white for FDR with red background - 4 or higher)
def get_text_color(fixture):
    if fixture['fdr'] >= 4:
        return 'white'
    return 'black'

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
def fit_text_to_width(draw, text: str, font, max_width: int) -> str:
    if draw.textlength(text, font=font) <= max_width:
        return text
    ellipsis = '…'
    # Binary search for the longest prefix that fits
    lo, hi = 0, len(text)
    best = ''
    while lo <= hi:
        mid = (lo + hi) // 2
        candidate = text[:mid] + ellipsis
        if draw.textlength(candidate, font=font) <= max_width:
            best = candidate
            lo = mid + 1
        else:
            hi = mid - 1
    return best if best else (text[:1] + ellipsis)

# Wrap text into up to two lines within max width. Second line may be ellipsized.
def wrap_text_to_two_lines(draw, text: str, font, max_width: int):
    if draw.textlength(text, font=font) <= max_width:
        return text, ''
    tokens = text.split()
    if len(tokens) == 1:
        # No spaces to wrap; fall back to ellipsis on one line
        return fit_text_to_width(draw, text, font, max_width), ''
    line1_tokens = []
    for token in tokens:
        test = (' '.join(line1_tokens + [token])).strip()
        if draw.textlength(test, font=font) <= max_width:
            line1_tokens.append(token)
        else:
            break
    if not line1_tokens:
        # First token alone doesn't fit; ellipsize single-line
        return fit_text_to_width(draw, tokens[0], font, max_width), ''
    line1 = ' '.join(line1_tokens)
    remaining = ' '.join(tokens[len(line1_tokens):]).strip()
    if not remaining:
        return line1, ''
    line2 = fit_text_to_width(draw, remaining, font, max_width)
    return line1, line2

# Command to get schedule
@bot.command()
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
@bot.command()
async def link(ctx, fpl_id: int = None):
    if fpl_id is None:
        await ctx.send("Please provide your FPL ID. Usage: !link <your_fpl_id>")
        return

    try:
        # Fetch user data from FPL API
        user_data = await fetch_fpl_data(f"entry/{fpl_id}/")
        team_name = user_data['name']

        async with aiosqlite.connect('fpl_users.db') as db:
            await db.execute('''
                INSERT OR REPLACE INTO users (discord_id, fpl_id, team_name)
                VALUES (?, ?, ?)
            ''', (ctx.author.id, fpl_id, team_name))
            await db.commit()

        await ctx.send(f"Successfully linked your Discord account to FPL team: {team_name}")
    except Exception as e:
        print(f"An error occurred: {str(e)}")
        await ctx.send("An error occurred while linking your account. Please check your FPL ID and try again.")

# Error handler for MissingRequiredArgument
@link.error
async def link_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("Please provide your FPL ID. Usage: !link <your_fpl_id>")

# Command to get my team
@bot.command()
async def myteam(ctx):
    try:
        async with aiosqlite.connect('fpl_users.db') as db:
            async with db.execute('SELECT fpl_id, team_name FROM users WHERE discord_id = ?', (ctx.author.id,)) as cursor:
                result = await cursor.fetchone()

        if result:
            fpl_id, team_name = result
            await ctx.send(f"Your linked FPL team is: {team_name} (ID: {fpl_id})")
        else:
            await ctx.send("You haven't linked an FPL team yet. Use the !link command to link your team.")
    except Exception as e:
        print(f"An error occurred: {str(e)}")
        await ctx.send("An error occurred while fetching your team information.")

# Command to get my points
@bot.command()
async def mypoints(ctx):
    try:
        async with aiosqlite.connect('fpl_users.db') as db:
            async with db.execute('SELECT fpl_id FROM users WHERE discord_id = ?', (ctx.author.id,)) as cursor:
                result = await cursor.fetchone()

        if result:
            fpl_id = result[0]
            user_data = await fetch_fpl_data(f"entry/{fpl_id}/")
            total_points = user_data['summary_overall_points']
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

# Function to create leaderboard image
def create_leaderboard_image(standings):
    width, height = 1300, 70 + len(standings) * 60
    image = Image.new('RGB', (width, height), color='white')
    draw = ImageDraw.Draw(image)
    
    font_regular = ImageFont.load_default().font_variant(size=24)
    font_bold = ImageFont.load_default().font_variant(size=24)
    font_header = ImageFont.load_default().font_variant(size=28)
    
    # Define column widths
    rank_width = 90
    team_width = 450
    gw_width = 90
    tot_width = 90
    value_width = 100
    or_width = 100
    
    # Define column widths and positions
    rank_center = rank_width // 2
    team_start = rank_width + 20
    gw_center = width - or_width - value_width - tot_width - gw_width // 2
    tot_center = width - or_width - value_width - tot_width // 2
    value_center = width - or_width - value_width // 2
    or_center = width - or_width // 2
    
    # Adjust header vertical position
    header_y = 40  # Moved down from 20
    
    # Draw headers
    draw.text((rank_center, header_y), "Rank", font=font_header, fill='black', anchor="mm")
    draw.text((team_start, header_y), "Team & Manager", font=font_header, fill='black', anchor="lm")
    draw.text((gw_center, header_y), "GW", font=font_header, fill='black', anchor="mm")
    draw.text((tot_center, header_y), "TOT", font=font_header, fill='black', anchor="mm")
    draw.text((value_center, header_y), "Value", font=font_header, fill='black', anchor="mm")
    draw.text((or_center, header_y), "OR", font=font_header, fill='black', anchor="mm")
    
    # Draw header underline (moved closer to headers)
    draw.line([(0, header_y + 25), (width, header_y + 25)], fill='black', width=2)
    
    def draw_slightly_bold_text(x, y, text, font, fill='black'):
        # Draw the text twice with a slight offset for a slightly bolder effect
        draw.text((x, y), text, font=font, fill=fill, anchor="lm")
        draw.text((x+1, y), text, font=font, fill=fill, anchor="lm")
    
    # Adjust the starting y-coordinate for the standings
    standings_start_y = header_y + 35
    
    # Draw standings
    for i, entry in enumerate(standings):
        y = standings_start_y + i * 60
        row_center = y + 30
        
        # Calculate positions for rank and indicator
        rank_text_width = draw.textlength(str(entry['rank']), font=font_regular)
        indicator_width = 20
        total_width = rank_text_width + indicator_width + 5  # 5 px spacing
        start_x = rank_center - total_width // 2
        
        # Draw rank
        draw.text((start_x, row_center), str(entry['rank']), font=font_regular, fill='black', anchor="lm")
        
        # Draw arrow or indicator
        indicator_x = start_x + rank_text_width + 5
        indicator_y = row_center
        if entry['rank'] < entry['last_rank']:
            draw.polygon([(indicator_x, indicator_y + 6), (indicator_x + 10, indicator_y - 6), (indicator_x + 20, indicator_y + 6)], fill='green')
        elif entry['rank'] > entry['last_rank']:
            draw.polygon([(indicator_x, indicator_y - 6), (indicator_x + 10, indicator_y + 6), (indicator_x + 20, indicator_y - 6)], fill='red')
        else:
            draw.rectangle([(indicator_x, indicator_y - 4), (indicator_x + 20, indicator_y + 4)], fill='grey')
        
        # Draw team name (slightly bold) and manager name (regular)
        draw_slightly_bold_text(team_start, row_center - 12, entry.get('entry_name', 'Unknown'), font_bold)
        draw.text((team_start, row_center + 12), entry.get('player_name', 'Unknown'), font=font_regular, fill='black', anchor="lm")
        
        # Draw GW and TOT scores
        draw.text((gw_center, row_center), str(entry.get('event_total', 'N/A')), font=font_regular, fill='black', anchor="mm")
        draw.text((tot_center, row_center), str(entry.get('total', 'N/A')), font=font_regular, fill='black', anchor="mm")
        
        # Draw Team Value
        team_value = entry.get('value', 0) / 10  # Assuming value is in tenths of millions
        draw.text((value_center, row_center), f"{team_value:.1f}m", font=font_regular, fill='black', anchor="mm")
        
        # Draw Overall Rank
        overall_rank = entry.get('overall_rank', 'N/A')
        if isinstance(overall_rank, int):
            if overall_rank >= 1000000:
                overall_rank_text = f"{overall_rank/1000000:.1f}M"
            elif overall_rank >= 1000:
                overall_rank_text = f"{overall_rank/1000:.1f}K"
            else:
                overall_rank_text = f"{overall_rank}"
        else:
            overall_rank_text = str(overall_rank)
        draw.text((or_center, row_center), overall_rank_text, font=font_regular, fill='black', anchor="mm")
        
        # Draw row separator
        draw.line([(0, y + 59), (width, y + 59)], fill='lightgray', width=1)
    
    img_byte_arr = io.BytesIO()
    image.save(img_byte_arr, format='PNG')
    img_byte_arr.seek(0)
    return img_byte_arr

# Command to get league standings as a leaderboard image
@bot.command()
async def leaderboard(ctx):
    try:
        async with aiosqlite.connect('fpl_users.db') as db:
            async with db.execute('SELECT league_id FROM leagues WHERE guild_id = ?', (ctx.guild.id,)) as cursor:
                result = await cursor.fetchone()
        
        if result:
            league_id = result[0]
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
@bot.command()
async def set_league(ctx, league_id: int):
    try:
        async with aiosqlite.connect('fpl_users.db') as db:
            await db.execute('INSERT OR REPLACE INTO leagues (guild_id, league_id) VALUES (?, ?)', (ctx.guild.id, league_id))
            await db.commit()
        await ctx.send(f"League ID set to {league_id}")
    except Exception as e:
        print(f"An error occurred: {str(e)}")
        await ctx.send("An error occurred while setting the league ID.")

# Command to get league ID
@bot.command()
async def get_league(ctx):
    try:
        async with aiosqlite.connect('fpl_users.db') as db:
            async with db.execute('SELECT league_id FROM leagues WHERE guild_id = ?', (ctx.guild.id,)) as cursor:
                result = await cursor.fetchone()
        if result:
            await ctx.send(f"The current league ID is {result[0]}")
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