import io
import discord
from discord.ext import commands

from repos.db_repo import get_league_id_for_guild
from services.league_service import fetch_league_standings
from utils.image_generator import create_leaderboard_image


class LeagueCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(name="leaderboard", description="Show league leaderboard image")
    async def leaderboard(self, ctx: commands.Context):
        try:
            league_id = await get_league_id_for_guild(ctx.guild.id)
            if league_id is not None:
                await ctx.send("Fetching leaderboard data... This may take a moment.")
                standings = await fetch_league_standings(league_id)
                image = create_leaderboard_image(standings)
                if image is None:
                    await ctx.send("An error occurred while creating the leaderboard image. Check the console for details.")
                    return
                await ctx.send(file=discord.File(fp=image, filename='leaderboard.png'))
            else:
                await ctx.send("No league has been set. Use !set_league command to set a league ID.")
        except Exception as e:
            await ctx.send(f"An error occurred while fetching the leaderboard: {str(e)}")


async def setup(bot: commands.Bot):
    await bot.add_cog(LeagueCommands(bot))


