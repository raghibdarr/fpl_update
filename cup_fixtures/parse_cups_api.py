import http.client
import os
from dotenv import load_dotenv

# Competition IDs for various cups already retrieved previously via API
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

# Make a GET request to the API endpoint
# This specific request is for fixtures-results of competition with ID 24 (UCL)
conn.request("GET", "/fixtures-results.json?comp=24", headers=headers)

# Get the response from the API
res = conn.getresponse()
# Read the response data
data = res.read()

# Print the decoded response data
print(data.decode("utf-8"))