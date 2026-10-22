"""Configuration management for the 24/7 AuDHD Personal Assistant."""

import os
from pathlib import Path
from typing import Dict, Any

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_dotenv_file(env_path: Path) -> None:
    """Lightweight .env loader with zero external dependencies."""
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value


load_dotenv_file(BASE_DIR / ".env")


class Config:
    """Central configuration for AI models, OAuth connectors, and Cloud runtime."""

    PORT: int = int(os.environ.get("PORT", "8765"))
    HOST: str = os.environ.get("HOST", "0.0.0.0")
    DB_PATH: Path = Path(os.environ.get("AUDHD_DB_PATH", str(DATA_DIR / "assistant.db")))

    #Dual AI Engine Keys (Google Gemini + Anthropic Claude)
    GEMINI_API_KEY: str = os.environ.get("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    ANTHROPIC_API_KEY: str = os.environ.get("ANTHROPIC_API_KEY", "")
    ANTHROPIC_MODEL: str = os.environ.get("ANTHROPIC_MODEL", "claude-3-7-sonnet-latest")

    # Notion Integration Key
    NOTION_API_KEY: str = os.environ.get("NOTION_API_KEY", "")

    # Live Google Calendar iCal Feeds & Gmail App Passwords
    GOOGLE_ICS_ROB: str = os.environ.get("GOOGLE_ICS_ROB", "")
    GOOGLE_ICS_FAMILY: str = os.environ.get("GOOGLE_ICS_FAMILY", "")
    GOOGLE_APP_PASSWORD_ROB: str = os.environ.get("GOOGLE_APP_PASSWORD_ROB", "")
    GOOGLE_APP_PASSWORD_FAMILY: str = os.environ.get("GOOGLE_APP_PASSWORD_FAMILY", "")

    # Google OAuth2 (Supports linking multiple accounts)
    GOOGLE_CLIENT_ID: str = os.environ.get("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET: str = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    GOOGLE_REDIRECT_URI: str = os.environ.get(
        "GOOGLE_REDIRECT_URI", "http://localhost:8765/api/auth/google/callback"
    )

    # Microsoft 365 / Outlook Graph OAuth2 (Supports linking multiple accounts)
    MS_CLIENT_ID: str = os.environ.get("MS_CLIENT_ID", "")
    MS_CLIENT_SECRET: str = os.environ.get("MS_CLIENT_SECRET", "")
    MS_TENANT_ID: str = os.environ.get("MS_TENANT_ID", "common")
    MS_REDIRECT_URI: str = os.environ.get(
        "MS_REDIRECT_URI", "http://localhost:8765/api/auth/microsoft/callback"
    )

    # Morning Briefing Schedule (24/7 Cloud Scheduler default)
    BRIEFING_TIME_LOCAL: str = os.environ.get("BRIEFING_TIME_LOCAL", "07:30")
    TIMEZONE: str = os.environ.get("TIMEZONE", "Europe/London")

    @classmethod
    def status_summary(cls) -> Dict[str, Any]:
        return {
            "gemini_configured": bool(cls.GEMINI_API_KEY),
            "claude_configured": bool(cls.ANTHROPIC_API_KEY),
            "notion_configured": bool(cls.NOTION_API_KEY),
            "google_oauth_configured": bool(cls.GOOGLE_CLIENT_ID and cls.GOOGLE_CLIENT_SECRET),
            "microsoft_oauth_configured": bool(cls.MS_CLIENT_ID and cls.MS_CLIENT_SECRET),
            "briefing_time": cls.BRIEFING_TIME_LOCAL,
            "timezone": cls.TIMEZONE,
            "storage_path": str(cls.DB_PATH),
        }
