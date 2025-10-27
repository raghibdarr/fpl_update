import asyncio
from typing import List, Tuple
import discord
from discord.ext import commands, tasks

from repos.db_repo import (
    upsert_live_subscription,
    remove_live_subscription,
    get_all_live_subscriptions,
)
from services.live_service import (
    fetch_current_gw,
    fetch_fixtures_for_gw,
    fetch_bootstrap_maps,
    fetch_live_points_map,
    extract_fixture_deltas,
    pair_scorers_assisters,
    compute_defcon_threshold_hits,
    format_event_message,
    maybe_emit_bonus_when_finished,
)


POLL_SECONDS = 60


class LiveCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._bootstrap = None  # type: ignore
        self._gw_cache = None
        # Start background loop lazily; we only start once someone subscribes
        self._loop_started = False

    @commands.hybrid_command(name="live_subscribe", description="Post live FPL match updates in this channel")
    async def live_subscribe(self, ctx: commands.Context):
        await upsert_live_subscription(ctx.guild.id, ctx.channel.id)  # type: ignore
        await ctx.send(f"Live updates will be posted in {ctx.channel.mention}")
        if not self._loop_started:
            self._loop.start()
            self._loop_started = True

    @commands.hybrid_command(name="live_unsubscribe", description="Stop live FPL match updates in this guild")
    async def live_unsubscribe(self, ctx: commands.Context):
        await remove_live_subscription(ctx.guild.id)  # type: ignore
        await ctx.send("Live updates unsubscribed for this guild.")

    @tasks.loop(seconds=POLL_SECONDS)
    async def _loop(self):
        try:
            subs: List[Tuple[int, int]] = await get_all_live_subscriptions()
            if not subs:
                return

            gw = await fetch_current_gw()
            if gw is None:
                return

            if self._bootstrap is None or self._gw_cache != gw:
                self._bootstrap = await fetch_bootstrap_maps()
                self._gw_cache = gw

            elements_by_id, teams_by_id = self._bootstrap
            fixtures = await fetch_fixtures_for_gw(gw)
            if not fixtures:
                return

            live_points = await fetch_live_points_map(gw)

            for fx in fixtures:
                # Treat as live while started and not finished_provisional
                if not fx.get("started") or fx.get("finished_provisional"):
                    # If just finished, maybe emit bonus once
                    bonus_msg = await maybe_emit_bonus_when_finished(fx, elements_by_id)
                    if bonus_msg:
                        for _, channel_id in subs:
                            ch = self.bot.get_channel(channel_id)
                            if ch:
                                await ch.send(bonus_msg)
                    continue

                deltas = await extract_fixture_deltas(fx)
                if deltas:
                    paired = pair_scorers_assisters(deltas)
                    msgs = []
                    for item in paired:
                        msg = format_event_message(
                            item=item,
                            fixture=fx,
                            elements_by_id=elements_by_id,
                            teams_by_id=teams_by_id,
                            live_points=live_points,
                        )
                        if msg:
                            msgs.append(msg)
                    if msgs:
                        for _, channel_id in subs:
                            ch = self.bot.get_channel(channel_id)
                            if ch:
                                for m in msgs:
                                    await ch.send(m)

                # DefCon thresholds via Pulse
                dc_msgs = await compute_defcon_threshold_hits(fx, elements_by_id, teams_by_id, gw)
                if dc_msgs:
                    for _, channel_id in subs:
                        ch = self.bot.get_channel(channel_id)
                        if ch:
                            for m in dc_msgs:
                                await ch.send(m)
        except Exception as e:
            print(f"[live_loop] error: {e}")


async def setup(bot: commands.Bot):
    await bot.add_cog(LiveCommands(bot))


