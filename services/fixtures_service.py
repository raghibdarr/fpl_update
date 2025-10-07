import asyncio
from datetime import datetime, timezone, timedelta
from collections import defaultdict

from utils.api_helpers import fetch_api_data, fetch_fpl_data, FPL_API_BASE, PULSE_API_BASE
from data.team_aliases import team_aliases


def abbreviate_team_name(team_name: str) -> str:
    if not team_name:
        return "?"
    words = [w for w in ''.join(ch if ch.isalnum() or ch.isspace() else ' ' for ch in team_name).split() if w]
    if len(words) == 1:
        return words[0][:3].upper()
    if len(words) == 2:
        return (words[0][0] + words[1][:2]).upper()
    return (words[0][0] + words[1][0] + words[2][0]).upper()


COMPETITION_IDS = {
    "PL": 1,
    "FA": 4,
    "EFL": 2,
    "UCL": 5,
    "UEL": 6,
    "UECL": 1125,
}


async def fetch_fixture_data(num_gameweeks, selected_teams=None, sort_method="alphabetical", start_gw=None, show_cups=False):
    bootstrap = await fetch_fpl_data("bootstrap-static/")

    teams = {team['id']: {'short': team['short_name'], 'name': team['name']} for team in bootstrap['teams']}
    team_name_to_short = {team['name']: team['short_name'] for team in bootstrap['teams']}

    alias_to_team = {}
    for team, aliases in team_aliases.items():
        for alias in aliases:
            alias_to_team[alias.lower()] = team

    if selected_teams:
        from fuzzywuzzy import process
        selected_team_shorts = set()
        for team in selected_teams:
            best_match, score = process.extractOne(team.lower(), alias_to_team.keys())
            if score > 80:
                matched_team_name = alias_to_team[best_match]
                if matched_team_name in team_name_to_short:
                    selected_team_shorts.add(team_name_to_short[matched_team_name])

        if selected_team_shorts:
            filtered_teams = {id: team for id, team in teams.items() if team['short'] in selected_team_shorts}
        else:
            filtered_teams = teams
    else:
        filtered_teams = teams

    current_gw = next((event for event in bootstrap['events'] if event['is_current']), None)
    fpl_fixtures = None
    
    if start_gw is None:
        if current_gw:
            # If all fixtures in the current GW are finished, start at the next GW; otherwise include current GW
            fpl_fixtures = await fetch_fpl_data("fixtures/")
            has_unfinished = any(
                (fx.get('event') == current_gw['id']) and (not fx.get('finished', False))
                for fx in fpl_fixtures
            )
            start_gw = current_gw['id'] if has_unfinished else current_gw['id'] + 1
        else:
            start_gw = next(event['id'] for event in bootstrap['events'] if not event['finished'])

    end_gw = min(start_gw + num_gameweeks - 1, 38)
    actual_gameweeks = end_gw - start_gw + 1

    # Initialize fixture buckets with independent dicts for each GW
    fixture_data = {
        team['short']: [
            {'opponent': '', 'fdr': 0} for _ in range(actual_gameweeks)
        ]
        for team in filtered_teams.values()
    }
    cup_fixture_buckets = defaultdict(list)

    # 1) Populate Premier League fixtures using the official FPL endpoint
    if fpl_fixtures is None:
        fpl_fixtures = await fetch_fpl_data("fixtures/")

    for fixture in fpl_fixtures:
        gw = fixture.get('event')
        if gw is None or not (start_gw <= gw <= end_gw):
            continue

        home_id = fixture['team_h']
        away_id = fixture['team_a']
        home_short = teams.get(home_id, {}).get('short')
        away_short = teams.get(away_id, {}).get('short')
        if not home_short or not away_short:
            continue

        gw_index = gw - start_gw
        home_fdr = fixture.get('team_h_difficulty') or 0
        away_fdr = fixture.get('team_a_difficulty') or 0

        if home_short in fixture_data:
            fixture_data[home_short][gw_index] = {'opponent': away_short.upper(), 'fdr': home_fdr}
        if away_short in fixture_data:
            fixture_data[away_short][gw_index] = {'opponent': home_short.lower(), 'fdr': away_fdr}

    # 2) Optionally enrich with cup fixtures via Pulse API
    if show_cups:
        start_deadline = next(e for e in bootstrap['events'] if e['id'] == start_gw)['deadline_time']
        end_deadline = next(e for e in bootstrap['events'] if e['id'] == end_gw)['deadline_time']
        start_dt = datetime.fromisoformat(start_deadline.replace('Z', '+00:00'))
        end_dt = datetime.fromisoformat(end_deadline.replace('Z', '+00:00'))

        tasks = []
        windows = []
        # Iterate months covering [start_dt - 7d, end_dt + 1d]
        probe_start = (start_dt - timedelta(days=7)).replace(day=1)
        probe_end = (end_dt + timedelta(days=1)).replace(day=1)
        cursor = probe_start
        while cursor <= probe_end:
            year = cursor.year
            month = cursor.month
            next_month_year = year + (1 if month == 12 else 0)
            next_month = 1 if month == 12 else month + 1
            kick_from = f"{year}-{month:02d}-01"
            kick_to = f"{next_month_year}-{next_month:02d}-01"
            windows.append((kick_from, kick_to, year))
            cursor = cursor.replace(year=next_month_year, month=next_month, day=1)

        for comp, comp_id in COMPETITION_IDS.items():
            if comp == 'PL':
                continue
            for kick_from, kick_to, year in windows:
                params = {
                    'competition': comp_id,
                    'season': year,
                    'kickoff>': kick_from,
                    'kickoff<': kick_to,
                    '_limit': 200
                }
                tasks.append(fetch_api_data(None, f"{PULSE_API_BASE}matches", params=params))

        # Execute HTTP requests concurrently with a session per utils helper
        pages = await asyncio.gather(*[
            fetch_api_data(__import__('aiohttp').ClientSession(), f"{PULSE_API_BASE}matches", params=params)  # type: ignore
            for params in (
                {
                    'competition': comp_id,
                    'season': year,
                    'kickoff>': kick_from,
                    'kickoff<': kick_to,
                    '_limit': 200
                }
                for comp, comp_id in COMPETITION_IDS.items() if comp != 'PL'
                for kick_from, kick_to, year in windows
            )
        ], return_exceptions=True)

        total = 0
        for page in pages:
            if isinstance(page, Exception):
                continue
            data = page.get('data') or page.get('content') or []
            total += len(data)
            for fixture in data:
                period = fixture.get('period')
                if isinstance(period, str) and period.lower() == 'fulltime':
                    continue
                home_name = (fixture.get('homeTeam') or {}).get('name')
                away_name = (fixture.get('awayTeam') or {}).get('name')
                if not home_name or not away_name:
                    continue
                home_short = team_name_to_short.get(home_name)
                away_short = team_name_to_short.get(away_name)
                if not home_short and not away_short:
                    continue
                kickoff_str = fixture.get('kickoff')
                if not kickoff_str:
                    continue
                try:
                    kickoff_time = datetime.strptime(kickoff_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
                except Exception:
                    try:
                        kickoff_time = datetime.strptime(kickoff_str.split(' ')[0], '%Y-%m-%d').replace(tzinfo=timezone.utc)
                    except Exception:
                        continue
                gw_map = next((event['id'] for event in bootstrap['events'] if datetime.fromisoformat(event['deadline_time'].replace('Z', '+00:00')) > kickoff_time), None)
                if not gw_map or not (start_gw <= gw_map <= end_gw):
                    continue
                comp_id = fixture.get('competitionId') or (fixture.get('competition') and fixture['competition'].get('id'))
                cup_name = next((name for name, cid in COMPETITION_IDS.items() if cid == int(comp_id) and name != 'PL'), None) if comp_id else None
                if not cup_name:
                    continue
                if home_short:
                    cup_fixture_buckets[gw_map].append({
                        'team': home_short,
                        'opponent': (away_short or abbreviate_team_name(away_name)),
                        'opponent_full': away_name,
                        'is_home': True,
                        'competition': cup_name
                    })
                if away_short:
                    cup_fixture_buckets[gw_map].append({
                        'team': away_short,
                        'opponent': (home_short or abbreviate_team_name(home_name)),
                        'opponent_full': home_name,
                        'is_home': False,
                        'competition': cup_name
                    })

    team_positions = {team['short_name']: team['position'] for team in bootstrap['teams']}

    if sort_method == "table":
        sorted_teams = sorted(fixture_data.keys(), key=lambda x: team_positions.get(x, 999))
    elif sort_method == "fdr":
        def team_fdr_score(team_key):
            fixtures = fixture_data[team_key]
            return sum(f.get('fdr') if f.get('fdr') else 3 for f in fixtures)
        sorted_teams = sorted(fixture_data.keys(), key=lambda t: (team_fdr_score(t), t))
    else:
        sorted_teams = sorted(fixture_data.keys())

    fixture_data = {team: fixture_data[team] for team in sorted_teams}
    
    gw_dates = {event['id']: datetime.fromisoformat(event['deadline_time'].replace('Z', '+00:00')).strftime("%d/%m")
                for event in bootstrap['events'] if start_gw <= event['id'] <= end_gw}
                
    return fixture_data, start_gw, actual_gameweeks, {v['short']: v['name'] for v in filtered_teams.values()}, gw_dates, cup_fixture_buckets


