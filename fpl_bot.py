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

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Base URL for the FPL API
FPL_API_BASE = "https://fantasy.premierleague.com/api/"

# Function to fetch data from the FPL API
async def fetch_fpl_data(endpoint):
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{FPL_API_BASE}{endpoint}") as response:
            return await response.json()

@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')
    print(f'Bot is in {len(bot.guilds)} guilds')

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

        def get_fdr_color(fdr):
            colors = {1: Color.dark_green(), 2: Color.green(), 3: Color.light_grey(), 
                      4: Color.red(), 5: Color.dark_red()}
            return colors.get(fdr, Color.light_grey())

        embeds = []

        if team_name:
            team_id = next((team['id'] for team in teams_data['teams'] 
                            if team['name'].lower() == team_name.lower()), None)
            if team_id is None:
                await ctx.send(f"Team '{team_name}' not found. Please check the spelling.")
                return

            current_time = datetime.now(timezone.utc)

            upcoming_fixtures = [
                fixture for fixture in fixtures_data
                if datetime.strptime(fixture['kickoff_time'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc) > current_time
            ]

            # Use upcoming_fixtures instead of fixtures_data
            team_fixtures = [f for f in upcoming_fixtures if f['team_h'] == team_id or f['team_a'] == team_id]
            team_fixtures.sort(key=lambda x: x['event'])

            title_embed = Embed(title=f"Upcoming fixtures for {team_name}", color=Color.blue())
            embeds.append(title_embed)

            for fixture in team_fixtures[:5]:
                is_home = fixture['team_h'] == team_id
                opponent = team_map[fixture['team_a' if is_home else 'team_h']]['name']
                fdr = fixture['team_h_difficulty' if is_home else 'team_a_difficulty']
                gw = fixture['event']
                kickoff_time = datetime.strptime(fixture['kickoff_time'], "%Y-%m-%dT%H:%M:%SZ")
                formatted_time = kickoff_time.strftime("%d %b %H:%M")
                fixture_text = f"GW{gw} - {formatted_time} - {'(H)' if is_home else '(A)'} vs {opponent} - FDR: {fdr}"
                
                embed = Embed(description=fixture_text, color=get_fdr_color(fdr))
                embeds.append(embed)

        else:
            next_gw = current_gw + 1
            next_gw_fixtures = [f for f in fixtures_data if f['event'] == next_gw]
            next_gw_fixtures.sort(key=lambda x: x['kickoff_time'])

            title_embed = Embed(title=f"Fixtures for Gameweek {next_gw}", color=Color.blue())
            embeds.append(title_embed)

            for fixture in next_gw_fixtures:
                home_team = team_map[fixture['team_h']]['name']
                away_team = team_map[fixture['team_a']]['name']
                home_fdr = fixture['team_h_difficulty']
                away_fdr = fixture['team_a_difficulty']
                kickoff_time = datetime.strptime(fixture['kickoff_time'], "%Y-%m-%dT%H:%M:%SZ")
                formatted_time = kickoff_time.strftime("%d %b %Y %H:%M")
                fixture_text = f"{formatted_time}\n{home_team} vs {away_team}\nHome FDR: {home_fdr} | Away FDR: {away_fdr}"
                
                embed = Embed(description=fixture_text, color=get_fdr_color(min(home_fdr, away_fdr)))
                embeds.append(embed)

        if embeds:
            await ctx.send(embeds=embeds)
        else:
            await ctx.send("No fixtures found.")

    except Exception as e:
        print(f"An error occurred: {str(e)}")
        await ctx.send(f"An error occurred while fetching fixtures. Please try again later.")

print("Registering commands...")
print(f"Registered commands: {[command.name for command in bot.commands]}")
bot.run(TOKEN)
