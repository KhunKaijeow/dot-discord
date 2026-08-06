"""Environment-backed application configuration."""

import os
from dotenv import load_dotenv

# Railway injects these values into the process environment. load_dotenv keeps
# local development with a git-ignored .env file convenient.
load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TYPHOON_API_KEY = os.getenv("TYPHOON_API_KEY")
VALORANT_API_KEY = os.getenv("VALORANT_API_KEY")
TOGETHER_API_KEY = os.getenv("TOGETHER_API_KEY")
PROKERALA_CLIENT_ID = os.getenv("PROKERALA_CLIENT_ID")
PROKERALA_CLIENT_SECRET = os.getenv("PROKERALA_CLIENT_SECRET")
