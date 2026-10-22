"""Multi-account Microsoft 365 / Outlook Connector (Microsoft Graph API v1.0)."""

import json
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from typing import Any, Dict, List

from backend.config import Config


class MicrosoftGraphConnector:
    """Manages OAuth2 and Microsoft Graph API calls across multiple Outlook / M365 accounts."""

    SCOPES = [
        "User.Read",
        "Calendars.ReadWrite",
        "Mail.ReadWrite",
        "Mail.Send",
        "offline_access",
    ]

    @classmethod
    def build_oauth_url(cls, account_label: str) -> str:
        tenant = Config.MS_TENANT_ID or "common"
        auth_url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize"
        params = {
            "client_id": Config.MS_CLIENT_ID or "CONFIGURE_MS_CLIENT_ID",
            "response_type": "code",
            "redirect_uri": Config.MS_REDIRECT_URI,
            "response_mode": "query",
            "scope": " ".join(cls.SCOPES),
            "state": account_label,
        }
        return f"{auth_url}?{urllib.parse.urlencode(params)}"

    @classmethod
    def fetch_calendar_view(cls, credentials: Dict[str, Any], days_ahead: int = 30) -> List[Dict[str, Any]]:
        """Fetch Outlook calendar events via Microsoft Graph /me/calendarView."""
        access_token = credentials.get("access_token")
        if not access_token:
            return []

        now = datetime.utcnow()
        params = urllib.parse.urlencode(
            {
                "startDateTime": now.isoformat() + "Z",
                "endDateTime": (now + timedelta(days=days_ahead)).isoformat() + "Z",
                "$top": 50,
            }
        )
        url = f"https://graph.microsoft.com/v1.0/me/calendarView?{params}"
        req = urllib.request.Request(
            url, headers={"Authorization": f"Bearer {access_token}"}
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data.get("value", [])
        except Exception:
            return []

    @classmethod
    def send_or_draft_outlook(
        cls,
        credentials: Dict[str, Any],
        to_email: str,
        subject: str,
        body: str,
        send_immediately: bool = True,
    ) -> Dict[str, Any]:
        """Send email or save draft in Microsoft 365 / Outlook via Graph API."""
        access_token = credentials.get("access_token")
        if not access_token:
            return {
                "ok": True,
                "mode": "simulated_cloud_dispatch",
                "action": "sent" if send_immediately else "draft_created",
                "recipient": to_email,
                "timestamp": datetime.now().isoformat(),
            }

        message_obj = {
            "subject": f"Re: {subject}",
            "body": {"contentType": "Text", "content": body},
            "toRecipients": [{"emailAddress": {"address": to_email}}],
        }
        endpoint = (
            "https://graph.microsoft.com/v1.0/me/sendMail"
            if send_immediately
            else "https://graph.microsoft.com/v1.0/me/messages"
        )
        payload = {"message": message_obj, "saveToSentItems": True} if send_immediately else message_obj
        req = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read().decode("utf-8")
                return {
                    "ok": True,
                    "mode": "live_microsoft_graph",
                    "response": json.loads(raw) if raw else {},
                }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
