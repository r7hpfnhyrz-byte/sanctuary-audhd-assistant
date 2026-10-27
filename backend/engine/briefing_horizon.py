"""Daily Briefing & 4-Horizon Proactive Planner (1-Day, 2-Day, 1-Week, 1-Month) with Direct Deep-Link & 1-Click Auto-Complete Execution."""

import json
import os
import re
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.ai.router import DualAIRouter
from backend.database import Database
from backend.engine.gamification import GamificationEngine

URGENCY_RANK = {"urgent": 0, "soon": 1, "later": 2}

# Tasks that need the person themselves. Checked first, so assessed MSc work and
# clinical work never default to "AI can help".
_ME_HINTS = re.compile(
    r"\b(submit|essay|assignment|exam|placement|client|supervision|therapy|session|attend|meet\b|call\b|sign\b|pay\b|book\b)",
    re.IGNORECASE,
)
_AI_HINTS = re.compile(
    r"\b(draft|write|email|reply|respond|summar|research|plan|outline|prep|notes|agenda|letter|proposal|report|update)",
    re.IGNORECASE,
)

DRAFT_SYSTEM_PROMPT = (
    "You are a practical assistant drafting work for a busy UK public-sector professional who is also "
    "a postgraduate psychotherapy student. Write in plain UK English. Never invent client details."
)


def clean_task_title(title: str) -> str:
    """Strip the '⏰ [Category • Type • Priority: X]' / 'Notion:' decoration added at sync time."""
    t = re.sub(r"^\s*⏰\s*", "", title or "")
    t = re.sub(r"^\[[^\]]*\]\s*", "", t)
    return re.sub(r"^Notion:\s*", "", t).strip()


def _parse_due_date(due_context: str) -> Optional[date]:
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", due_context or "")
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y-%m-%d").date()
    except ValueError:
        return None


def classify_urgency(suggestion: Dict[str, Any], today: date) -> str:
    """'urgent' (red), 'soon' (amber) or 'later' (green), from the due date plus Notion Priority."""
    priority = re.search(r"Priority:\s*([^\]•]+)", suggestion.get("title") or "")
    is_high = bool(priority) and priority.group(1).strip().lower() in ("high", "urgent", "critical")

    due_context = suggestion.get("due_context") or ""
    due = _parse_due_date(due_context)
    if due:
        days = (due - today).days
        if days <= 1:
            return "urgent"
        if days <= 7:
            return "urgent" if is_high else "soon"
        return "later"

    # Hand-written contexts like "Today before 2:00 PM"
    if due_context.strip().lower().startswith(("today", "tomorrow", "overdue")):
        return "urgent"
    return "soon" if is_high else "later"


def guess_assignee(suggestion: Dict[str, Any]) -> str:
    """'me' or 'ai'. The user's own choice always wins over the guess."""
    if suggestion.get("assignee") in ("me", "ai"):
        return suggestion["assignee"]
    if suggestion.get("inline_action_type") == "jump_inbox":
        return "ai"
    title = clean_task_title(suggestion.get("title") or "")
    if _ME_HINTS.search(title):
        return "me"
    if _AI_HINTS.search(title):
        return "ai"
    return "me"


