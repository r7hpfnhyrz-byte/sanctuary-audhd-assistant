"""Email Triage & Proactive Draft Studio Engine across multiple Gmail and Outlook accounts."""

import json
from datetime import datetime
from typing import Any, Dict, List

from backend.ai.router import DualAIRouter
from backend.connectors.google_connector import GoogleWorkspaceConnector
from backend.connectors.microsoft_connector import MicrosoftGraphConnector
from backend.database import Database
from backend.engine.gamification import GamificationEngine


class EmailTriageEngine:
    """Triages multi-inbox emails, shifts draft tones, sends replies, and logs cleared items to the Vault."""

    def __init__(self, db: Database, ai: DualAIRouter, game: GamificationEngine) -> None:
        self.db = db
        self.ai = ai
        self.game = game

    def list_pending_emails(self) -> List[Dict[str, Any]]:
        progress = self.game.get_state()
        energy_mode = progress.get("energy_mode", "steady")

        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM triaged_emails
                WHERE status = 'pending'
                ORDER BY CASE urgency WHEN 'action_required' THEN 1 ELSE 2 END, id ASC
                """
            ).fetchall()
            # Real sending needs an OAuth access token; app-password (IMAP) accounts can only read
            sendable_accounts = {
                r["id"]
                for r in conn.execute("SELECT id, credentials_json FROM connected_accounts").fetchall()
                if json.loads(r["credentials_json"] or "{}").get("access_token")
            }

        emails = [dict(r) for r in rows]
        for e in emails:
            e["can_send"] = (e.get("account_id") or 1) in sendable_accounts
        if energy_mode == "low_spoons":
            action_only = [e for e in emails if e["urgency"] == "action_required"]
            return action_only[:2] if action_only else emails[:1]
        return emails

    def update_draft(self, email_id: int, new_draft: str) -> Dict[str, Any]:
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE triaged_emails SET draft_reply = ? WHERE id = ?",
                (new_draft, email_id),
            )
        return {"ok": True, "email_id": email_id, "draft_reply": new_draft}

    def shift_tone(self, email_id: int, target_tone: str) -> Dict[str, Any]:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM triaged_emails WHERE id = ?", (email_id,)
            ).fetchone()
            if not row:
                return {"ok": False, "error": "Email not found"}

            rewritten = self.ai.shift_email_tone(
                current_draft=row["draft_reply"],
                target_tone=target_tone,
                sender_name=row["sender_name"],
                subject=row["subject"],
            )
            conn.execute(
                "UPDATE triaged_emails SET draft_reply = ?, draft_tone = ? WHERE id = ?",
                (rewritten, target_tone, email_id),
            )
        return {
            "ok": True,
            "email_id": email_id,
            "draft_tone": target_tone,
            "draft_reply": rewritten,
        }

    def approve_and_send(
        self, email_id: int, edited_body: str, action: str = "send"
    ) -> Dict[str, Any]:
        """Send or save draft via the matching Google or Microsoft account, award XP, and move to Accomplishment Vault."""
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM triaged_emails WHERE id = ?", (email_id,)
            ).fetchone()
            if not row:
                return {"ok": False, "error": "Email not found"}
            email = dict(row)

            acc_row = conn.execute(
                "SELECT * FROM connected_accounts WHERE id = ?",
                (email.get("account_id") or 1,),
            ).fetchone()
            creds = json.loads(acc_row["credentials_json"]) if acc_row else {}

            body_to_send = edited_body.strip() or email["draft_reply"]
            send_now = action == "send"

            if send_now and not creds.get("access_token"):
                # Without OAuth the connectors only simulate a send. Never mark an email "sent" that wasn't.
                return {
                    "ok": False,
                    "error": "Sending isn't set up for this account. Copy the reply and send it from your email app.",
                }

            if email["provider"] == "google":
                dispatch_result = GoogleWorkspaceConnector.send_or_draft_gmail(
                    creds,
                    to_email=email["sender_email"],
                    subject=email["subject"],
                    body=body_to_send,
                    send_immediately=send_now,
                )
            else:
                dispatch_result = MicrosoftGraphConnector.send_or_draft_outlook(
                    creds,
                    to_email=email["sender_email"],
                    subject=email["subject"],
                    body=body_to_send,
                    send_immediately=send_now,
                )

            conn.execute(
                "UPDATE triaged_emails SET status = ?, draft_reply = ? WHERE id = ?",
                ("sent" if send_now else "archived", body_to_send, email_id),
            )

            xp = int(email.get("xp_reward", 25))
            action_verb = "Sent reply to" if send_now else "Cleared & archived email from"
            conn.execute(
                """
                INSERT INTO cleared_vault (
                    item_type, title, summary, account_label, horizon_tag,
                    xp_earned, was_boss, synced_to_notion, target_url,
                    local_file_path, target_label, cleared_at
                ) VALUES ('email_sent', ?, ?, ?, '1d', ?, 0, 1, ?, ?, ?, ?)
                """,
                (
                    f"{action_verb} {email['sender_name']}: {email['subject']}",
                    email["one_line_brief"],
                    email["account_label"],
                    xp,
                    email.get("target_url", ""),
                    email.get("local_file_path", ""),
                    email.get("attachment_label", "Open Email Thread"),
                    datetime.now().isoformat(),
                ),
            )

        progress = self.game.award_xp(
            amount=xp,
            reason=f"✉️ {action_verb} {email['sender_name']}",
        )
        return {
            "ok": True,
            "dispatch": dispatch_result,
            "email_id": email_id,
            "progress": progress,
        }

    def triage_custom_email(
        self,
        raw_email_text: str,
        sender_name: str = "Work Colleague / Outlook",
        subject: str = "Work Email Triage",
        account_label: str = "Employer Outlook (IT-Safe Paste/Forward)",
    ) -> Dict[str, Any]:
        """Triage a pasted or forwarded email from an employer-locked inbox and generate an editable reply."""
        prompt = (
            f"Triage this email for Rob (AuDHD coach & leader).\n"
            f"Sender: {sender_name}\n"
            f"Subject: {subject}\n"
            f"Email Content:\n{raw_email_text}\n\n"
            "Return ONLY a JSON object with keys:\n"
            "- urgency: 'action_required' or 'quick_read'\n"
            "- one_line_brief: 1 calm sentence explaining what this email is really asking\n"
            "- what_they_need: 1 short phrase of what Rob needs to decide/reply\n"
            "- draft_reply: a clear, warm, ready-to-send reply in Rob's voice"
        )
        res = self.ai.generate(prompt, prefer="claude")
        parsed = {}
        if res["text"]:
            try:
                cleaned = res["text"].strip()
                if "```" in cleaned:
                    cleaned = cleaned.split("```")[1].replace("json", "").strip()
                parsed = json.loads(cleaned)
            except Exception:
                parsed = {}

        brief = parsed.get(
            "one_line_brief",
            f"Summary: {raw_email_text.strip()[:140]}...",
        )
        need = parsed.get(
            "what_they_need",
            "Review the key point and send the drafted response below.",
        )
        draft = parsed.get(
            "draft_reply",
            f"Hi {sender_name.split()[0] if sender_name else 'there'},\n\nThanks for sending this over. I've reviewed the details regarding {subject} and am happy to confirm from my side.\n\nBest regards,\nRob",
        )
        urgency = parsed.get("urgency", "action_required")
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

        with self.db.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO triaged_emails (
                    account_id, account_label, provider, sender_name, sender_email,
                    subject, received_at, urgency, one_line_brief, what_they_need,
                    draft_reply, draft_tone, energy_required, xp_reward, status,
                    target_url, local_file_path, attachment_label
                ) VALUES (3, ?, 'microsoft', ?, '', ?, ?, ?, ?, ?, ?, 'warm_balanced', 'low', 25, 'pending', 'https://outlook.office.com/mail/', '', '📋 Copy Reply to Clipboard')
                """,
                (account_label, sender_name, subject, now_str, urgency, brief, need, draft),
            )
            new_id = cur.lastrowid

        return {"ok": True, "email_id": new_id}

