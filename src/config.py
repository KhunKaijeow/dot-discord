"""Environment-backed application configuration."""

import os
from dotenv import load_dotenv

# Railway injects these values into the process environment. load_dotenv keeps
# local development with a git-ignored .env file convenient.
load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
TYPHOON_API_KEY = os.getenv("TYPHOON_API_KEY")
VALORANT_API_KEY = os.getenv("VALORANT_API_KEY")
TOGETHER_API_KEY = os.getenv("TOGETHER_API_KEY")
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
PROKERALA_CLIENT_ID = os.getenv("PROKERALA_CLIENT_ID")
PROKERALA_CLIENT_SECRET = os.getenv("PROKERALA_CLIENT_SECRET")


REQUIRED_ENVIRONMENT_VARIABLES = {
    "DISCORD_TOKEN": DISCORD_TOKEN,
    "TYPHOON_API_KEY": TYPHOON_API_KEY,
}


def missing_required_environment_variables() -> list[str]:
    """Return required configuration names that have no value."""
    return [name for name, value in REQUIRED_ENVIRONMENT_VARIABLES.items() if not value]
