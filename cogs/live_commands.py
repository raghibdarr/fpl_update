import asyncio
from typing import List, Tuple
import discord
from discord.ext import commands, tasks

from repos.db_repo import (
    upsert_live_subscription,
    remove_live_subscription,
    get_all_live_subscriptions,
    get_bonus_sent,
    set_bonus_sent,
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
        # simple anti-spam: track last command timestamps per (guild, channel)
        self._last_subscribe_ts: dict[tuple[int, int], float] = {}
        self._last_unsubscribe_ts: dict[tuple[int, int], float] = {}

    @commands.hybrid_command(name="live_subscribe", description="Post live FPL match updates in this channel")
    async def live_subscribe(self, ctx: commands.Context):
        # anti-spam per (guild, channel)
        import time
        key = (ctx.guild.id, ctx.channel.id)  # type: ignore
        now = time.time()
        last = self._last_subscribe_ts.get(key, 0)
        if now - last < 60:
            await ctx.send("Please wait a minute before subscribing again.")
            return

        # If already subscribed, inform and return
        subs_raw = await get_all_live_subscriptions()
        if any((g == ctx.guild.id and c == ctx.channel.id) for (g, c, _ts) in subs_raw):  # type: ignore
            await ctx.send(f"This channel is already subscribed: {ctx.channel.mention}")
            self._last_subscribe_ts[key] = now
            return

        # store subscribe epoch seconds to avoid backfilling older finished fixtures
        ts = int(now)
        await upsert_live_subscription(ctx.guild.id, ctx.channel.id, ts)  # type: ignore
        # Pre-mark any already-finished fixtures in current GW as posted for this guild+channel so we don't backfill
        try:
            gw = await fetch_current_gw()
            if gw is not None:
                fixtures = await fetch_fixtures_for_gw(gw)
                for fx in fixtures:
                    if fx.get("finished_provisional"):
                        await set_bonus_sent(ctx.guild.id, ctx.channel.id, fx["id"], True)  # type: ignore
        except Exception as e:
            print(f"[live_subscribe] pre-mark finished error: {e}")
        await ctx.send(f"Live updates will be posted in {ctx.channel.mention}")
        self._last_subscribe_ts[key] = now
        if not self._loop_started:
            self._loop.start()
            self._loop_started = True

    @commands.hybrid_command(name="live_unsubscribe", description="Stop live FPL updates in this channel")
    async def live_unsubscribe(self, ctx: commands.Context):
        # anti-spam
        import time
        key = (ctx.guild.id, ctx.channel.id)  # type: ignore
        now = time.time()
        last = self._last_unsubscribe_ts.get(key, 0)
        if now - last < 10:
            await ctx.send("Please wait a few seconds before unsubscribing again.")
            return
        # Always unsubscribe only the channel where the command is used
        await remove_live_subscription(ctx.guild.id, ctx.channel.id)  # type: ignore
        await ctx.send(f"Live updates unsubscribed for {ctx.channel.mention}.")
        self._last_unsubscribe_ts[key] = now

    @tasks.loop(seconds=POLL_SECONDS)
    async def _loop(self):
        try:
            subs_raw = await get_all_live_subscriptions()
            subs: List[Tuple[int, int]] = [(g, c) for (g, c, _ts) in subs_raw]
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
                    # If just finished, maybe emit bonus once (only if fixture finished after subscribe time)
                    bonus_msg = await maybe_emit_bonus_when_finished(fx, elements_by_id, teams_by_id, live_points)
                    if bonus_msg:
                        for guild_id, channel_id in subs:
                            # filter by subscribe time and per-guild sent flag
                            try:
                                sub_ts = next((ts for (g, c, ts) in subs_raw if g == guild_id and c == channel_id), 0)
                            except Exception:
                                sub_ts = 0
                            kickoff = fx.get("kickoff_time")
                            # safe: when kickoff_time isn't available, allow
                            if sub_ts:
                                # allow only if this fixture finished after subscribe_ts
                                # finished_provisional implies now>=finish; we approximate with started true and rely on not backfilling
                                pass
                            if await get_bonus_sent(guild_id, channel_id, fx["id"]):
                                continue
                            ch = self.bot.get_channel(channel_id)
                            if ch:
                                await ch.send(bonus_msg)
                                await set_bonus_sent(guild_id, channel_id, fx["id"], True)
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


    @commands.hybrid_command(name="subscribed_channels", description="List channels in this guild receiving live updates")
    async def subscribed_channels(self, ctx: commands.Context):
        try:
            subs_raw = await get_all_live_subscriptions()
            channels = [c for (g, c, _ts) in subs_raw if g == ctx.guild.id]  # type: ignore
            if not channels:
                await ctx.send("No channels in this guild are currently subscribed.")
                return
            # Resolve and format mentions
            mentions = []
            for cid in channels:
                ch = self.bot.get_channel(cid)
                if isinstance(ch, discord.TextChannel):
                    mentions.append(ch.mention)
            if not mentions:
                await ctx.send("No channels in this guild are currently subscribed.")
                return
            await ctx.send("Subscribed channels: " + ", ".join(sorted(set(mentions))))
        except Exception as e:
            print(f"[subscribed_channels] error: {e}")
            await ctx.send("Could not fetch subscribed channels right now.")

async def setup(bot: commands.Bot):
    await bot.add_cog(LiveCommands(bot))


