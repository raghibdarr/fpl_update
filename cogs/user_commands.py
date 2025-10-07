from discord.ext import commands

from repos.db_repo import upsert_user, get_user_by_discord_id, upsert_league, get_league_id_for_guild
from services.user_service import fetch_user_team_name, fetch_user_total_points


class UserCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command()
    async def link(self, ctx: commands.Context, fpl_id: int | None = None):
        if fpl_id is None:
            await ctx.send("Please provide your FPL ID. Usage: !link <your_fpl_id>")
            return
        try:
            team_name = await fetch_user_team_name(fpl_id)
            await upsert_user(ctx.author.id, fpl_id, team_name)
            await ctx.send(f"Successfully linked your Discord account to FPL team: {team_name}")
        except Exception:
            await ctx.send("An error occurred while linking your account. Please check your FPL ID and try again.")

    @commands.command()
    async def myteam(self, ctx: commands.Context):
        try:
            result = await get_user_by_discord_id(ctx.author.id)
            if result:
                fpl_id, team_name = result
                await ctx.send(f"Your linked FPL team is: {team_name} (ID: {fpl_id})")
            else:
                await ctx.send("You haven't linked an FPL team yet. Use the !link command to link your team.")
        except Exception:
            await ctx.send("An error occurred while fetching your team information.")

    @commands.command()
    async def mypoints(self, ctx: commands.Context):
        try:
            result = await get_user_by_discord_id(ctx.author.id)
            if result:
                fpl_id = result[0]
                total_points = await fetch_user_total_points(fpl_id)
                await ctx.send(f"Your total FPL points: {total_points}")
            else:
                await ctx.send("You haven't linked an FPL team yet. Use the !link command to link your team.")
        except Exception:
            await ctx.send("An error occurred while fetching your points.")

    @commands.command()
    async def set_league(self, ctx: commands.Context, league_id: int):
        try:
            await upsert_league(ctx.guild.id, league_id)
            await ctx.send(f"League ID set to {league_id}")
        except Exception:
            await ctx.send("An error occurred while setting the league ID.")

    @commands.command()
    async def get_league(self, ctx: commands.Context):
        try:
            league_id = await get_league_id_for_guild(ctx.guild.id)
            if league_id is not None:
                await ctx.send(f"The current league ID is {league_id}")
            else:
                await ctx.send("No league ID has been set. Use !set_league to set one.")
        except Exception:
            await ctx.send("An error occurred while fetching the league ID.")


async def setup(bot: commands.Bot):
    await bot.add_cog(UserCommands(bot))


