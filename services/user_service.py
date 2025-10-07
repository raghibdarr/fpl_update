from utils.api_helpers import fetch_fpl_data


async def fetch_user_team_name(fpl_id: int) -> str:
    user_data = await fetch_fpl_data(f"entry/{fpl_id}/")
    return user_data['name']


async def fetch_user_total_points(fpl_id: int) -> int:
    user_data = await fetch_fpl_data(f"entry/{fpl_id}/")
    return user_data['summary_overall_points']


