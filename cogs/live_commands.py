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
    compute_defcon_threshold_events,
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
        # Pending goal/assist to allow pairing on the next tick: {fixture_id: {"goals":[el_ids], "assists":[el_ids], "ts":float}}
        self._pending_pairing: dict[int, dict[str, object]] = {}

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
                    bonus_payload = await maybe_emit_bonus_when_finished(fx, elements_by_id, teams_by_id, live_points)
                    if bonus_payload:
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
                                embed = discord.Embed(
                                    title=bonus_payload.get("title") or "Provisional bonus (BPS)",
                                    description=bonus_payload.get("description") or "",
                                    colour=discord.Color.gold(),
                                )
                                await ch.send(embed=embed)
                                await set_bonus_sent(guild_id, channel_id, fid, True)
                            # DefCon summary for the finished fixture (all hits, no ownership filter)
                            try:
                                from repos.db_repo import list_dc_hits_for_fixture, get_defcon_summary_sent, set_defcon_summary_sent
                                if not await get_defcon_summary_sent(guild_id, channel_id, fid):
                                    rows = await list_dc_hits_for_fixture(fid)
                                    if rows:
                                        header = f"{teams_by_id.get(fx['team_h'], {}).get('short_name','H')} {fx.get('team_h_score',0)}–{fx.get('team_a_score',0)} {teams_by_id.get(fx['team_a'], {}).get('short_name','A')}"
                                        desc_lines = []
                                        # parse awards mapping for totals
                                        awards_raw = (bonus_payload.get("awards") or "")
                                        awards_map = {}
                                        try:
                                            for pair in awards_raw.split(","):
                                                if not pair:
                                                    continue
                                                el_s, pts_s = pair.split(":")
                                                awards_map[int(el_s)] = int(pts_s)
                                        except Exception:
                                            awards_map = {}
                                        for (el_id, dc) in rows:
                                            el = elements_by_id.get(el_id, {})
                                            name = el.get('web_name') or el.get('second_name') or str(el_id)
                                            need = 10 if el.get('element_type') == 2 else 12
                                            base_tot = live_points.get(el_id, 0)
                                            tot = base_tot + awards_map.get(el_id, 0)
                                            desc_lines.append(f"🛡️ {name} — DC {dc}/{need} — Total: {tot}")
                                        if desc_lines:
                                            embed = discord.Embed(title=f"{header} — DefCon summary", description="\n".join(desc_lines), colour=discord.Color.teal())
                                            await ch.send(embed=embed)
                                            await set_defcon_summary_sent(guild_id, channel_id, fid, True)
                            except Exception as e:
                                print(f"[live] defcon summary error fixture={fid}: {e}")
                    continue

                # Live: deltas
                import time
                deltas = await extract_fixture_deltas(fx, elements_by_id)
                lines_by_fixture: list[str] = []
                if deltas:
                    print(f"[live] deltas fixture={fid} keys={[k for k in deltas.keys()]}")
                    # Goal/assist delayed pairing across ticks
                    current_goals = list(deltas.get("goals_scored", []))
                    current_assists = list(deltas.get("assists", []))
                    prev = self._pending_pairing.get(fid, {"goals": [], "assists": [], "ts": time.time()})
                    prev_goals = list(prev.get("goals", []))  # type: ignore
                    prev_assists = list(prev.get("assists", []))  # type: ignore
                    # Pair using prev with current first
                    paired_items = []
                    # pair prev_goals with current_assists
                    while prev_goals and current_assists:
                        g = prev_goals.pop(0)
                        a = current_assists.pop(0)
                        paired_items.append({"type": "goal_assist", "scorer": g, "assister": a})
                    # pair prev_assists with current_goals
                    while prev_assists and current_goals:
                        a = prev_assists.pop(0)
                        g = current_goals.pop(0)
                        paired_items.append({"type": "goal_assist", "scorer": g, "assister": a})
                    # Also pair any remaining current goals/assists within the SAME tick
                    # (so we don't delay when both arrive together)
                    while current_goals and current_assists:
                        g = current_goals.pop(0)
                        a = current_assists.pop(0)
                        paired_items.append({"type": "goal_assist", "scorer": g, "assister": a})
                    # If any prev remained unpaired after one tick, emit them now
                    stale_unpaired: list[dict] = []
                    for g in prev_goals:
                        stale_unpaired.append({"type": "goal", "scorer": g})
                    for a in prev_assists:
                        stale_unpaired.append({"type": "assist", "assister": a})
                    # Now, DO NOT emit remaining current unpaired (if any) yet; store for next tick
                    self._pending_pairing[fid] = {"goals": current_goals, "assists": current_assists, "ts": time.time()}
                    # Build compact lines for paired + stale unpaired
                    def _line_for_item(item: dict) -> str:
                        header = ""  # we will send a single embed with header; lines only
                        if item["type"] == "goal_assist":
                            s = elements_by_id.get(item["scorer"], {}).get("web_name", item["scorer"])
                            a = elements_by_id.get(item["assister"], {}).get("web_name", item["assister"])
                            s_tot = live_points.get(item["scorer"], 0)
                            a_tot = live_points.get(item["assister"], 0)
                            return f"⚽ GOAL | {s} — Total: {s_tot} pts.\n🅰️ ASSIST | {a} — Total: {a_tot} pts."
                        if item["type"] == "goal":
                            s = elements_by_id.get(item["scorer"], {}).get("web_name", item["scorer"])
                            s_tot = live_points.get(item["scorer"], 0)
                            return f"⚽ GOAL | {s} — Total: {s_tot} pts."
                        if item["type"] == "assist":
                            a = elements_by_id.get(item["assister"], {}).get("web_name", item["assister"])
                            a_tot = live_points.get(item["assister"], 0)
                            return f"🅰️ ASSIST | {a} — Total: {a_tot} pts."
                        if item["type"] == "yellow_cards":
                            p = elements_by_id.get(item["player"], {}).get("web_name", item["player"])
                            t = live_points.get(item["player"], 0)
                            return f"🟨 Yellow card | {p} — Total: {t} pts."
                        if item["type"] == "red_cards":
                            p = elements_by_id.get(item["player"], {}).get("web_name", item["player"])
                            t = live_points.get(item["player"], 0)
                            return f"🟥 Red card | {p} — Total: {t} pts."
                        if item["type"] == "own_goals":
                            p = elements_by_id.get(item["player"], {}).get("web_name", item["player"])
                            t = live_points.get(item["player"], 0)
                            return f"🥅 Own goal | {p} — Total: {t} pts."
                        if item["type"] == "penalties_saved":
                            p = elements_by_id.get(item["player"], {}).get("web_name", item["player"])
                            t = live_points.get(item["player"], 0)
                            return f"🧤 Penalty saved | {p} — Total: {t} pts."
                        if item["type"] == "penalties_missed":
                            p = elements_by_id.get(item["player"], {}).get("web_name", item["player"])
                            t = live_points.get(item["player"], 0)
                            return f"❌ Penalty missed | {p} — Total: {t} pts."
                        return ""
                    # Log and collect lines
                    try:
                        print(f"[live] pairing fixture={fid} carryover -> emit now: {len(stale_unpaired)}, new pairs: {len(paired_items)}")
                    except Exception:
                        pass
                    for it in stale_unpaired + paired_items:
                        ln = _line_for_item(it)
                        if ln:
                            lines_by_fixture.append(ln)
                    # Immediately handled events (no delay): cards & misc
                    MIN_YC_SELECTED = 1.0
                    for key in ("yellow_cards", "red_cards", "own_goals", "penalties_saved", "penalties_missed", "modified"):
                        for pid in deltas.get(key, []):
                            # Ownership filter for yellow cards only
                            if key == "yellow_cards":
                                try:
                                    base = elements_by_id.get(pid, {})  # type: ignore
                                    sel_raw = str(base.get("selected_by_percent", "0"))
                                    sel = float(sel_raw.replace("%", "")) if isinstance(sel_raw, str) else float(sel_raw)
                                except Exception:
                                    sel = 0.0
                                if sel < MIN_YC_SELECTED:
                                    continue
                            ln = _line_for_item({"type": key, "player": pid})
                            if ln:
                                lines_by_fixture.append(ln)
                # Send one embed per fixture for compactness
                if lines_by_fixture:
                    header = f"{teams_by_id.get(fx['team_h'], {}).get('short_name','H')} {fx.get('team_h_score',0)}–{fx.get('team_a_score',0)} {teams_by_id.get(fx['team_a'], {}).get('short_name','A')}"
                    embed = discord.Embed(title=header, description="\n".join(lines_by_fixture), colour=discord.Color.blurple())
                    for _, channel_id in subs:
                        ch = self.bot.get_channel(channel_id)
                        if ch:
                            await ch.send(embed=embed)

                # DefCon thresholds (filter by ownership >= 1% for live ticker), embedded within the same fixture embed
                defcon_events = await compute_defcon_threshold_events(fx, elements_by_id, teams_by_id, gw, min_selected_percent=1.0)
                if defcon_events:
                    for ev in defcon_events:
                        pid = ev["player"]
                        name = ev["name"]
                        dc = ev["dc"]
                        need = ev["need"]
                        lines_by_fixture.append(f"🛡️ DefCon +2 | {name} — DC {dc}/{need}")
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


