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

### Make GET requests to the API endpoint ##

# Get premier league teams
conn.request("GET", "/teams.json?comp=" + str(PREMIER_LEAGUE_ID), headers=headers)
prem_teams = conn.getresponse()
prem_teams_data = prem_teams.read()

# Parse the JSON data
prem_teams_json = json.loads(prem_teams_data.decode("utf-8"))

# Extract only the IDs into a list
prem_team_ids = [team['id'] for team in prem_teams_json['teams']]

# Print the list of Premier League team IDs
print("Premier League Team IDs:", prem_team_ids)


# Get the fixtures/results of UCL
conn.request("GET", "/fixtures-results.json?comp=24", headers=headers)

# TO-DO: Filter the data to only include fixtures/results of premier league teams

# Get the response from the API
res = conn.getresponse()
# Read the response data
data = res.read()

# Print the decoded response data
#print(data.decode("utf-8"))