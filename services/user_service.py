from utils.api_helpers import fetch_fpl_data
import asyncio
import aiohttp
import io
from typing import Dict, List, Tuple, Any, Set
from PIL import Image
from utils.image_generator import create_squad_image


async def fetch_user_team_name(fpl_id: int) -> str:
    user_data = await fetch_fpl_data(f"entry/{fpl_id}/")
    return user_data['name']


async def fetch_user_total_points(fpl_id: int) -> int:
    user_data = await fetch_fpl_data(f"entry/{fpl_id}/")
    return user_data['summary_overall_points']



async def _current_event_and_bootstrap() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    data = await fetch_fpl_data("bootstrap-static/")
    current = next((e for e in data['events'] if e.get('is_current')), None)
    if current is None:
        current = next((e for e in data['events'] if e.get('is_next')), data['events'][-1])
    return current, data


async def _fetch_shirt_images(team_codes: Set[int]) -> Dict[int, Image.Image]:
    async def fetch_one(session: aiohttp.ClientSession, code: int):
        url = f"https://fantasy.premierleague.com/dist/img/shirts/standard/shirt_{code}-66.png"
        try:
            async with session.get(url) as resp:
                if resp.status == 200:
                    b = await resp.read()
                    return code, Image.open(io.BytesIO(b)).convert("RGBA")
        except Exception:
            pass
        return code, None

    out: Dict[int, Image.Image] = {}
    async with aiohttp.ClientSession() as session:
        results = await asyncio.gather(*(fetch_one(session, c) for c in team_codes))
    for code, img in results:
        if img is not None:
            out[code] = img
    return out


def _group_starters_by_line(picks: List[Dict[str, Any]], elements_by_id: Dict[int, Dict[str, Any]]):
    starters = [p for p in picks if p.get('multiplier', 0) > 0]
    lines = {"GK": [], "DEF": [], "MID": [], "FWD": []}
    for p in starters:
        et = elements_by_id[p['element']]['element_type']
        if et == 1:
            lines["GK"].append(p)
        elif et == 2:
            lines["DEF"].append(p)
        elif et == 3:
            lines["MID"].append(p)
        else:
            lines["FWD"].append(p)
    for k in lines:
        lines[k].sort(key=lambda x: x['position'])
    return lines


async def build_myteam_image(fpl_id: int, team_name: str | None = None) -> Image.Image:
    current_event, bootstrap = await _current_event_and_bootstrap()
    event_id = current_event['id']
    event_name = current_event['name']

    picks_data = await fetch_fpl_data(f"entry/{fpl_id}/event/{event_id}/picks/")
    picks: List[Dict[str, Any]] = picks_data.get('picks', [])
    active_chip = picks_data.get('active_chip')
    entry_history = picks_data.get('entry_history', {}) or {}
    total_points = entry_history.get('points')

    live = await fetch_fpl_data(f"event/{event_id}/live/")
    live_points = {e['id']: e['stats'].get('total_points', 0) for e in live.get('elements', [])}

    elements_by_id = {e['id']: e for e in bootstrap['elements']}
    teams_by_id = {t['id']: t for t in bootstrap['teams']}

    captain_id = next((p['element'] for p in picks if p.get('is_captain')), None)
    vice_id = next((p['element'] for p in picks if p.get('is_vice_captain')), None)

    lines = _group_starters_by_line(picks, elements_by_id)
    bench = sorted([p for p in picks if p.get('multiplier', 0) == 0], key=lambda x: x['position'])

    if total_points is None:
        total_points = sum(live_points.get(p['element'], 0) * p.get('multiplier', 0) for p in picks)

    team_ids = {elements_by_id[p['element']]['team'] for p in picks}
    team_codes = {teams_by_id[tid]['code'] for tid in team_ids}
    shirts_by_team_code = await _fetch_shirt_images(team_codes)

    return create_squad_image(
        team_name=team_name or "",
        event_name=event_name,
        total_points=total_points,
        lines=lines,
        bench=bench,
        elements_by_id=elements_by_id,
        teams_by_id=teams_by_id,
        live_points=live_points,
        captain_id=captain_id,
        vice_id=vice_id,
        shirts_by_team_code=shirts_by_team_code,
        active_chip=active_chip,
    )

