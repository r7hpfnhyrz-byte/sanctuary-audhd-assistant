"""Main HTTP & Cloud Server for the 24/7 AuDHD Personal Assistant & Executive Function Coach."""

import json
import mimetypes
import os
import threading
import time
import urllib.parse
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from backend.ai.router import DualAIRouter
from backend.config import BASE_DIR, Config
from backend.connectors.google_connector import GoogleWorkspaceConnector
from backend.connectors.live_ingest import LiveIngestionEngine
from backend.connectors.microsoft_connector import MicrosoftGraphConnector
from backend.database import Database
from backend.engine.briefing_horizon import BriefingHorizonEngine
from backend.engine.email_triage import EmailTriageEngine
from backend.engine.gamification import GamificationEngine
from backend.engine.idea_incubator import IdeaIncubatorEngine
from backend.engine.vault_service import AccomplishmentVaultEngine

STATIC_DIR = Path(__file__).resolve().parent / "static"


class AssistantApplication:
    """Core application controller shared by local HTTP server, tests, and cloud ASGI workers."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db = Database(db_path=db_path)
        self.ai = DualAIRouter()
        self.game = GamificationEngine(self.db)
        self.briefing = BriefingHorizonEngine(self.db, self.ai, self.game)
        self.triage = EmailTriageEngine(self.db, self.ai, self.game)
        self.incubator = IdeaIncubatorEngine(self.db, self.ai, self.game)
        self.vault = AccomplishmentVaultEngine(self.db)
        self.live_ingest = LiveIngestionEngine(self.db, self.ai)

    def handle_api(
        self, method: str, path: str, query: Dict[str, Any], body: Dict[str, Any]
    ) -> Tuple[int, Dict[str, Any]]:
        """Dispatch REST API requests cleanly."""
        if method == "GET" and path == "/api/health":
            return 200, {
                "status": "ok",
                "service": "AuDHD Personal Assistant & Coach",
                "config": Config.status_summary(),
            }

        if method == "GET" and path == "/api/briefing":
            return 200, self.briefing.get_briefing_and_horizons()

        if method == "POST" and path == "/api/energy-mode":
            mode = body.get("mode", "steady")
            state = self.game.set_energy_mode(mode)
            return 200, {
                "ok": True,
                "progress": state,
                "briefing": self.briefing.get_briefing_and_horizons(),
            }

        if method == "POST" and path == "/api/roulette":
            spin = self.game.spin_quick_win_roulette()
            return 200, {"ok": True, "roulette": spin}

        if method == "POST" and path == "/api/roulette/claim-instant":
            xp = int(body.get("xp", 15))
            reason = body.get("reason", "⚡ Quick-Win Roulette Reset Completed")
            state = self.game.award_xp(xp, reason)
            return 200, {"ok": True, "progress": state}

        if method == "POST" and path == "/api/actions/launch-and-complete":
            sid = int(body.get("id", 0))
            auto_complete = bool(body.get("auto_complete", True))
            quick_note = body.get("quick_note", "").strip()
            return 200, self.briefing.execute_and_complete_suggestion(
                sid, auto_complete=auto_complete, quick_note=quick_note
            )

        if method == "POST" and path == "/api/actions/open-target":
            local_path = body.get("local_file_path", "").strip()
            target_url = body.get("target_url", "").strip()
            res = self.briefing.open_local_or_remote_target(local_path, target_url)
            return 200, {"ok": True, "launched": res}

        if method == "POST" and path == "/api/suggestions/complete":
            sid = int(body.get("id", 0))
            quick_note = body.get("quick_note", "").strip()
            return 200, self.briefing.complete_suggestion(sid, quick_note=quick_note)

        if method == "POST" and path == "/api/suggestions/micro-steps":
            sid = int(body.get("id", 0))
            return 200, self.briefing.generate_micro_steps_for_suggestion(sid)

        if method == "POST" and path == "/api/tasks/break-down":
            title = body.get("title", "").strip()
            if not title:
                return 400, {"ok": False, "error": "Please enter a task title"}
            mode = self.game.get_state().get("energy_mode", "steady")
            steps = self.ai.break_into_micro_steps(title, mode)
            return 200, {"ok": True, "title": title, "micro_steps": steps}

        if method == "GET" and path == "/api/emails":
            return 200, {
                "emails": self.triage.list_pending_emails(),
                "progress": self.game.get_state(),
            }

        if method == "POST" and path == "/api/emails/tone":
            eid = int(body.get("id", 0))
            tone = body.get("tone", "shorter")
            return 200, self.triage.shift_tone(eid, tone)

        if method == "POST" and path == "/api/emails/send":
            eid = int(body.get("id", 0))
            draft = body.get("draft_reply", "")
            action = body.get("action", "send")
            return 200, self.triage.approve_and_send(eid, draft, action=action)

        if method == "POST" and path == "/api/emails/triage-custom":
            raw_text = body.get("raw_email_text", "").strip()
            sender = body.get("sender_name", "Work Colleague").strip() or "Work Colleague"
            subj = body.get("subject", "Work Email").strip() or "Work Email"
            if not raw_text:
                return 400, {"ok": False, "error": "Paste the email text first"}
            return 200, self.triage.triage_custom_email(
                raw_email_text=raw_text, sender_name=sender, subject=subj
            )

        if method == "GET" and path == "/api/ideas":
            return 200, {
                "ideas": self.incubator.list_ideas(),
                "progress": self.game.get_state(),
            }

        if method == "POST" and path == "/api/ideas":
            title = body.get("title", "").strip()
            raw_spark = body.get("raw_spark", "").strip()
            category = body.get("category", "Wild Spark")
            if not title and raw_spark:
                title = raw_spark[:52] + ("..." if len(raw_spark) > 52 else "")
            if not title:
                return 400, {"ok": False, "error": "Idea title or description required"}
            return 200, self.incubator.park_and_incubate_idea(
                title=title, raw_spark=raw_spark or title, category=category
            )

        if method == "GET" and path == "/api/vault":
            window = query.get("window", "week")
            return 200, self.vault.get_vault_lookback(window=window)

        if method == "POST" and path == "/api/vault/sync-notion":
            return 200, self.vault.sync_all_to_notion()

        if method == "GET" and path == "/api/coach":
            with self.db.connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM coach_messages ORDER BY id ASC LIMIT 50"
                ).fetchall()
            return 200, {"messages": [dict(r) for r in rows]}

        if method == "POST" and path == "/api/coach":
            msg = body.get("message", "").strip()
            if not msg:
                return 400, {"ok": False, "error": "Message cannot be empty"}
            progress = self.game.get_state()
            mode = progress.get("energy_mode", "steady")
            now = datetime.now().isoformat()

            with self.db.connect() as conn:
                conn.execute(
                    "INSERT INTO coach_messages (role, content, energy_mode, created_at) VALUES ('user', ?, ?, ?)",
                    (msg, mode, now),
                )
                pending_boss = conn.execute(
                    "SELECT title FROM proactive_suggestions WHERE is_cleared = 0 AND is_daily_boss = 1 LIMIT 1"
                ).fetchone()
                pending_emails = conn.execute(
                    "SELECT COUNT(*) AS c FROM triaged_emails WHERE status = 'pending'"
                ).fetchone()["c"]

            context_summary = (
                f"Daily Boss: {pending_boss['title'] if pending_boss else 'All clear!'}; "
                f"Pending Triaged Emails: {pending_emails}; Current XP: {progress.get('xp')}."
            )
            ai_res = self.ai.coach_reply(msg, mode, context_summary)
            reply_text = ai_res["reply"]

            with self.db.connect() as conn:
                conn.execute(
                    "INSERT INTO coach_messages (role, content, energy_mode, created_at) VALUES ('coach', ?, ?, ?)",
                    (reply_text, mode, datetime.now().isoformat()),
                )
                rows = conn.execute(
                    "SELECT * FROM coach_messages ORDER BY id ASC LIMIT 50"
                ).fetchall()

            return 200, {
                "ok": True,
                "reply": reply_text,
                "engine": ai_res["engine"],
                "messages": [dict(r) for r in rows],
            }

        if method == "GET" and path == "/api/accounts":
            with self.db.connect() as conn:
                rows = conn.execute(
                    "SELECT id, provider, account_label, account_identifier, color_tag, portal_url, is_active, last_synced_at FROM connected_accounts ORDER BY id ASC"
                ).fetchall()
            return 200, {
                "accounts": [dict(r) for r in rows],
                "config": Config.status_summary(),
            }

        if method == "POST" and path == "/api/accounts":
            provider = body.get("provider", "google")
            label = body.get("account_label", "").strip()
            identifier = body.get("account_identifier", "").strip()
            token = body.get("api_token", "").strip()
            ics_url = body.get("ics_url", "").strip()
            app_password = body.get("app_password", "").strip()
            color = body.get("color_tag", "#6366f1")
            if not label or not identifier:
                return 400, {"ok": False, "error": "Account label and email/workspace name required"}

            now = datetime.now().isoformat()
            creds = {
                "access_token": token,
                "api_token": token,
                "ics_url": ics_url,
                "app_password": app_password,
            }
            portal = {
                "google": "https://mail.google.com",
                "microsoft": "https://outlook.office.com",
                "notion": "https://www.notion.so",
            }.get(provider, "")
            with self.db.connect() as conn:
                conn.execute(
                    """
                    INSERT INTO connected_accounts (
                        provider, account_label, account_identifier, color_tag,
                        portal_url, credentials_json, is_active, last_synced_at, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
                    """,
                    (provider, label, identifier, color, portal, json.dumps(creds), now, now),
                )
            oauth_url = ""
            if provider == "google":
                oauth_url = GoogleWorkspaceConnector.build_oauth_url(label)
            elif provider == "microsoft":
                oauth_url = MicrosoftGraphConnector.build_oauth_url(label)

            return 200, {"ok": True, "oauth_url": oauth_url}

        if method == "POST" and path == "/api/sync/live":
            clear_demo = bool(body.get("clear_demo_data", False))
            sync_res = self.live_ingest.sync_all_live_accounts(clear_demo_data=clear_demo)
            return 200, sync_res

        if method == "POST" and path == "/api/settings/keys":
            gemini_key = body.get("gemini_api_key", "").strip()
            claude_key = body.get("anthropic_api_key", "").strip()
            if gemini_key:
                os.environ["GEMINI_API_KEY"] = gemini_key
                Config.GEMINI_API_KEY = gemini_key
            if claude_key:
                os.environ["ANTHROPIC_API_KEY"] = claude_key
                Config.ANTHROPIC_API_KEY = claude_key

            env_file = BASE_DIR / ".env"
            lines = []
            if env_file.exists():
                lines = [
                    l
                    for l in env_file.read_text(encoding="utf-8").splitlines()
                    if not l.startswith("GEMINI_API_KEY=") and not l.startswith("ANTHROPIC_API_KEY=")
                ]
            if Config.GEMINI_API_KEY:
                lines.append(f"GEMINI_API_KEY={Config.GEMINI_API_KEY}")
            if Config.ANTHROPIC_API_KEY:
                lines.append(f"ANTHROPIC_API_KEY={Config.ANTHROPIC_API_KEY}")
            env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

            self.ai.refresh_keys()
            return 200, {"ok": True, "config": Config.status_summary()}

        if method in ("GET", "POST") and path == "/api/webhooks/notion":
            # Instant Notion Webhook receiver (handles verification_token challenge & live page events)
            if "verification_token" in body:
                return 200, {"ok": True, "verification_token": body["verification_token"]}
            sync_res = self.live_ingest.sync_all_live_accounts(clear_demo_data=False)
            return 200, {"ok": True, "webhook_synced": sync_res}

        if method in ("GET", "POST") and path == "/api/cron/daily-briefing":
            self.live_ingest.sync_all_live_accounts(clear_demo_data=False)
            briefing_data = self.briefing.get_briefing_and_horizons()
            notion_sync = self.vault.sync_all_to_notion()
            return 200, {
                "ok": True,
                "triggered_at": datetime.now().isoformat(),
                "briefing_generated": True,
                "notion_sync": notion_sync,
                "headline": briefing_data.get("coach_headline"),
            }

        return 404, {"error": f"Unknown endpoint {method} {path}"}


app_instance = AssistantApplication()


class AssistantHTTPRequestHandler(BaseHTTPRequestHandler):
    """Zero-dependency HTTP handler serving the Web UI and REST API."""

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def _send_json(self, status: int, payload: Dict[str, Any]) -> None:
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _serve_static(self, rel_path: str) -> None:
        if rel_path in ("", "/"):
            rel_path = "index.html"
        target = (STATIC_DIR / rel_path.lstrip("/")).resolve()
        if not str(target).startswith(str(STATIC_DIR.resolve())) or not target.is_file():
            target = STATIC_DIR / "index.html"

        content = target.read_bytes()
        mime_type, _ = mimetypes.guess_type(str(target))
        self.send_response(200)
        self.send_header("Content-Type", f"{mime_type or 'text/html'}; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path.startswith("/api/"):
            qs = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
            status, payload = app_instance.handle_api("GET", parsed.path, qs, {})
            self._send_json(status, payload)
        else:
            self._serve_static(parsed.path)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
        try:
            body = json.loads(raw_body) if raw_body else {}
        except Exception:
            body = {}
        qs = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
        status, payload = app_instance.handle_api("POST", parsed.path, qs, body)
        self._send_json(status, payload)


def start_background_cloud_scheduler(controller: AssistantApplication) -> None:
    """Background daemon thread that auto-captures new Notion pages/emails every 5 mins & runs 07:30 briefings."""

    def _loop() -> None:
        last_run_date = ""
        ticks = 0
        # On fresh cloud container boot, if live credentials are provided via env vars, auto-sync immediately
        if Config.NOTION_API_KEY or Config.GOOGLE_ICS_ROB or Config.GOOGLE_APP_PASSWORD_ROB:
            try:
                with controller.db.connect() as conn:
                    cnt = conn.execute("SELECT COUNT(*) AS c FROM proactive_suggestions").fetchone()["c"]
                if cnt <= 10:
                    controller.live_ingest.sync_all_live_accounts(clear_demo_data=True)
            except Exception:
                pass
        while True:
            now = datetime.now()
            hhmm = now.strftime("%H:%M")
            today_str = now.strftime("%Y-%m-%d")
            # Every 5 minutes (10 ticks x 30s), automatically pull any newly created Notion pages, calendar events, or emails
            if ticks > 0 and ticks % 10 == 0:
                try:
                    controller.live_ingest.sync_all_live_accounts(clear_demo_data=False)
                except Exception:
                    pass
            if hhmm == Config.BRIEFING_TIME_LOCAL and last_run_date != today_str:
                try:
                    controller.live_ingest.sync_all_live_accounts(clear_demo_data=False)
                    controller.vault.sync_all_to_notion()
                    last_run_date = today_str
                except Exception:
                    pass
            ticks += 1
            time.sleep(30)

    t = threading.Thread(target=_loop, daemon=True)
    t.start()


def run_server(host: Optional[str] = None, port: Optional[int] = None) -> None:
    bind_host = host or Config.HOST
    bind_port = port or Config.PORT
    start_background_cloud_scheduler(app_instance)
    server = ThreadingHTTPServer((bind_host, bind_port), AssistantHTTPRequestHandler)
    print(f"✨ AuDHD Personal Assistant & Coach running at http://localhost:{bind_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


if __name__ == "__main__":
    run_server()
