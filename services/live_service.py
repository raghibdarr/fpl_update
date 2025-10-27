from typing import Dict, List, Tuple, Any, Optional
from datetime import datetime, timezone
import aiohttp

from utils.api_helpers import fetch_fpl_data, PULSE_API_BASE
from repos.db_repo import (
    get_seen_count,
    set_seen_count,
    get_dc_row,
    upsert_dc_row,
    get_finished_sent,
    set_finished_sent,
)


WATCH_STATS = [
    "goals_scored",
    "assists",
    "yellow_cards",
    "red_cards",
    "own_goals",
    "penalties_saved",
    "penalties_missed",
]


async def fetch_current_gw() -> Optional[int]:
    data = await fetch_fpl_data("bootstrap-static/")
    for e in data.get("events", []):
        if e.get("is_current"):
            return e["id"]
    nxt = next((e for e in data.get("events", []) if e.get("is_next")), None)
    return nxt["id"] if nxt else None


async def fetch_fixtures_for_gw(gw: int) -> List[Dict[str, Any]]:
    return await fetch_fpl_data(f"fixtures/?event={gw}")


async def fetch_bootstrap_maps() -> Tuple[Dict[int, Dict[str, Any]], Dict[int, Dict[str, Any]]]:
    data = await fetch_fpl_data("bootstrap-static/")
    elements_by_id = {e["id"]: e for e in data["elements"]}
    teams_by_id = {t["id"]: t for t in data["teams"]}
    return elements_by_id, teams_by_id


async def fetch_live_points_map(gw: int) -> Dict[int, int]:
    live = await fetch_fpl_data(f"event/{gw}/live/")
    return {e["id"]: e["stats"].get("total_points", 0) for e in live.get("elements", [])}


def _collect_counts(fixture: Dict[str, Any]) -> Dict[Tuple[str, int], int]:
    out: Dict[Tuple[str, int], int] = {}
    for s in fixture.get("stats", []):
        ident = s.get("identifier")
        if ident not in WATCH_STATS:
            continue
        for side in ("a", "h"):
            for row in s.get(side, []):
                el = row.get("element")
                val = int(row.get("value", 0) or 0)
                out[(ident, el)] = out.get((ident, el), 0) + val
    return out


def _scoreline(fx: Dict[str, Any], teams_by_id: Dict[int, Dict[str, Any]]) -> str:
    ha = teams_by_id.get(fx["team_h"], {})
    aa = teams_by_id.get(fx["team_a"], {})
    hsn = ha.get("short_name", "H")
    asn = aa.get("short_name", "A")
    return f"{hsn} {fx.get('team_h_score', 0)}–{fx.get('team_a_score', 0)} {asn}"


def _nice_name(el: Dict[str, Any]) -> str:
    return el.get("web_name") or el.get("second_name") or el.get("first_name") or "Unknown"


def _stat_emoji(ident: str) -> str:
    return {
        "goals_scored": "⚽",
        "assists": "🅰️",
        "yellow_cards": "🟨",
        "red_cards": "🟥",
        "own_goals": "🥅",
        "penalties_saved": "🧤",
        "penalties_missed": "❌",
    }.get(ident, "ℹ️")


async def extract_fixture_deltas(fixture: Dict[str, Any]) -> Dict[str, List[int]]:
    fixture_id = fixture["id"]
    counts = _collect_counts(fixture)
    new: Dict[str, List[int]] = {}
    for (ident, el), cur in counts.items():
        prev = await get_seen_count(fixture_id, ident, el)
        if prev is None:
            await set_seen_count(fixture_id, ident, el, cur)
            continue
        if cur > prev:
            for _ in range(cur - prev):
                new.setdefault(ident, []).append(el)
            await set_seen_count(fixture_id, ident, el, cur)
        elif cur < prev:
            await set_seen_count(fixture_id, ident, el, cur)
            new.setdefault("modified", []).append(el)
    return new


def pair_scorers_assisters(deltas: Dict[str, List[int]]) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    goals = deltas.get("goals_scored", [])
    assts = deltas.get("assists", [])
    k = min(len(goals), len(assts))
    for i in range(k):
        result.append({"type": "goal_assist", "scorer": goals[i], "assister": assts[i]})
    for el in goals[k:]:
        result.append({"type": "goal", "scorer": el})
    for el in assts[k:]:
        result.append({"type": "assist", "assister": el})
    for key in ("yellow_cards", "red_cards", "own_goals", "penalties_saved", "penalties_missed", "modified"):
        for el in deltas.get(key, []):
            result.append({"type": key, "player": el})
    return result


