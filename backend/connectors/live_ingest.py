"""Low-Friction Live Ingestion Engine for Notion (Auto-Discovery), Google/Outlook Calendars (iCal .ics + OAuth), and Inboxes (IMAP/SMTP + OAuth)."""

import email
import imaplib
import json
import re
import smtplib
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from email.header import decode_header
from email.mime.text import MIMEText
from typing import Any, Dict, List, Optional

from backend.ai.router import DualAIRouter
from backend.config import Config
from backend.database import Database


class LiveIngestionEngine:
    """Pulls live calendar events, unread emails, and Notion workspace items and synthesizes them with Gemini & Claude."""

    def __init__(self, db: Database, ai: DualAIRouter) -> None:
        self.db = db
        self.ai = ai
        # Set by fetch_notion_workspace_items whenever the Notion API call itself fails,
        # so the sync endpoint can tell the dashboard WHY 0 items came back instead of
        # silently swallowing the error (401 invalid token, network issue, etc.)
        self.last_notion_error: str = ""

    # -------------------------------------------------------------------------
    # 1. FULL NOTION ENVIRONMENT CRAWLER (Pages, Databases, Rows & To-Do Blocks)
    # -------------------------------------------------------------------------
    def fetch_notion_workspace_items(self, notion_token: str, account_label: str) -> List[Dict[str, Any]]:
        """Paginate through the entire Notion workspace: discover all databases, pages, rows, due dates, and unchecked to-do blocks."""
        self.last_notion_error = ""
        if not notion_token:
            self.last_notion_error = "No Notion API key configured."
            return []

        headers = {
            "Authorization": f"Bearer {notion_token}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        }
        all_objects: List[Dict[str, Any]] = []
        next_cursor: Optional[str] = None

        # Paginate through /v1/search to get the entire Notion environment
        for _ in range(10):
            payload: Dict[str, Any] = {
                "page_size": 100,
                "sort": {"direction": "descending", "timestamp": "last_edited_time"},
            }
            if next_cursor:
                payload["start_cursor"] = next_cursor

            req = urllib.request.Request(
                "https://api.notion.com/v1/search",
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=20) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    all_objects.extend(data.get("results", []))
                    if not data.get("has_more") or not data.get("next_cursor"):
                        break
                    next_cursor = data.get("next_cursor")
            except urllib.error.HTTPError as exc:
                try:
                    body = json.loads(exc.read().decode("utf-8"))
                    notion_msg = body.get("message", "")
                except Exception:
                    notion_msg = ""
                self.last_notion_error = f"Notion API rejected the request (HTTP {exc.code}): {notion_msg or exc.reason}"
                break
            except Exception as exc:
                self.last_notion_error = f"Could not reach Notion API: {exc}"
                break

        if not all_objects and not self.last_notion_error:
            self.last_notion_error = (
                "Notion API call succeeded but returned 0 shared pages/databases — "
                "the integration likely isn't connected to anything yet."
            )

        items: List[Dict[str, Any]] = []
        seen_ids = set()

        for obj in all_objects:
            obj_id = obj.get("id", "")
            if not obj_id or obj_id in seen_ids:
                continue
            seen_ids.add(obj_id)

            obj_type = obj.get("object", "page")
            title = self._extract_notion_title(obj)
            if not title or title.startswith("Sanctuary AuDHD Briefing"):
                continue

            meta = self._extract_notion_properties_meta(obj)
            # Skip items explicitly marked Done/Completed/Archived in Notion databases
            if meta.get("is_done"):
                continue

            items.append(
                {
                    "notion_id": obj_id,
                    "object_type": obj_type,
                    "title": title,
                    "url": obj.get("url", "https://www.notion.so"),
                    "last_edited": obj.get("last_edited_time", ""),
                    "status_label": meta.get("status", ""),
                    "due_date": meta.get("due_date", ""),
                    "horizon": meta.get("horizon", "1d"),
                    "account_label": account_label,
                    "type_label": meta.get("type_label", ""),
                    "category_label": meta.get("category_label", ""),
                    "priority_label": meta.get("priority_label", ""),
                }
            )

            # Also inspect top pages for unchecked to_do checkboxes (- [ ] tasks)
            if obj_type == "page" and len(items) < 60:
                todo_items = self._fetch_unchecked_todos_from_page(
                    page_id=obj_id,
                    page_title=title,
                    page_url=obj.get("url", "https://www.notion.so"),
                    headers=headers,
                    account_label=account_label,
                )
                items.extend(todo_items)

        # Soonest-due items first (so the Daily Boss & horizon order reflect real urgency,
        # not just whatever Notion's last-edited search order happened to surface).
        # Items without a due date keep their relative discovery order, sunk to the back.
        items.sort(key=lambda it: (0, it["due_date"]) if it.get("due_date") else (1, ""))
        return items

    def _fetch_unchecked_todos_from_page(
        self,
        page_id: str,
        page_title: str,
        page_url: str,
        headers: Dict[str, str],
        account_label: str,
    ) -> List[Dict[str, Any]]:
        url = f"https://api.notion.com/v1/blocks/{page_id}/children?page_size=50"
        req = urllib.request.Request(url, headers=headers, method="GET")
        todos: List[Dict[str, Any]] = []
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                for block in data.get("results", []):
                    if block.get("type") == "to_do":
                        todo_data = block.get("to_do", {})
                        if not todo_data.get("checked", False):
                            rich = todo_data.get("rich_text", [])
                            text = "".join(t.get("plain_text", "") for t in rich).strip()
                            if text:
                                todos.append(
                                    {
                                        "notion_id": block.get("id", ""),
                                        "object_type": "to_do_block",
                                        "title": f"{text} (in {page_title})",
                                        "url": page_url,
                                        "last_edited": block.get("last_edited_time", ""),
                                        "status_label": "Unchecked To-Do",
                                        "due_date": "",
                                        "horizon": "1d",
                                        "account_label": account_label,
                                    }
                                )
        except Exception:
            return []
        return todos

    @staticmethod
    def _extract_notion_title(obj: Dict[str, Any]) -> str:
        if obj.get("object") == "database":
            title_arr = obj.get("title", [])
            if title_arr:
                return "🗂️ [Database] " + "".join(t.get("plain_text", "") for t in title_arr).strip()
        props = obj.get("properties", {})
        for _, prop_val in props.items():
            if prop_val.get("type") == "title":
                title_arr = prop_val.get("title", [])
                if title_arr:
                    return "".join(t.get("plain_text", "") for t in title_arr).strip()
        return ""

    @staticmethod
    def _extract_notion_properties_meta(obj: Dict[str, Any]) -> Dict[str, Any]:
        """Extract Status, Type/Category/Priority, and due-date properties from Notion database rows
        to assign accurate 1d/2d/1w/1m horizons.

        Databases with more than one select property (e.g. Category + Type + Priority + Status) or
        more than one date property (e.g. Start Date + End Date) need to be matched by property NAME,
        not just by type, otherwise whichever property happens to be last in the API response silently
        overwrites the real Status/due date.
        """
        props = obj.get("properties", {})
        now = datetime.now()

        select_props: Dict[str, str] = {}
        date_props: Dict[str, str] = {}
        is_done = False

        for prop_name, pval in props.items():
            ptype = pval.get("type")
            name_lower = prop_name.strip().lower()
            if ptype in ("status", "select") and pval.get(ptype):
                opt_name = (pval[ptype].get("name") or "").strip()
                if opt_name:
                    select_props[name_lower] = opt_name
                    if opt_name.lower() in ("done", "completed", "complete", "archived", "cancelled"):
                        is_done = True
            elif ptype == "checkbox":
                if pval.get("checkbox") is True:
                    is_done = True
            elif ptype == "date" and pval.get("date") and pval["date"].get("start"):
                date_props[name_lower] = pval["date"]["start"][:10]

        def _pick(options: Dict[str, str], preferred_names: List[str]) -> str:
            for pname in preferred_names:
                if pname in options:
                    return options[pname]
            return next(iter(options.values()), "")

        status_str = _pick(select_props, ["status"])
        type_label = _pick(select_props, ["type"])
        category_label = _pick(select_props, ["category"])
        priority_label = _pick(select_props, ["priority"])

        due_str = ""
        for pname in ("due date", "deadline", "end date", "due"):
            if pname in date_props:
                due_str = date_props[pname]
                break
        if not due_str:
            non_start_dates = {k: v for k, v in date_props.items() if "start" not in k}
            due_str = next(iter(non_start_dates.values()), "") or next(iter(date_props.values()), "")

        horizon = ""
        if due_str:
            try:
                due_dt = datetime.strptime(due_str, "%Y-%m-%d")
                days = (due_dt - now).days
                if days <= 1:
                    horizon = "1d"
                elif days <= 3:
                    horizon = "2d"
                elif days <= 8:
                    horizon = "1w"
                else:
                    horizon = "1m"
            except Exception:
                pass

        return {
            "status": status_str,
            "due_date": due_str,
            "is_done": is_done,
            "horizon": horizon,
            "type_label": type_label,
            "category_label": category_label,
            "priority_label": priority_label,
        }

    # -------------------------------------------------------------------------
    # 2. LIVE CALENDAR INGESTION VIA iCal (.ics URL) FOR GOOGLE & OUTLOOK
    # -------------------------------------------------------------------------
    def fetch_ical_events(self, ics_url: str, account_label: str, provider: str) -> List[Dict[str, Any]]:
        """Fetch and parse upcoming events from any Google Calendar or Outlook .ics feed URL."""
        if not ics_url or not ics_url.startswith("http"):
            return []
        req = urllib.request.Request(ics_url, headers={"User-Agent": "Sanctuary-AuDHD-Assistant/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw_ics = resp.read().decode("utf-8", errors="ignore")
        except Exception:
            return []

        # Unfold RFC 5545 multi-line values
        raw_ics = re.sub(r"\r?\n[ \t]", "", raw_ics)
        now = datetime.now()
        raw_events: List[Dict[str, Any]] = []
        blocks = raw_ics.split("BEGIN:VEVENT")[1:]
        for block in blocks:
            summary_m = re.search(r"^SUMMARY(?:;[^:]*)?:(.*)$", block, re.MULTILINE)
            dtstart_m = re.search(r"^DTSTART(?:;[^:]*)?:([0-9T]+)", block, re.MULTILINE)
            dtend_m = re.search(r"^DTEND(?:;[^:]*)?:([0-9T]+)", block, re.MULTILINE)
            loc_m = re.search(r"^LOCATION(?:;[^:]*)?:(.*)$", block, re.MULTILINE)
            if not summary_m or not dtstart_m:
                continue

            title = summary_m.group(1).strip().replace("\\,", ",").replace("\\;", ";")
            dt_str = dtstart_m.group(1).strip()
            end_str = dtend_m.group(1).strip() if dtend_m else dt_str
            loc = loc_m.group(1).strip().replace("\\,", ",") if loc_m else ""

            start_dt = self._parse_ics_datetime(dt_str)
            end_dt = self._parse_ics_datetime(end_str) or (start_dt + timedelta(hours=1) if start_dt else None)
            if not start_dt or start_dt < now - timedelta(hours=4) or start_dt > now + timedelta(days=32):
                continue

            delta_hours = (start_dt - now).total_seconds() / 3600.0
            if delta_hours <= 36:
                horizon = "1d"
            elif delta_hours <= 72:
                horizon = "2d"
            elif delta_hours <= 180:
                horizon = "1w"
            else:
                horizon = "1m"

            drive_root = "/Users/student/Library/CloudStorage/GoogleDrive-robknightstrong@gmail.com/My Drive"
            local_file = ""
            target_label = "📅 Open in Google Calendar" if provider == "google" else "📅 Open in Outlook Calendar"
            cog_load, soc_load, buffer_mins = 5, 5, 15
            prep_note = "15m transition buffer before/after event"

            t_lower = title.lower()
            if "the box" in t_lower or "client" in t_lower:
                cog_load, soc_load, buffer_mins = 8, 8, 20
                prep_note = "Clinical Therapy Session — protect 15m sensory decompression & clinical notes window after"
                target_label = "📓 Open Clinical Session & Calendar"
            elif "clinical director" in t_lower or "spire" in t_lower:
                cog_load, soc_load, buffer_mins = 8, 7, 20
                local_file = f"{drive_root}/Spire Therapy CIC Clinical Director role specification (DRAFT).gdoc"
                target_label = "📄 Open Clinical Director Spec (DRAFT).gdoc"
                prep_note = "Review Clinical Director role specification draft before board meeting"
            elif "msc" in t_lower or "uni" in t_lower:
                cog_load, soc_load, buffer_mins = 8, 4, 15
                local_file = f"{drive_root}/MSc Integrative Therapy: Distinctions Learning Guide.gdoc"
                target_label = "📘 Open MSc Distinctions Learning Guide.gdoc"
                prep_note = "Open MSc Action Plan & Distinctions Guide for 10m focus review"
            elif "swimming" in t_lower or "birthday" in t_lower or "halloween" in t_lower or "isla" in t_lower:
                cog_load, soc_load, buffer_mins = 4, 6, 20
                prep_note = "Family logistics — pack bag/outfit the evening before to avoid morning time-blindness rush"

            raw_events.append(
                {
                    "account_label": account_label,
                    "provider": provider,
                    "title": title,
                    "start_time": start_dt.strftime("%Y-%m-%d %H:%M"),
                    "end_time": end_dt.strftime("%Y-%m-%d %H:%M") if end_dt else "",
                    "horizon": horizon,
                    "cognitive_load": cog_load,
                    "social_load": soc_load,
                    "transition_buffer_mins": buffer_mins,
                    "prep_needed": prep_note,
                    "location": loc or ("Google Calendar" if provider == "google" else "Outlook Calendar"),
                    "target_url": "https://calendar.google.com" if provider == "google" else "https://outlook.office.com/calendar",
                    "local_file_path": local_file,
                    "target_label": target_label,
                }
            )

        # Filter out duplicate 'Private appointment' shadow blocks when a real named event exists at the same start_time
        named_timestamps = {
            e["start_time"] for e in raw_events if e["title"].strip().lower() != "private appointment"
        }
        filtered = [
            e
            for e in raw_events
            if not (e["title"].strip().lower() == "private appointment" and e["start_time"] in named_timestamps)
        ]
        return sorted(filtered, key=lambda x: x["start_time"])[:45]

    @staticmethod
    def _parse_ics_datetime(val: str) -> Optional[datetime]:
        val = val.rstrip("Z")
        for fmt in ("%Y%m%dT%H%M%S", "%Y%m%dT%H%M", "%Y%m%d"):
            try:
                return datetime.strptime(val, fmt)
            except ValueError:
                continue
        return None

    # -------------------------------------------------------------------------
    # 3. LIVE EMAIL INGESTION VIA IMAP & SMTP (GMAIL & OUTLOOK 365)
    # -------------------------------------------------------------------------
    def fetch_imap_unread_emails(
        self,
        email_address: str,
        app_password: str,
        provider: str,
        account_label: str,
        max_emails: int = 8,
    ) -> List[Dict[str, Any]]:
        """Connect to Gmail or Outlook via standard IMAP and triage recent unread emails with Claude/Gemini."""
        if not email_address or not app_password:
            return []
        imap_host = "imap.gmail.com" if provider == "google" else "outlook.office365.com"
        results: List[Dict[str, Any]] = []
        try:
            mail = imaplib.IMAP4_SSL(imap_host, 993)
            mail.login(email_address, app_password)
            mail.select("INBOX", readonly=True)
            status, messages = mail.search(None, "UNSEEN")
            msg_list = messages[0].split() if (status == "OK" and messages and messages[0]) else []
            if len(msg_list) < 3:
                status_all, all_messages = mail.search(None, "ALL")
                if status_all == "OK" and all_messages and all_messages[0]:
                    recent_all = all_messages[0].split()[-max_emails:]
                    for m in recent_all:
                        if m not in msg_list:
                            msg_list.append(m)

            msg_ids = msg_list[-max_emails:]
            for mid in reversed(msg_ids):
                res_code, msg_data = mail.fetch(mid, "(BODY.PEEK[])")
                if res_code != "OK" or not msg_data:
                    continue
                for part in msg_data:
                    if isinstance(part, tuple):
                        msg = email.message_from_bytes(part[1])
                        subject = self._decode_mime_words(msg.get("Subject", "(No Subject)"))
                        from_raw = self._decode_mime_words(msg.get("From", ""))
                        sender_name, sender_addr = email.utils.parseaddr(from_raw)
                        body_snippet = self._extract_text_snippet(msg)[:600]

                        triaged = self._ai_triage_single_email(
                            sender_name=sender_name or sender_addr,
                            sender_email=sender_addr,
                            subject=subject,
                            snippet=body_snippet,
                        )
                        results.append(
                            {
                                "account_label": account_label,
                                "provider": provider,
                                "sender_name": sender_name or sender_addr,
                                "sender_email": sender_addr,
                                "subject": subject,
                                "received_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                                "urgency": triaged.get("urgency", "action_required"),
                                "one_line_brief": triaged.get("one_line_brief", body_snippet[:140]),
                                "what_they_need": triaged.get("what_they_need", "Review and send pre-drafted reply"),
                                "draft_reply": triaged.get("draft_reply", f"Hi {sender_name or 'there'},\n\nThanks for your email regarding {subject}. I've noted this and will follow up shortly.\n\nBest,\nRob"),
                                "target_url": "https://mail.google.com/mail/u/0/#inbox" if provider == "google" else "https://outlook.office.com/mail/inbox",
                            }
                        )
            mail.logout()
        except Exception:
            return []
        return results

    def _ai_triage_single_email(
        self, sender_name: str, sender_email: str, subject: str, snippet: str
    ) -> Dict[str, str]:
        clean_snip = re.sub(r"https?://\S+", "", snippet)
        clean_snip = re.sub(r"\[image:[^\]]*\]", "", clean_snip)
        clean_snip = re.sub(r"\s+", " ", clean_snip).strip()

        prompt = (
            f"Triage this incoming email for Rob (AuDHD coach & founder).\n"
            f"From: {sender_name} <{sender_email}>\n"
            f"Subject: {subject}\n"
            f"Snippet: {clean_snip[:450]}\n\n"
            "Return ONLY a JSON object with keys:\n"
            "- urgency: 'action_required' (if a human or important admin needs a response/action) or 'quick_read' (if it is an automated alert, newsletter, survey, or FYI)\n"
            "- one_line_brief: 1 calm, clear sentence explaining what this email is about without raw URLs\n"
            "- what_they_need: 1 short phrase of what Rob needs to do (or 'No reply needed — safe to archive' for automated/newsletter emails)\n"
            "- draft_reply: a warm, ready-to-send reply in Rob's voice (or a brief note if he chooses to reply)"
        )
        res = self.ai.generate(prompt, prefer="gemini")
        if res["text"]:
            try:
                cleaned = res["text"].strip()
                if "```" in cleaned:
                    cleaned = cleaned.split("```")[1].replace("json", "").strip()
                parsed = json.loads(cleaned)
                if isinstance(parsed, dict) and "one_line_brief" in parsed:
                    return parsed
            except Exception:
                pass

        low_sub = subject.lower()
        low_from = f"{sender_name} {sender_email}".lower()
        if "security alert" in low_sub or "app password" in clean_snip.lower():
            return {
                "urgency": "quick_read",
                "one_line_brief": "Google security confirmation that your new App Password for robknightstrong@gmail.com was just created.",
                "what_they_need": "No reply needed — you just generated this App Password for Sanctuary! Safe to archive (+25 XP).",
                "draft_reply": "No reply needed (automated Google security confirmation).",
            }
        if any(w in low_sub or w in low_from or w in clean_snip.lower() for w in ["have your say", "survey", "newsletter", "noreply", "no-reply", "marketing", "chance to win", "substack", "view this email in your browser", "view this post on the web", "15% off", "unsubscribe"]):
            return {
                "urgency": "quick_read",
                "one_line_brief": f"Optional newsletter / update from {sender_name} ('{subject}').",
                "what_they_need": "Optional read or 1-click archive — no personal reply required (+25 XP).",
                "draft_reply": f"No reply needed (newsletter/promotional email from {sender_name}).",
            }
        return {
            "urgency": "action_required",
            "one_line_brief": f"{sender_name} wrote regarding '{subject}': {clean_snip[:160]}",
            "what_they_need": "Review message and send pre-drafted reply.",
            "draft_reply": f"Hi {sender_name.split()[0] if sender_name else 'there'},\n\nThanks so much for getting back to me regarding {subject}. I've reviewed your note and will follow up with the next steps shortly.\n\nWarm regards,\nRob",
        }

    @staticmethod
    def send_smtp_email(
        sender_email: str,
        app_password: str,
        provider: str,
        to_email: str,
        subject: str,
        body: str,
    ) -> Optional[Dict[str, Any]]:
        if not sender_email or not app_password:
            return None
        smtp_host = "smtp.gmail.com" if provider == "google" else "smtp.office365.com"
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = f"Re: {subject}" if not subject.lower().startswith("re:") else subject
        msg["From"] = sender_email
        msg["To"] = to_email
        try:
            with smtplib.SMTP(smtp_host, 587, timeout=15) as server:
                server.starttls()
                server.login(sender_email, app_password)
                server.sendmail(sender_email, [to_email], msg.as_string())
            return {"ok": True, "mode": "live_smtp_sent", "recipient": to_email}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @staticmethod
    def _decode_mime_words(s: str) -> str:
        if not s:
            return ""
        decoded_fragments = decode_header(s)
        out = []
        for frag, enc in decoded_fragments:
            if isinstance(frag, bytes):
                out.append(frag.decode(enc or "utf-8", errors="ignore"))
            else:
                out.append(str(frag))
        return "".join(out)

    @staticmethod
    def _extract_text_snippet(msg: Any) -> str:
        if msg.is_multipart():
            for part in msg.walk():
                ctype = part.get_content_type()
                cdisp = str(part.get("Content-Disposition"))
                if ctype == "text/plain" and "attachment" not in cdisp:
                    payload = part.get_payload(decode=True)
                    if payload:
                        return payload.decode("utf-8", errors="ignore").strip()
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                return payload.decode("utf-8", errors="ignore").strip()
        return ""

    # -------------------------------------------------------------------------
    # 4. MASTER SYNC ACROSS ALL CONFIGURED LIVE ACCOUNTS
    # -------------------------------------------------------------------------
    def sync_all_live_accounts(self, clear_demo_data: bool = False) -> Dict[str, Any]:
        """Run live ingestion across all accounts that have Notion tokens, iCal URLs, or IMAP credentials."""
        with self.db.connect() as conn:
            if clear_demo_data:
                conn.execute("DELETE FROM calendar_events")
                conn.execute("DELETE FROM proactive_suggestions")
                conn.execute("DELETE FROM triaged_emails WHERE status = 'pending'")

            accounts = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM connected_accounts WHERE is_active = 1"
                ).fetchall()
            ]

        events_added = 0
        emails_added = 0
        notion_suggestions_added = 0
        synced_notion_tokens = set()
        notion_debug = ""
        now_iso = datetime.now().isoformat()

        if not any(a["provider"] == "notion" for a in accounts):
            notion_debug = (
                "No active Notion account found under Connected Accounts (⚙️ menu) — "
                "the Notion sync step was skipped entirely."
            )

        for acc in accounts:
            creds = json.loads(acc.get("credentials_json") or "{}")
            provider = acc["provider"]
            label = acc["account_label"]
            ident = acc["account_identifier"]

            # A. Notion live workspace sync (Full Environment)
            if provider == "notion":
                token = (
                    creds.get("access_token")
                    or creds.get("api_token")
                    or Config.NOTION_API_KEY
                )
                if not token:
                    notion_debug = "No Notion API key is configured for this account or via NOTION_API_KEY."
                    continue
                if token in synced_notion_tokens:
                    continue
                synced_notion_tokens.add(token)
                notion_items = self.fetch_notion_workspace_items(token, label)
                if self.last_notion_error:
                    notion_debug = self.last_notion_error
                elif not notion_items:
                    notion_debug = (
                        "Notion returned shared pages, but every one was already marked Done "
                        "or had no readable title — none were usable tasks."
                    )
                with self.db.connect() as conn:
                    existing_urls = {
                        r["target_url"]
                        for r in conn.execute("SELECT target_url FROM proactive_suggestions WHERE target_url != ''").fetchall()
                    }
                    cleared_urls = {
                        r["target_url"]
                        for r in conn.execute("SELECT target_url FROM cleared_vault WHERE target_url != ''").fetchall()
                    }
                    has_active_boss = (
                        conn.execute("SELECT COUNT(*) AS c FROM proactive_suggestions WHERE is_cleared = 0 AND is_daily_boss = 1").fetchone()["c"]
                        > 0
                    )
                    for idx, item in enumerate(notion_items):
                        item_url = item.get("url", "")
                        if item_url in existing_urls or item_url in cleared_urls:
                            continue
                        existing_urls.add(item_url)
                        horizon = item.get("horizon") or ("1d" if idx < 4 else ("2d" if idx < 10 else ("1w" if idx < 22 else "1m")))
                        due_ctx = item.get("due_date") or item.get("status_label") or "Live Notion Environment"

                        type_label = item.get("type_label", "")
                        category_label = item.get("category_label", "")
                        priority_label = item.get("priority_label", "")
                        is_hard_deadline = type_label == "Hard Deadline"

                        tag_bits = [
                            b for b in (category_label, type_label, f"Priority: {priority_label}" if priority_label else "")
                            if b
                        ]
                        display_title = (
                            f"{'⏰ ' if is_hard_deadline else ''}[{' • '.join(tag_bits)}] {item['title']}"
                            if tag_bits
                            else f"Notion: {item['title']}"
                        )

                        is_boss = 1 if (not has_active_boss and idx == 0 and notion_suggestions_added == 0) else 0
                        if is_boss:
                            has_active_boss = True
                        xp = 75 if is_boss else (50 if is_hard_deadline else 30)
                        conn.execute(
                            """
                            INSERT INTO proactive_suggestions (
                                horizon, title, why_it_matters, starter_micro_step, micro_steps_json,
                                source_label, energy_required, is_daily_boss, xp_reward, due_context,
                                target_url, local_file_path, target_label, inline_action_type,
                                inline_action_label, is_cleared, created_at
                            ) VALUES (?, ?, ?, ?, ?, ?, 'steady', ?, ?, ?, ?, '', ?, 'open_url', ?, 0, ?)
                            """,
                            (
                                horizon,
                                display_title,
                                f"Live item from {label} ({due_ctx} • Last edited {item['last_edited'][:10]}).",
                                f"Click '🚀 Open in Notion & Auto-Complete' to jump straight to '{item['title']}' in Notion and claim +{xp} XP.",
                                json.dumps(["Open directly in Notion", "Complete 1 micro-step or update status"]),
                                label,
                                is_boss,
                                xp,
                                due_ctx,
                                item_url,
                                f"📓 Open '{item['title'][:34]}' in Notion",
                                f"🚀 Open in Notion & Auto-Complete (+{xp} XP)",
                                now_iso,
                            ),
                        )
                        notion_suggestions_added += 1

                    if notion_items and notion_suggestions_added == 0 and not notion_debug:
                        notion_debug = (
                            f"Notion returned {len(notion_items)} item(s), but all were already "
                            "synced in a previous run — nothing new to add."
                        )

            # B. Calendar live iCal (.ics) sync
            ics_url = creds.get("ics_url") or ""
            if ics_url:
                cal_events = self.fetch_ical_events(ics_url, label, provider)
                with self.db.connect() as conn:
                    existing_ev = {
                        (r["title"], r["start_time"])
                        for r in conn.execute("SELECT title, start_time FROM calendar_events").fetchall()
                    }
                    existing_titles = {
                        r["title"]
                        for r in conn.execute("SELECT title FROM proactive_suggestions").fetchall()
                    }
                    for ev in cal_events:
                        key = (ev["title"], ev["start_time"])
                        if key in existing_ev:
                            continue
                        existing_ev.add(key)
                        conn.execute(
                            """
                            INSERT INTO calendar_events (
                                account_id, account_label, provider, title, start_time, end_time,
                                horizon, cognitive_load, social_load, transition_buffer_mins,
                                prep_needed, location, target_url, local_file_path, target_label
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                acc["id"],
                                label,
                                provider,
                                ev["title"],
                                ev["start_time"],
                                ev["end_time"],
                                ev["horizon"],
                                ev.get("cognitive_load", 6),
                                ev.get("social_load", 6),
                                ev.get("transition_buffer_mins", 15),
                                ev.get("prep_needed", "15m transition buffer"),
                                ev["location"],
                                ev["target_url"],
                                ev.get("local_file_path", ""),
                                ev.get("target_label", "📅 Open Calendar Event"),
                            ),
                        )
                        events_added += 1

                        # Generate high-value proactive prep cards for key real calendar events
                        t_low = ev["title"].lower()
                        prep_title = ""
                        if "clinical director" in t_low:
                            prep_title = f"Prep for '{ev['title']}' ({ev['start_time']})"
                            why = "Live Board Meeting spotted on your Google Calendar—review the Clinical Director role specification draft ahead of time."
                            starter = "Click below to open Spire Therapy CIC Clinical Director role specification (DRAFT).gdoc on your Mac."
                        elif "msc" in t_low and "action plan" in t_low:
                            prep_title = f"Prep for '{ev['title']}' ({ev['start_time']})"
                            why = "Scheduled on your calendar tomorrow afternoon—doing a 2-minute bullet check now removes any friction."
                            starter = "Click to open your MSc Distinctions Learning Guide / Action Plan."
                        elif "halloween dress up" in t_low or "birthday party" in t_low:
                            prep_title = f"Family Prep Radar: {ev['title']} ({ev['start_time'][:10]})"
                            why = "Spotted on The Knight-Strongs Family Calendar—prepping outfit/card ahead of time prevents a last-minute rush!"
                            starter = "Open family calendar event and confirm outfit/gift is ready."

                        if prep_title and prep_title not in existing_titles:
                            existing_titles.add(prep_title)
                            conn.execute(
                                """
                                INSERT INTO proactive_suggestions (
                                    horizon, title, why_it_matters, starter_micro_step, micro_steps_json,
                                    source_label, energy_required, is_daily_boss, xp_reward, due_context,
                                    target_url, local_file_path, target_label, inline_action_type,
                                    inline_action_label, is_cleared, created_at
                                ) VALUES (?, ?, ?, ?, ?, ?, 'low', 0, 35, ?, ?, ?, ?, 'open_file', ?, 0, ?)
                                """,
                                (
                                    ev["horizon"],
                                    prep_title,
                                    why,
                                    starter,
                                    json.dumps(["Open linked document or calendar event", "Check 2 key details"]),
                                    label,
                                    ev["start_time"],
                                    ev["target_url"],
                                    ev.get("local_file_path", ""),
                                    ev.get("target_label", "📅 Open Calendar Event"),
                                    "🚀 Open Target & Auto-Complete (+35 XP)",
                                    now_iso,
                                ),
                            )

            # C. Live IMAP Inbox Triage
            app_password = (creds.get("app_password") or "").replace(" ", "").strip()
            if app_password and "@" in ident:
                live_emails = self.fetch_imap_unread_emails(
                    email_address=ident,
                    app_password=app_password,
                    provider=provider,
                    account_label=label,
                )
                with self.db.connect() as conn:
                    existing_em = {
                        (r["sender_email"], r["subject"])
                        for r in conn.execute("SELECT sender_email, subject FROM triaged_emails WHERE status = 'pending'").fetchall()
                    }
                    for em in live_emails:
                        em_key = (em["sender_email"], em["subject"])
                        if em_key in existing_em:
                            continue
                        existing_em.add(em_key)
                        conn.execute(
                            """
                            INSERT INTO triaged_emails (
                                account_id, account_label, provider, sender_name, sender_email,
                                subject, received_at, urgency, one_line_brief, what_they_need,
                                draft_reply, draft_tone, energy_required, xp_reward, status,
                                target_url, local_file_path, attachment_label
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'warm_balanced', 'low', 25, 'pending', ?, '', '')
                            """,
                            (
                                acc["id"],
                                label,
                                provider,
                                em["sender_name"],
                                em["sender_email"],
                                em["subject"],
                                em["received_at"],
                                em["urgency"],
                                em["one_line_brief"],
                                em["what_they_need"],
                                em["draft_reply"],
                                em["target_url"],
                            ),
                        )
                        emails_added += 1

        return {
            "ok": True,
            "events_synced": events_added,
            "emails_triaged": emails_added,
            "notion_items_synced": notion_suggestions_added,
            "notion_debug": notion_debug,
            "cleared_demo": clear_demo_data,
        }
