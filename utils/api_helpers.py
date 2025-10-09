import aiohttp

# Base URLs for APIs (duplicated here to preserve original behavior without cross-module coupling changes)
FPL_API_BASE = "https://fantasy.premierleague.com/api/"
PULSE_API_BASE = "https://sdp-prem-prod.premier-league-prod.pulselive.com/api/v2/"


async def fetch_api_data(session, url, params=None):
    async with session.get(url, params=params) as response:
        response.raise_for_status()
        return await response.json()


async def fetch_fpl_data(endpoint: str, params=None):
    async with aiohttp.ClientSession() as session:
        return await fetch_api_data(session, f"{FPL_API_BASE}{endpoint}", params)