def format_event_message(
    *,
    item: Dict[str, Any],
    fixture: Dict[str, Any],
    elements_by_id: Dict[int, Dict[str, Any]],
    teams_by_id: Dict[int, Dict[str, Any]],
    live_points: Dict[int, int],
) -> Optional[str]:
    sl = _scoreline(fixture, teams_by_id)

    def total_line(el_id: int) -> str:
        pts = live_points.get(el_id, 0)
        return f"— Total: {pts} pts."

    t = item["type"]
    if t == "goal_assist":
        s_el = elements_by_id.get(item["scorer"])  # type: ignore
        a_el = elements_by_id.get(item["assister"])  # type: ignore
        if not s_el or not a_el:
            return None
        return (
            "Goal!\n"
            f"{_stat_emoji('goals_scored')} {_nice_name(s_el)} {total_line(s_el['id'])}\n"
            f"{_stat_emoji('assists')} {_nice_name(a_el)} {total_line(a_el['id'])}\n\n"
            f"{sl}"
        )
    if t == "goal":
        s_el = elements_by_id.get(item["scorer"])  # type: ignore
        if not s_el:
            return None
        return "Goal!\n" f"{_stat_emoji('goals_scored')} {_nice_name(s_el)} {total_line(s_el['id'])}\n\n{sl}"
    if t == "assist":
        a_el = elements_by_id.get(item["assister"])  # type: ignore
        if not a_el:
            return None
        return "Assist!\n" f"{_stat_emoji('assists')} {_nice_name(a_el)} {total_line(a_el['id'])}\n\n{sl}"
    if t == "yellow_cards":
        p = elements_by_id.get(item["player"])  # type: ignore
        if not p:
            return None
        return f"Yellow card\n{_stat_emoji('yellow_cards')} {_nice_name(p)} {total_line(p['id'])}\n\n{sl}"
    if t == "red_cards":
        p = elements_by_id.get(item["player"])  # type: ignore
        if not p:
            return None
        return f"Red card\n{_stat_emoji('red_cards')} {_nice_name(p)} {total_line(p['id'])}\n\n{sl}"
    if t == "own_goals":
        p = elements_by_id.get(item["player"])  # type: ignore
        if not p:
            return None
        return f"Own goal\n{_stat_emoji('own_goals')} {_nice_name(p)} {total_line(p['id'])}\n\n{sl}"
    if t == "penalties_saved":
        p = elements_by_id.get(item["player"])  # type: ignore
        if not p:
            return None
        return f"Penalty saved\n{_stat_emoji('penalties_saved')} {_nice_name(p)} {total_line(p['id'])}\n\n{sl}"
    if t == "penalties_missed":
        p = elements_by_id.get(item["player"])  # type: ignore
        if not p:
            return None
        return f"Penalty missed\n{_stat_emoji('penalties_missed')} {_nice_name(p)} {total_line(p['id'])}\n\n{sl}"
    if t == "modified":
        p = elements_by_id.get(item.get("player")) if item.get("player") else None
        name = _nice_name(p) if p else "Update"
        return f"Modified!\nℹ️ {name}: a stat has been adjusted.\n\n{sl}"
    return None


def _pulse_match_id(fixture: Dict[str, Any]) -> Optional[int]:
    return fixture.get("pulse_id")


async def _fetch_pulse_dc_counts(pulse_match_id: int) -> Dict[int, int]:
    url = f"{PULSE_API_BASE}match/{pulse_match_id}"
    out: Dict[int, int] = {}
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url) as r:
                r.raise_for_status()
                data = await r.json()
        for p in data.get("playerStats", []):
            el_id = p.get("fplId") or p.get("elementId")
            if not el_id:
                continue
            dc = int(p.get("stats", {}).get("defensiveContributions", 0) or 0)
            out[int(el_id)] = dc
    except Exception:
        pass
    return out


def _defcon_threshold(element_type: int) -> int:
    # 1 GK, 2 DEF, 3 MID, 4 FWD
    return 10 if element_type == 2 else 12


