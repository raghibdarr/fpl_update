import io
import discord
from discord.ext import commands
from discord import Embed, Color, app_commands
from datetime import datetime, timezone
from collections import defaultdict

from utils.api_helpers import fetch_fpl_data
from utils.image_generator import create_fixture_grid, create_table_image
from services.user_service import build_myteam_image, fetch_user_team_name
from utils.colors import get_fdr_color
from services.fixtures_service import fetch_fixture_data
from data.team_aliases import team_aliases


class FPLCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(name="table", description="Show the Premier League table")
    async def table(self, ctx: commands.Context):
        try:
            data = await fetch_fpl_data("bootstrap-static/")
            sorted_teams = sorted(data['teams'], key=lambda x: x['position'])
            image = create_table_image(sorted_teams)
            img_byte_arr = io.BytesIO()
            image.save(img_byte_arr, format='PNG')
            img_byte_arr.seek(0)
            await ctx.send(file=discord.File(fp=img_byte_arr, filename='table.png'))
        except Exception as e:
            await ctx.send(f"An error occurred: {str(e)}")

    @commands.hybrid_command(name="fixtures", description="Show fixture grid")
    async def fixtures(self, ctx: commands.Context, *, args: str = ""):
        params = args.split()
        num_gameweeks = 6
        teams = []
        sort_method = "alphabetical"
        start_gw = None
        end_gw = None
        show_cups = False

        for param in params:
            if param.lower().startswith("gw"):
                gw = int(param[2:])
                if start_gw is None:
                    start_gw = gw
                else:
                    end_gw = gw
            elif param.isdigit():
                if start_gw is None:
                    num_gameweeks = min(int(param), 38)
            elif param.lower() in ["fdr", "alphabetical", "table"]:
                sort_method = param.lower()
            elif param.lower() == "cups":
                show_cups = True
            else:
                teams.extend(param.strip().rstrip(',').lower().split(','))

        teams = [team.strip() for team in teams if team.strip()]

        multi_word_teams = [name.lower() for name in team_aliases.keys() if ' ' in name]
        for multi_word_team in multi_word_teams:
            words = multi_word_team.split()
            if all(word in teams for word in words):
                for word in words:
                    teams.remove(word)
                teams.append(multi_word_team)

        if start_gw is not None:
            if end_gw is None:
                end_gw = 38
            num_gameweeks = end_gw - start_gw + 1

        num_gameweeks = min(num_gameweeks, 38)

        await ctx.send("Generating fixture grid... This may take a moment.")
        try:
            fixture_data, actual_start_gw, actual_gameweeks, team_names, gw_dates, cup_fixture_buckets = await fetch_fixture_data(num_gameweeks, teams, sort_method, start_gw, show_cups)
            if not fixture_data:
                await ctx.send("No valid teams found. Please check your team names and try again.")
                return

            team_positions = {}
            team_points = {}
            if sort_method == "table":
                data = await fetch_fpl_data("bootstrap-static/")
                for team in data['teams']:
                    team_positions[team['short_name']] = team['position']
                    team_points[team['short_name']] = team['points']

            image = create_fixture_grid(fixture_data, actual_gameweeks, actual_start_gw, team_names, gw_dates, sort_method, team_positions, team_points, cup_fixture_buckets)
            img_byte_arr = io.BytesIO()
            image.save(img_byte_arr, format='PNG')
            img_byte_arr.seek(0)
            await ctx.send(file=discord.File(fp=img_byte_arr, filename='fixtures.png'))
        except Exception as e:
            await ctx.send(f"An error occurred: {str(e)}")

    @commands.hybrid_command(name="schedule", description="Show upcoming fixtures for a team or next GW")
    async def schedule(self, ctx: commands.Context, *, team_name: str | None = None):
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
                    team_id = next((team['id'] for team in teams_data['teams'] if team['name'] == matched_team), None)
                else:
                    await ctx.send(f"Team '{team_name}' not found. Please check the spelling.")
                    return

                if team_id is None:
                    await ctx.send(f"Error: Unable to find team ID for {matched_team}. Please try again later.")
                    return

                current_time = datetime.now(timezone.utc)
                upcoming_fixtures = [fixture for fixture in fixtures_data if datetime.strptime(fixture['kickoff_time'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc) > current_time]
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
                    unix_timestamp = int(kickoff_time.timestamp())
                    discord_timestamp = f"<t:{unix_timestamp}:R> (<t:{unix_timestamp}:f>)"
                    fixture_text = f"GW{gw} - {discord_timestamp} - {'(H)' if is_home else '(A)'} vs {opponent} - FDR: {fdr}"
                    embed = Embed(description=fixture_text, color=get_fdr_color(fdr))
                    embeds.append(embed)

                await ctx.send(embeds=embeds)
            else:
                upcoming_fixtures = [f for f in fixtures_data if f['event'] == current_gw + 1]
                upcoming_fixtures.sort(key=lambda x: x['kickoff_time'])
                fixtures_by_day = defaultdict(list)
                for fixture in upcoming_fixtures:
                    kickoff_time = datetime.strptime(fixture['kickoff_time'], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                    day_key = kickoff_time.strftime("%A, %d %B %Y")
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
                    day_fixtures = "\n".join(fixture_strings)
                    embed.add_field(name=f"**{day}**", value=day_fixtures, inline=False)

                await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(f"An error occurred while fetching fixtures. Please try again later.")


    @commands.hybrid_command(name="showteam", description="Render a team's current GW squad image by FPL entry ID")
    async def showteam(self, ctx: commands.Context, fpl_id: int):
        await ctx.defer()
        try:
            team_name = None
            try:
                team_name = await fetch_user_team_name(fpl_id)
            except Exception:
                pass
            img = await build_myteam_image(fpl_id, team_name)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            buf.seek(0)
            await ctx.send(file=discord.File(buf, filename=f"team_{fpl_id}.png"))
        except Exception as e:
            await ctx.send(f"Failed to render team {fpl_id}: {e}")


async def setup(bot: commands.Bot):
    await bot.add_cog(FPLCommands(bot))