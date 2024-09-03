import discord
from discord.ext import commands
import aiohttp
import asyncio
from fuzzywuzzy import process
import difflib
from datetime import datetime, timezone
from discord import Embed, Color
import os
from dotenv import load_dotenv
from collections import defaultdict
import aiosqlite
from PIL import Image, ImageDraw, ImageFont
import io

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

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
    "Man Utd": ["manchester united", "man united", "united", "mun", 'utd', 'man utd', "mufc", "mu", "red devils", "reddevils", "the red devils", "the reddevils"],
    "Newcastle": ["newcastle", "newcastle united", "new", 'nufc', 'newcastle', "magpies", "the magpies", "nufc", "newcastle utd", "newcastle united fc", "newcastle utd fc", "the magpies fc", "the magpies fc"],
    "Nott'm Forest": ["nottingham forest", "nottm forest", "forest", "nfo", "nottingham", "trouts", "forest fc", "nottingham forest fc", "nffc"],
    "Southampton": ["southampton", "saints", "sou", "southampton fc", "the saints", "saints fc", "sfc"],
    "Spurs": ["tottenham", "tottenham hotspur", "spurs", "tot", "thfc", "hotspurs", "spurs fc", "the spurs", "lilywhites", "the lilywhites", "spurs"],
    "West Ham": ["west ham", "west ham united", "whu", "hammers", "west ham united fc", "the hammers", "the irons", "irons", "whufc"],
    "Wolves": ["wolves", "wolverhampton", "wolverhampton wanderers", "wol", "wolves fc", "the wolves", "wolves", "wwfc"]
}

# Base URL for the FPL API
FPL_API_BASE = "https://fantasy.premierleague.com/api/"

# Function to fetch data from the FPL API
async def fetch_fpl_data(endpoint):
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{FPL_API_BASE}{endpoint}") as response:
            return await response.json()

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
    await setup_database()

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
async def fixtures(ctx, *, team_name=None):
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

async def fetch_league_standings(league_id):
    url = f"https://fantasy.premierleague.com/api/leagues-classic/{league_id}/standings/"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                raise Exception(f"API request failed with status {resp.status}")
            data = await resp.json()
    return data['standings']['results']

def create_leaderboard_image(standings):
    width, height = 800, 50 + len(standings) * 40
    image = Image.new('RGB', (width, height), color='white')
    draw = ImageDraw.Draw(image)
    
    # Use default font
    font = ImageFont.load_default()
    
    # Define column widths
    rank_width = 60
    team_width = 400
    gw_width = 60
    tot_width = 60
    
    # Draw headers
    draw.text((10, 15), "Rank", font=font, fill='black')
    draw.text((rank_width + 10, 15), "Team & Manager", font=font, fill='black')
    draw.text((width - tot_width - gw_width - 10, 15), "GW", font=font, fill='black')
    draw.text((width - tot_width + 10, 15), "TOT", font=font, fill='black')
    
    # Draw header underline
    draw.line([(0, 40), (width, 40)], fill='black', width=1)
    
    # Draw standings
    for i, entry in enumerate(standings):
        y = 50 + i * 40
        row_center = y + 20  # Center of the row
        
        # Draw rank
        draw.text((10, row_center - 6), str(entry['rank']), font=font, fill='black', anchor="lm")
        
        # Draw arrow
        arrow_y = row_center
        if entry['rank'] < entry['last_rank']:
            draw.polygon([(40, arrow_y - 5), (50, arrow_y + 5), (60, arrow_y - 5)], fill='green')  # Up arrow
        elif entry['rank'] > entry['last_rank']:
            draw.polygon([(40, arrow_y + 5), (50, arrow_y - 5), (60, arrow_y + 5)], fill='red')  # Down arrow
        
        # Draw team name and manager name
        draw.text((rank_width + 10, row_center - 10), entry['entry_name'], font=font, fill='black', anchor="lm")
        draw.text((rank_width + 10, row_center + 10), entry['player_name'], font=font, fill='black', anchor="lm")
        
        # Draw GW and TOT scores
        draw.text((width - tot_width - gw_width + 10, row_center), str(entry['event_total']), font=font, fill='black', anchor="mm")
        draw.text((width - tot_width + 20, row_center), str(entry['total']), font=font, fill='black', anchor="mm")
        
        # Draw row separator
        draw.line([(0, y + 39), (width, y + 39)], fill='lightgray', width=1)
    
    img_byte_arr = io.BytesIO()
    image.save(img_byte_arr, format='PNG')
    img_byte_arr.seek(0)
    return img_byte_arr

@bot.command()
async def leaderboard(ctx):
    try:
        async with aiosqlite.connect('fpl_users.db') as db:
            async with db.execute('SELECT league_id FROM leagues WHERE guild_id = ?', (ctx.guild.id,)) as cursor:
                result = await cursor.fetchone()
        
        if result:
            league_id = result[0]
            standings = await fetch_league_standings(league_id)
            image = create_leaderboard_image(standings)
            await ctx.send(file=discord.File(fp=image, filename='leaderboard.png'))
        else:
            await ctx.send("No league has been set. Use !set_league command to set a league ID.")
    except Exception as e:
        print(f"An error occurred: {str(e)}")
        await ctx.send("An error occurred while fetching the leaderboard.")

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

print("Registering commands...")
print(f"Registered commands: {[command.name for command in bot.commands]}")
bot.run(TOKEN)
