import http.client
import os
from dotenv import load_dotenv
import json

# Competition IDs for various cups already retrieved previously via API
PREMIER_LEAGUE_ID = 1
FA_CUP_ID = 21
EFL_CUP_ID = 22
UCL_ID = 24
UEL_ID = 25
UECL_ID = 116

# Create a mapping between PL team abbreviations (used in FPL) and team names from API
pl_abbreviations_mapping = {
    'ARS': 'Arsenal', 'AVL': 'Aston Villa', 'BOU': 'AFC Bournemouth', 'BRE': 'Brentford',
    'BHA': 'Brighton & Hove Albion', 'CHE': 'Chelsea', 'CRY': 'Crystal Palace', 'EVE': 'Everton',
    'FUL': 'Fulham', 'LIV': 'Liverpool', 'MCI': 'Manchester City', 'MUN': 'Manchester United',
    'NEW': 'Newcastle United', 'NFO': 'Nottingham Forest', 'SOU': 'Southampton', 'TOT': 'Tottenham Hotspur',
    'WHU': 'West Ham United', 'WOL': 'Wolverhampton Wanderers', 'LEI': 'Leicester City', 'IPS': 'Ipswich Town'
}

# Load environment variables from .env file
load_dotenv()

# Get the API key from environment variables
rapidapi_key = os.getenv('RAPIDAPI_KEY')

# Establish a connection to the API endpoint
conn = http.client.HTTPSConnection("football-web-pages1.p.rapidapi.com")

# Set up the headers required for the API request - these include the API key and host information
headers = {
    'x-rapidapi-key': rapidapi_key,
    'x-rapidapi-host': "football-web-pages1.p.rapidapi.com"
}

### GET PREMIER LEAGUE TEAMS ###

# Make GET request to get premier league teams
conn.request("GET", "/teams.json?comp=" + str(PREMIER_LEAGUE_ID), headers=headers)
prem_teams = conn.getresponse()
prem_teams_data = prem_teams.read()

# Parse the JSON data
prem_teams_json = json.loads(prem_teams_data.decode("utf-8"))

# Extract only the IDs into a list
prem_team_ids = [team['id'] for team in prem_teams_json['teams']]

# Print the list of Premier League team IDs
print("Premier League Team IDs:", prem_team_ids)

# Function to get filtered fixtures
def get_filtered_fixtures(competition_id, prem_team_ids, competition_name):
    # Get the fixtures/results of the competition
    conn.request("GET", f"/fixtures-results.json?comp={competition_id}", headers=headers)
    fixtures = conn.getresponse()
    fixtures_data = fixtures.read()

    # Parse the JSON data for fixtures
    fixtures_json = json.loads(fixtures_data.decode("utf-8"))

    # Filter fixtures
    filtered_fixtures = []
    excluded_rounds = ['First Qualifying Round', 'Second Qualifying Round', 'Third Qualifying Round']

    for match in fixtures_json['fixtures-results']['matches']:
        # Use .get() method to safely access potentially missing keys
        home_team_id = match.get('home-team', {}).get('id')
        away_team_id = match.get('away-team', {}).get('id')
        round_name = match.get('round', {}).get('name')
        status = match.get('status', {}).get('short')
        
        # Check if the home or away team is a Premier League team, has not finished and is not in the excluded rounds
        if ((home_team_id in prem_team_ids or away_team_id in prem_team_ids) and
            round_name not in excluded_rounds and
            status != 'FT'):
            
            home_team_name = match.get('home-team', {}).get('name', '')
            away_team_name = match.get('away-team', {}).get('name', '')
            
            # Get or generate abbreviations
            home_team_abbr = next((abbr for abbr, name in pl_abbreviations_mapping.items() if name == home_team_name), 
                                  generate_abbreviation(home_team_name))
            away_team_abbr = next((abbr for abbr, name in pl_abbreviations_mapping.items() if name == away_team_name), 
                                  generate_abbreviation(away_team_name))

            filtered_fixtures.append({
                'date': match.get('date'),
                'home_team': home_team_name,
                'away_team': away_team_name,
                'home_team_abbr': home_team_abbr,
                'away_team_abbr': away_team_abbr,
                'competition': competition_name,
                'matchday': round_name
            })

    return filtered_fixtures

# Function to generate abbreviations for non-PL teams
def generate_abbreviation(team_name):
    words = team_name.split()
    if len(words) == 1:
        return team_name[:3].upper() # If the team name is a single word, return the first three characters
    elif len(words) == 2:
        return (words[0][0] + words[1][:2]).upper() # If the team name is two words, return the first character of the first word and the first two characters of the second word
    else:
        return ''.join(word[0] for word in words[:3]).upper()

# Get fixtures for each competition
all_fixtures = {
    'UCL': get_filtered_fixtures(UCL_ID, prem_team_ids, 'UCL'),
    'UEL': get_filtered_fixtures(UEL_ID, prem_team_ids, 'UEL'),
    'UECL': get_filtered_fixtures(UECL_ID, prem_team_ids, 'UECL'),
    'EFL': get_filtered_fixtures(EFL_CUP_ID, prem_team_ids, 'EFL')
}

print (f"All fixtures: {all_fixtures}")