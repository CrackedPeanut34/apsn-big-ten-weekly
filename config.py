"""Environment configuration, loaded once from .env (local) or the process
environment (GitHub Actions secrets)."""
import os

from dotenv import load_dotenv

load_dotenv()

CFBD_API_KEY = os.environ.get("CFBD_API_KEY", "")
DATABASE_URL = os.environ.get("DATABASE_URL", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

CFBD_BASE_URL = "https://api.collegefootballdata.com"
CONFERENCE = "B1G"

# Kill switch for summarize/generate.py. Must be explicitly "true" -- any
# other value (including unset) disables LLM summary generation before it
# makes a DB connection or an API call. Flip locally in .env, or as a GitHub
# Actions repo variable/secret if this is ever wired into a workflow.
LLM_SUMMARIES_ENABLED = os.environ.get("LLM_SUMMARIES_ENABLED", "").lower() == "true"
LLM_SUMMARY_MODEL = os.environ.get("LLM_SUMMARY_MODEL", "claude-opus-5")
