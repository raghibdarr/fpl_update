import aiohttp
import asyncio


async def fetch_league_standings(league_id):
    async with aiohttp.ClientSession() as session:
        league_url = f"https://fantasy.premierleague.com/api/leagues-classic/{league_id}/standings/"
        async with session.get(league_url) as resp:
            if resp.status != 200:
                raise Exception(f"League API request failed with status {resp.status}")
            league_data = await resp.json()

    standings = league_data['standings']['results']

    async def fetch_team_data(entry):
        team_id = entry['entry']
        async with aiohttp.ClientSession() as session:
            team_url = f"https://fantasy.premierleague.com/api/entry/{team_id}/"
            try:
                async with session.get(team_url) as resp:
                    if resp.status == 200:
                        team_data = await resp.json()
                        entry['value'] = team_data.get('last_deadline_value', 0)
                        entry['overall_rank'] = team_data.get('summary_overall_rank', 'N/A')
                        print(f"Team {team_id}: Raw data: {team_data}")
                    else:
                        print(f"Team {team_id}: API request failed with status {resp.status}")
                        entry['value'] = 0
                        entry['overall_rank'] = 'N/A'
            except Exception as e:
                print(f"Team {team_id}: Error fetching data: {str(e)}")
                entry['value'] = 0
                entry['overall_rank'] = 'N/A'
        print(f"Team {team_id}: Value={entry['value']}, OR={entry['overall_rank']}")

    await asyncio.gather(*[fetch_team_data(entry) for entry in standings])

    return standings


