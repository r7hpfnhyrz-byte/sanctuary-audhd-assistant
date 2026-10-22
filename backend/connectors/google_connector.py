"""Multi-account Google Connector (Gmail API v1 + Google Calendar API v3)."""

import base64
import json
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from typing import Any, Dict, List

from backend.config import Config


class GoogleWorkspaceConnector:
    """Manages OAuth2 and REST sync across multiple Google Gmail & Calendar accounts."""

    AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN_URL = "https://oauth2.googleapis.com/token"
    SCOPES = [
        "https://www.googleapis.com/auth/calendar.readonly",
        "https://www.googleapis.com/auth/calendar.events",
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.compose",
        "https://www.googleapis.com/auth/gmail.send",
    ]

    @classmethod
    def build_oauth_url(cls, account_label: str) -> str:
        params = {
            "client_id": Config.GOOGLE_CLIENT_ID or "CONFIGURE_GOOGLE_CLIENT_ID",
            "redirect_uri": Config.GOOGLE_REDIRECT_URI,
            "response_type": "code",
            "scope": " ".join(cls.SCOPES),
            "access_type": "offline",
            "prompt": "consent",
            "state": account_label,
        }
        return f"{cls.AUTH_URL}?{urllib.parse.urlencode(params)}"

    @classmethod
    def fetch_calendar_events(cls, credentials: Dict[str, Any], days_ahead: int = 30) -> List[Dict[str, Any]]:
        """Fetch upcoming events from Google Calendar API v3 if access_token is present."""
        access_token = credentials.get("access_token")
        if not access_token:
            return []

        now = datetime.utcnow()
        time_min = now.isoformat() + "Z"
        time_max = (now + timedelta(days=days_ahead)).isoformat() + "Z"
        url = (
            "https://www.googleapis.com/calendar/v3/calendars/primary/events?"
            + urllib.parse.urlencode(
                {
                    "timeMin": time_min,
                    "timeMax": time_max,
                    "singleEvents": "true",
                    "orderBy": "startTime",
                    "maxResults": 50,
                }
            )
        )
        req = urllib.request.Request(
            url, headers={"Authorization": f"Bearer {access_token}"}
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
                return payload.get("items", [])
        except Exception:
            return []

    @classmethod
    def send_or_draft_gmail(
        cls,
        credentials: Dict[str, Any],
        to_email: str,
        subject: str,
        body: str,
        send_immediately: bool = True,
    ) -> Dict[str, Any]:
        """Send email or create a draft in the connected Gmail inbox."""
        access_token = credentials.get("access_token")
        raw_msg = f"To: {to_email}\r\nSubject: Re: {subject}\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n{body}"
        encoded_msg = base64.urlsafe_b64encode(raw_msg.encode("utf-8")).decode("utf-8")

        if not access_token:
            return {
                "ok": True,
                "mode": "simulated_cloud_dispatch",
                "action": "sent" if send_immediately else "draft_created",
                "recipient": to_email,
                "timestamp": datetime.now().isoformat(),
            }

        endpoint = (
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
            if send_immediately
            else "https://gmail.googleapis.com/gmail/v1/users/me/drafts"
        )
        body_payload = (
            {"raw": encoded_msg}
            if send_immediately
            else {"message": {"raw": encoded_msg}}
        )
        req = urllib.request.Request(
            endpoint,
            data=json.dumps(body_payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return {"ok": True, "mode": "live_gmail_api", "response": data}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