async def compute_defcon_threshold_hits(
    fixture: Dict[str, Any],
    elements_by_id: Dict[int, Dict[str, Any]],
    teams_by_id: Dict[int, Dict[str, Any]],
    gw: int,
) -> List[str]:
    msgs: List[str] = []
    pmid = _pulse_match_id(fixture)
    if not pmid:
        return msgs
    dc_counts = await _fetch_pulse_dc_counts(pmid)
    if not dc_counts:
        return msgs

    hsn = teams_by_id.get(fixture["team_h"], {}).get("short_name", "H")
    asn = teams_by_id.get(fixture["team_a"], {}).get("short_name", "A")
    sl = f"{hsn} {fixture.get('team_h_score', 0)}–{fixture.get('team_a_score', 0)} {asn}"

    for el_id, dc in dc_counts.items():
        el = elements_by_id.get(int(el_id))
        if not el:
            continue
        need = _defcon_threshold(el["element_type"])
        row = await get_dc_row(fixture["id"], int(el_id))
        prev = row[0] if row else 0
        already = bool(row[1]) if row else False

        hit_now = (dc >= need) and not already
        await upsert_dc_row(fixture["id"], int(el_id), dc, already or hit_now)
        if hit_now:
            name = _nice_name(el)
            msgs.append(f"DefCon hit! +2 pts\n🛡️ {name} — DC {dc}/{need}\n\n{sl}")
    return msgs


async def maybe_emit_bonus_when_finished(
    fixture: Dict[str, Any],
    elements_by_id: Dict[int, Dict[str, Any]],
    live_points: Dict[int, int] | None = None,
) -> Optional[str]:
    if not fixture.get("finished_provisional"):
        return None
    if await get_finished_sent(fixture["id"]):
        return None

    entries: List[Tuple[int, int]] = []
    for s in fixture.get("stats", []):
        if s.get("identifier") != "bps":
            continue
        for side in ("a", "h"):
            for row in s.get(side, []):
                el_id = row.get("element")
                bps = int(row.get("value", 0) or 0)
                if el_id:
                    entries.append((int(el_id), bps))

    if not entries:
        await set_finished_sent(fixture["id"], True)
        return None

    entries.sort(key=lambda x: x[1], reverse=True)

    # award logic (3/2/1 with ties)
    award: Dict[int, int] = {}
    if entries:
        top_bps = entries[0][1]
        top_group = [e for e in entries if e[1] == top_bps]
        for el, _ in top_group:
            award[el] = 3
        rest = [e for e in entries if e[1] < top_bps]
        if rest:
            second_bps = rest[0][1]
            second_group = [e for e in rest if e[1] == second_bps]
            if len(top_group) == 1:
                for el, _ in second_group:
                    award[el] = 2
                rest2 = [e for e in rest if e[1] < second_bps]
                if rest2:
                    third_bps = rest2[0][1]
                    third_group = [e for e in rest2 if e[1] == third_bps]
                    for el, _ in third_group:
                        award[el] = 1
            else:
                # two or more tied for 3; next band gets 1
                for el, _ in second_group:
                    award[el] = 1

    lines: List[str] = []
    for pts in (3, 2, 1):
        band = [(el, bps) for el, bps in entries if award.get(el) == pts]
        if band:
            names = ", ".join(f"{(elements_by_id.get(el) or {}).get('web_name','?')} ({bps})" for el, bps in band)
            lines.append(f"{pts} pts: {names}")

    # Build a header with fixture
    h_team = fixture.get("team_h")
    a_team = fixture.get("team_a")
    # header e.g. "Provisional bonus (BPS): H 2–1 A"
    header = "Provisional bonus (BPS):"
    if h_team and a_team:
        header += " "
    # medals and totals with optional pre-bonus totals
    medal = {3: "🥇", 2: "🥈", 1: "🥉"}
    pretty_lines = []
    for pts in (3, 2, 1):
        band = [(el, bps) for el, bps in entries if award.get(el) == pts]
        if not band:
            continue
        names = []
        for el, bps in band:
            base = elements_by_id.get(el) or {}
            nm = base.get('web_name', '?')
            if live_points is not None:
                tot = live_points.get(el, 0)
                names.append(f"{nm} ({bps}) — Total: {tot}+{pts}={tot+pts}")
            else:
                names.append(f"{nm} ({bps})")
        pretty_lines.append(f"{medal[pts]} {pts} pts: "+", ".join(names))

    msg = header + "\n" + "\n".join(pretty_lines)
    await set_finished_sent(fixture["id"], True)
    return msg


