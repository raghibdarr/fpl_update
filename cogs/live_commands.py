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


POLL_SECONDS = 30


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
        # last tick time (epoch seconds)
        self._last_tick_ts = None
        # Ensure loop auto-starts if there are existing subscriptions in DB
        try:
            self.bot.loop.create_task(self._startup_check())
        except Exception as e:
            print(f"[live] failed to schedule startup check: {e}")

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
        # Run an immediate tick so you don't have to wait for the next interval
        try:
            await self._run_tick()
        except Exception as e:
            print(f"[live_subscribe] immediate tick error: {e}")

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

    async def _run_tick(self):
        try:
            subs_raw = await get_all_live_subscriptions()
            subs: List[Tuple[int, int]] = [(g, c) for (g, c, _ts) in subs_raw]
            import time
            self._last_tick_ts = time.time()
            print(f"[live] tick; subs={len(subs_raw)}")
            if not subs:
                return

            gw = await fetch_current_gw()
            print(f"[live] current_gw={gw}")
            if gw is None:
                return

            if self._bootstrap is None or self._gw_cache != gw:
                self._bootstrap = await fetch_bootstrap_maps()
                self._gw_cache = gw
                print("[live] bootstrap loaded/cached")

            elements_by_id, teams_by_id = self._bootstrap
            fixtures = await fetch_fixtures_for_gw(gw)
            print(f"[live] fixtures count={len(fixtures) if fixtures else 0}")
            if not fixtures:
                return

            live_points = await fetch_live_points_map(gw)
            print(f"[live] live_points loaded elements={len(live_points)}")

            for fx in fixtures:
                fid = fx.get("id")
                started = bool(fx.get("started"))
                finished = bool(fx.get("finished_provisional"))
                print(f"[live] fixture id={fid} started={started} finished_provisional={finished}")

                # Finished: maybe send bonus once per channel
                if not started or finished:
                    bonus_msg = await maybe_emit_bonus_when_finished(fx, elements_by_id, teams_by_id, live_points)
                    if bonus_msg:
                        print(f"[live] bonus ready for fixture={fid}")
                        for guild_id, channel_id in subs:
                            try:
                                sub_ts = next((ts for (g, c, ts) in subs_raw if g == guild_id and c == channel_id), 0)
                            except Exception:
                                sub_ts = 0
                            if await get_bonus_sent(guild_id, channel_id, fid):
                                continue
                            ch = self.bot.get_channel(channel_id)
                            if ch:
                                print(f"[live] sending bonus to guild={guild_id} channel={channel_id}")
                                await ch.send(bonus_msg)
                                await set_bonus_sent(guild_id, channel_id, fid, True)
                    continue

                # Live: deltas
                deltas = await extract_fixture_deltas(fx, elements_by_id)
                if deltas:
                    print(f"[live] deltas fixture={fid} keys={[k for k in deltas.keys()]}")
                    paired = pair_scorers_assisters(deltas)
                    # Log pairing decisions
                    try:
                        pairs = []
                        goals_only = []
                        assists_only = []
                        for it in paired:
                            if it["type"] == "goal_assist":
                                s = elements_by_id.get(it["scorer"], {}).get("web_name", it["scorer"])
                                a = elements_by_id.get(it["assister"], {}).get("web_name", it["assister"])
                                pairs.append((s, a))
                            elif it["type"] == "goal":
                                s = elements_by_id.get(it["scorer"], {}).get("web_name", it["scorer"])
                                goals_only.append(s)
                            elif it["type"] == "assist":
                                a = elements_by_id.get(it["assister"], {}).get("web_name", it["assister"])
                                assists_only.append(a)
                        print(f"[live] pairing fixture={fid} pairs={pairs} goals_only={goals_only} assists_only={assists_only}")
                    except Exception as e:
                        print(f"[live] pairing log error fixture={fid}: {e}")
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
                                print(f"[live] sending {len(msgs)} event(s) to channel={channel_id}")
                                for m in msgs:
                                    await ch.send(m)

                # DefCon thresholds via Pulse
                dc_msgs = await compute_defcon_threshold_hits(fx, elements_by_id, teams_by_id, gw)
                if dc_msgs:
                    print(f"[live] defcon msgs={len(dc_msgs)} for fixture={fid}")
                    for _, channel_id in subs:
                        ch = self.bot.get_channel(channel_id)
                        if ch:
                            for m in dc_msgs:
                                await ch.send(m)
        except Exception as e:
            print(f"[live] tick error: {e}")

    @tasks.loop(seconds=POLL_SECONDS, reconnect=True)
    async def _loop(self):
        await self._run_tick()

    @_loop.before_loop
    async def _before_loop(self):
        print("[live] waiting for bot ready before starting loop...")
        await self.bot.wait_until_ready()
        print("[live] loop starting")

    @_loop.after_loop
    async def _after_loop(self):
        print("[live] loop stopped")

    async def _startup_check(self):
        # Auto-start the loop if any subscriptions exist when the cog loads
        await self.bot.wait_until_ready()
        try:
            subs_raw = await get_all_live_subscriptions()
            if subs_raw and not self._loop.is_running():
                print(f"[live] auto-starting loop on startup; subs={len(subs_raw)}")
                self._loop.start()
                self._loop_started = True
        except Exception as e:
            print(f"[live] startup_check error: {e}")


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

    @commands.hybrid_command(name="live_poll_now", description="Run a live poll tick now (debug)")
    async def live_poll_now(self, ctx: commands.Context):
        await ctx.defer()
        await self._run_tick()
        await ctx.send("Live tick executed (see console logs).")

    @commands.hybrid_command(name="live_loop_status", description="Show live loop status and last tick time")
    async def live_loop_status(self, ctx: commands.Context):
        import time
        running = self._loop.is_running()
        if self._last_tick_ts:
            ago = int(time.time() - self._last_tick_ts)
            await ctx.send(f"Loop running: {running}. Last tick {ago}s ago. Interval={POLL_SECONDS}s")
        else:
            await ctx.send(f"Loop running: {running}. No tick yet. Interval={POLL_SECONDS}s")

    @commands.hybrid_command(name="live_loop_start", description="Manually start the live poll loop (admin/debug)")
    async def live_loop_start(self, ctx: commands.Context):
        if not self._loop.is_running():
            self._loop.start()
            self._loop_started = True
            await ctx.send("Live loop started.")
        else:
            await ctx.send("Live loop is already running.")

    @commands.hybrid_command(name="live_loop_stop", description="Manually stop the live poll loop (admin/debug)")
    async def live_loop_stop(self, ctx: commands.Context):
        if self._loop.is_running():
            self._loop.cancel()
            self._loop_started = False
            await ctx.send("Live loop stopped.")
        else:
            await ctx.send("Live loop is not running.")

async def setup(bot: commands.Bot):
    await bot.add_cog(LiveCommands(bot))


