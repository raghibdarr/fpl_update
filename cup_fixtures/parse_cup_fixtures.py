import json
from datetime import datetime
import re

def parse_european_fixtures(file_path, competition):
    fixtures = []
    current_matchday = None
    with open(file_path, 'r', encoding='utf-8') as file:
        for line in file:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            
            # Check for Matchday
            if line.startswith('Matchday'):
                current_matchday = line
                continue
            
            # Check for fixture
            parts = line.split('\t')
            if len(parts) >= 3:  # More lenient check
                home_team, date_or_score, away_team = parts[:3]
                if re.match(r'\d{1,2} \w{3}', date_or_score):  # Check if it's a date
                    date = datetime.strptime(date_or_score, "%d %b")
                    date = date.replace(year=2024)  # Assuming all fixtures are in 2024
                    
                    # Include all fixtures, not just English teams
                    fixtures.append({
                        'date': date.strftime("%Y-%m-%d"),
                        'home_team': home_team,
                        'away_team': away_team,
                        'competition': competition,
                        'matchday': current_matchday
                    })
    
    print(f"Parsed {len(fixtures)} fixtures for {competition}")
    return fixtures

def parse_efl_fixtures(file_path):
    fixtures = []
    with open(file_path, 'r', encoding='utf-8') as file:
        for line in file:
            parts = line.strip().split('\t')
            if len(parts) == 5:  # Date, Home Team, 'v', Away Team, Venue
                date, home_team, _, away_team, _ = parts
                date = datetime.strptime(date, "%d %B %Y")
                
                # Extract team names and remove league tier
                home_team = re.sub(r'\s*\(\d+\)$', '', home_team)
                away_team = re.sub(r'\s*\(\d+\)$', '', away_team)
                
                fixtures.append({
                    'date': date.strftime("%Y-%m-%d"),
                    'home_team': home_team,
                    'away_team': away_team,
                    'competition': 'EFL'
                })
    
    print(f"Parsed {len(fixtures)} fixtures for EFL")
    return fixtures

# Parse each competition
competitions = {
    'UCL': 'ucl_fixtures.txt',
    'UEL': 'uel_fixtures.txt',
    'UECL': 'uecl_fixtures.txt',
    'EFL': 'efl_fixtures.txt'
}

all_fixtures = {}

for comp, file_path in competitions.items():
    print(f"Processing {comp} fixtures from {file_path}")
    if comp in ['UCL', 'UEL', 'UECL']:
        all_fixtures[comp] = parse_european_fixtures(file_path, comp)
    elif comp == 'EFL':
        all_fixtures[comp] = parse_efl_fixtures(file_path)

# Add placeholder for FA Cup
all_fixtures['FA'] = []

# Write to JSON file
with open('cup_fixtures.json', 'w', encoding='utf-8') as json_file:
    json.dump(all_fixtures, json_file, ensure_ascii=False, indent=2)

print("Fixtures have been parsed and saved to cup_fixtures.json")