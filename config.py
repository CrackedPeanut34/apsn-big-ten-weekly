"""Environment configuration, loaded once from .env (local) or the process
environment (GitHub Actions secrets)."""
import os

from dotenv import load_dotenv

load_dotenv()

CFBD_API_KEY = os.environ.get("CFBD_API_KEY", "")
DATABASE_URL = os.environ.get("DATABASE_URL", "")

CFBD_BASE_URL = "https://api.collegefootballdata.com"
CONFERENCE = "B1G"