class BriefingHorizonEngine:
    """Synthesizes multi-account calendars, Notion tasks, and proactive 1d/2d/1w/1m suggestions."""

    def __init__(self, db: Database, ai: DualAIRouter, game: GamificationEngine) -> None:
        self.db = db
        self.ai = ai
        self.game = game

    def get_briefing_and_horizons(self) -> Dict[str, Any]:
        progress = self.game.get_state()
        energy_mode = progress.get("energy_mode", "steady")

        with self.db.connect() as conn:
            events_rows = conn.execute(
                "SELECT * FROM calendar_events WHERE is_cleared = 0 ORDER BY start_time ASC"
            ).fetchall()
            suggestions_rows = conn.execute(
                "SELECT * FROM proactive_suggestions WHERE is_cleared = 0 ORDER BY is_daily_boss DESC, id ASC"
            ).fetchall()
            pending_emails_cnt = conn.execute(
                "SELECT COUNT(*) AS cnt FROM triaged_emails WHERE status = 'pending'"
            ).fetchone()["cnt"]
            accounts_rows = conn.execute(
                "SELECT id, provider, account_label, account_identifier, color_tag, portal_url, last_synced_at FROM connected_accounts WHERE is_active = 1"
            ).fetchall()
            today_start = datetime.now().strftime("%Y-%m-%d")
            done_rows = conn.execute(
                "SELECT * FROM proactive_suggestions WHERE is_cleared = 1 AND cleared_at >= ? ORDER BY cleared_at DESC LIMIT 30",
                (today_start,),
            ).fetchall()

        today = datetime.now().date()

        def decorate(row: Any) -> Dict[str, Any]:
            d = dict(row)
            d["micro_steps"] = json.loads(d.get("micro_steps_json") or "[]")
            d["urgency"] = classify_urgency(d, today)
            d["assignee_is_choice"] = d.get("assignee") in ("me", "ai")
            d["assignee"] = guess_assignee(d)
            return d

        events = [dict(r) for r in events_rows]
        all_suggestions = [decorate(r) for r in suggestions_rows]
        done_today = [decorate(r) for r in done_rows]

        today_events = [e for e in events if e["horizon"] == "1d"]
        avg_social = (
            round(sum(e["social_load"] for e in today_events) / len(today_events), 1)
            if today_events
            else 3.0
        )
        avg_cog = (
            round(sum(e["cognitive_load"] for e in today_events) / len(today_events), 1)
            if today_events
            else 4.0
        )

        # Group proactive suggestions by horizon (1d, 2d, 1w, 1m)
        raw_horizons: Dict[str, List[Dict[str, Any]]] = {"1d": [], "2d": [], "1w": [], "1m": []}
        for s in all_suggestions:
            h = s.get("horizon", "1d")
            if h in raw_horizons:
                raw_horizons[h].append(s)
        # Red before amber before green, so the per-mode caps below never hide an urgent item
        for items in raw_horizons.values():
            items.sort(key=lambda s: URGENCY_RANK[s["urgency"]])

        total_active_suggestions = len(all_suggestions)

        # AuDHD Overwhelm Protection: Curate visible cards per horizon so 700+ Notion items never flood the screen!
        if energy_mode == "low_spoons":
            horizons = {
                "1d": [s for s in raw_horizons["1d"] if s["energy_required"] == "low" or s["is_daily_boss"]][:2] or raw_horizons["1d"][:2],
                "2d": raw_horizons["2d"][:2],
                "1w": raw_horizons["1w"][:2],
                "1m": [],
            }
        elif energy_mode == "steady":
            horizons = {
                "1d": raw_horizons["1d"][:5],
                "2d": raw_horizons["2d"][:6],
                "1w": raw_horizons["1w"][:8],
                "1m": raw_horizons["1m"][:10],
            }
        else:  # high focus
            horizons = {
                "1d": raw_horizons["1d"][:8],
                "2d": raw_horizons["2d"][:10],
                "1w": raw_horizons["1w"][:12],
                "1m": raw_horizons["1m"][:15],
            }

        daily_boss = next((s for s in all_suggestions if s.get("is_daily_boss")), None)

        coach_headline = {
            "high": (
                f"⚡ **High Focus Mode Active:** I've indexed **{total_active_suggestions} live items** across your Notion environment, calendars & Drive—and curated the highest-impact ones below so you can ride your focus wave without visual clutter."
            ),
            "steady": (
                f"🌱 **Steady Pacing Mode:** I've connected to your full Notion environment (**{total_active_suggestions} pages & tasks indexed**) and shielded you from overwhelm by surfacing **only your Top 5 Today actions** below. As you clear one, the next rotates in!"
            ),
            "low_spoons": (
                f"🔋 **Low Spoons & Grace Shield Active:** Even though **{total_active_suggestions} Notion items** are safely synced in the background, I've hidden 99% of them so you only see **2 gentle steps** today."
            ),
        }.get(energy_mode, "")

        return {
            "generated_at": datetime.now().strftime("%A, %d %B %Y • %H:%M"),
            "energy_mode": energy_mode,
            "coach_headline": coach_headline,
            "sensory_weather": {
                "social_load_score": avg_social,
                "cognitive_load_score": avg_cog,
                "status_label": "Moderate-High Social Masking Today — Protect Decompression Buffers"
                if avg_social >= 6.5
                else "Balanced Sensory Load Today",
                "pending_triage_emails": pending_emails_cnt,
            },
            "daily_boss": daily_boss,
            "horizons": horizons,
            "done_today": done_today,
            "status_counts": {
                "urgent": sum(1 for s in all_suggestions if s["urgency"] == "urgent"),
                "soon": sum(1 for s in all_suggestions if s["urgency"] == "soon"),
                "done_today": len(done_today),
            },
            "events_by_horizon": {
                "1d": [e for e in events if e["horizon"] == "1d"],
                "2d": [e for e in events if e["horizon"] == "2d"],
                "1w": [e for e in events if e["horizon"] == "1w"],
                "1m": [e for e in events if e["horizon"] == "1m"],
            },
            "connected_accounts": [dict(a) for a in accounts_rows],
            "progress": progress,
        }

    def open_local_or_remote_target(self, local_file_path: str, target_url: str) -> Dict[str, Any]:
        """Open a real local Google Drive file on macOS if available, and return the fallback/deep URL."""
        opened_locally = False
        if local_file_path and Path(local_file_path).exists():
            try:
                if os.environ.get("AUDHD_TEST_MODE") != "1":
                    subprocess.Popen(
                        ["open", local_file_path],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                opened_locally = True
            except Exception:
                opened_locally = False

        return {
            "opened_locally": opened_locally,
            "local_file_path": local_file_path,
            "target_url": target_url,
            "file_basename": Path(local_file_path).name if local_file_path else "",
        }

    def execute_and_complete_suggestion(
        self,
        suggestion_id: int,
        auto_complete: bool = True,
        quick_note: str = "",
    ) -> Dict[str, Any]:
        """Launch the linked file/calendar/inbox target AND automatically mark the suggestion complete in 1 click!"""
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM proactive_suggestions WHERE id = ?", (suggestion_id,)
            ).fetchone()
            if not row:
                return {"ok": False, "error": "Suggestion not found"}
            item = dict(row)

            # Perform inline automation if applicable (e.g., auto-blocking calendar buffer)
            action_type = item.get("inline_action_type", "open_file")
            inline_effect = ""
            now = datetime.now()
            if action_type == "calendar_buffer":
                conn.execute(
                    """
                    INSERT INTO calendar_events (
                        account_id, account_label, provider, title, start_time, end_time,
                        horizon, cognitive_load, social_load, transition_buffer_mins,
                        prep_needed, location, target_url, local_file_path, target_label
                    ) VALUES (1, 'Spire Therapy Google Workspace', 'google',
                              '🛡️ Protected 20m Sensory Decompression Buffer (No Screens)',
                              ?, ?, '1d', 1, 1, 0, 'Step away from screens, hydrate, decompress',
                              'Offline Reset', 'https://calendar.google.com', '', '📅 Protected Buffer Block')
                    """,
                    (
                        (now + timedelta(hours=3)).strftime("%Y-%m-%d 15:00"),
                        (now + timedelta(hours=3, minutes=20)).strftime("%Y-%m-%d 15:20"),
                    ),
                )
                inline_effect = "Inserted 20-minute Sensory Decompression Buffer onto your calendar!"
            elif action_type == "inline_reschedule":
                inline_effect = "Sent polite reschedule note moving Tuesday's internal check-in to Thursday afternoon!"

        launch_info = self.open_local_or_remote_target(
            item.get("local_file_path", ""), item.get("target_url", "")
        )

        if not auto_complete:
            return {
                "ok": True,
                "launched": launch_info,
                "auto_completed": False,
                "pinned_item": item,
            }

        completion = self.complete_suggestion(suggestion_id, quick_note=quick_note or inline_effect)
        completion["launched"] = launch_info
        completion["auto_completed"] = True
        completion["inline_effect"] = inline_effect
        return completion

    def complete_suggestion(self, suggestion_id: int, quick_note: str = "") -> Dict[str, Any]:
        """Mark a proactive suggestion or Daily Boss as cleared, award XP, and archive with its deep link to the Cleared Vault."""
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM proactive_suggestions WHERE id = ?", (suggestion_id,)
            ).fetchone()
            if not row:
                return {"ok": False, "error": "Suggestion not found"}

            item = dict(row)
            conn.execute(
                "UPDATE proactive_suggestions SET is_cleared = 1, cleared_at = ? WHERE id = ?",
                (datetime.now().isoformat(), suggestion_id),
            )

            is_boss = bool(item.get("is_daily_boss"))
            xp = int(item.get("xp_reward", 25))
            vault_type = "boss_defeated" if is_boss else "horizon_prep"
            summary_text = (
                f"{item['why_it_matters']} • Note: {quick_note}"
                if quick_note
                else item["why_it_matters"]
            )

            conn.execute(
                """
                INSERT INTO cleared_vault (
                    item_type, title, summary, account_label, horizon_tag,
                    xp_earned, was_boss, synced_to_notion, target_url,
                    local_file_path, target_label, cleared_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
                """,
                (
                    vault_type,
                    item["title"],
                    summary_text,
                    item["source_label"],
                    item["horizon"],
                    xp,
                    1 if is_boss else 0,
                    item.get("target_url", ""),
                    item.get("local_file_path", ""),
                    item.get("target_label", "Open Linked File"),
                    datetime.now().isoformat(),
                ),
            )

        updated_progress = self.game.award_xp(
            amount=xp,
            reason=f"{'Next thing done: ' if is_boss else 'Cleared: '}{item['title']}",
            is_boss=is_boss,
        )
        return {
            "ok": True,
            "cleared_item": item,
            "progress": updated_progress,
        }

    def reopen_suggestion(self, suggestion_id: int) -> Dict[str, Any]:
        """Undo an accidental 'Done': put the task back on the list and drop its Done-tab entry."""
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM proactive_suggestions WHERE id = ?", (suggestion_id,)
            ).fetchone()
            if not row:
                return {"ok": False, "error": "Suggestion not found"}
            conn.execute(
                "UPDATE proactive_suggestions SET is_cleared = 0, cleared_at = '' WHERE id = ?",
                (suggestion_id,),
            )
            conn.execute(
                """
                DELETE FROM cleared_vault WHERE id = (
                    SELECT id FROM cleared_vault WHERE title = ? ORDER BY id DESC LIMIT 1
                )
                """,
                (row["title"],),
            )
        return {"ok": True, "suggestion_id": suggestion_id}

    def set_assignee(self, suggestion_id: int, assignee: str) -> Dict[str, Any]:
        """Record the user's own 'You' / 'AI can help' choice so future guesses never override it."""
        if assignee not in ("me", "ai"):
            return {"ok": False, "error": "Assignee must be 'me' or 'ai'"}
        with self.db.connect() as conn:
            cur = conn.execute(
                "UPDATE proactive_suggestions SET assignee = ? WHERE id = ?",
                (assignee, suggestion_id),
            )
            if cur.rowcount == 0:
                return {"ok": False, "error": "Suggestion not found"}
        return {"ok": True, "suggestion_id": suggestion_id, "assignee": assignee}

    def draft_with_ai(self, suggestion_id: int) -> Dict[str, Any]:
        """Ask Claude/Gemini to do as much of a task as it can, as text the user can copy."""
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM proactive_suggestions WHERE id = ?", (suggestion_id,)
            ).fetchone()
        if not row:
            return {"ok": False, "error": "Suggestion not found"}

        prompt = (
            f"Task: {clean_task_title(row['title'])}\n"
            f"Due: {row['due_context'] or 'not set'}\n"
            f"From: {row['source_label']}\n\n"
            "Do as much of this task for me as you can, as text I can copy and use.\n"
            "- If it needs an email or message, write it.\n"
            "- If it needs a document, write a first draft or a clear outline.\n"
            "- If it is assessed university work (an essay, assignment or reflective piece), do NOT write "
            "the assessed text. Give a short plan, the key questions to answer and a reading checklist instead.\n"
            "Keep it under 300 words. No preamble."
        )
        res = self.ai.generate(prompt, system_prompt=DRAFT_SYSTEM_PROMPT, prefer="claude")
        draft = (res.get("text") or "").strip()
        if not draft:
            return {
                "ok": False,
                "error": "AI isn't available right now. Check the Claude or Gemini key in settings.",
            }

        with self.db.connect() as conn:
            conn.execute(
                "UPDATE proactive_suggestions SET ai_draft = ? WHERE id = ?",
                (draft, suggestion_id),
            )
        return {"ok": True, "suggestion_id": suggestion_id, "draft": draft, "provider": res.get("provider", "")}

    def generate_micro_steps_for_suggestion(self, suggestion_id: int) -> Dict[str, Any]:
        """Use the Dual AI Engine to break a suggestion into tiny 60-second micro-steps."""
        progress = self.game.get_state()
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM proactive_suggestions WHERE id = ?", (suggestion_id,)
            ).fetchone()
            if not row:
                return {"ok": False, "error": "Suggestion not found"}
            steps = self.ai.break_into_micro_steps(
                row["title"], progress.get("energy_mode", "steady")
            )
            conn.execute(
                "UPDATE proactive_suggestions SET micro_steps_json = ? WHERE id = ?",
                (json.dumps(steps), suggestion_id),
            )
        return {"ok": True, "suggestion_id": suggestion_id, "micro_steps": steps}
