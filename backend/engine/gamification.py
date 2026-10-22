"""Shame-free AuDHD Gamification Engine: XP, Momentum Rings, Grace Shields, Daily Boss Battles, and Quick-Win Roulette."""

import json
import random
from datetime import datetime
from typing import Any, Dict, List

from backend.database import Database

LEVEL_TITLES = {
    1: "Spark Seeker",
    2: "Momentum Builder",
    3: "Cognitive Navigator",
    4: "Dopamine Alchemist",
    5: "Executive Architect",
    6: "Horizon Strategist",
    7: "Neuro-Flow Master",
    8: "Grand Systems Wizard",
}


class GamificationEngine:
    """Manages dopamine-friendly rewards without punitive streak-shaming."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def get_state(self) -> Dict[str, Any]:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM user_progress WHERE id = 1").fetchone()
            if not row:
                return {}
            data = dict(row)
            xp = data["xp"]
            level = max(1, (xp // 100) + 1)
            xp_in_level = xp % 100
            data["level"] = level
            data["level_title"] = LEVEL_TITLES.get(level, f"Level {level} Trailblazer")
            data["xp_in_current_level"] = xp_in_level
            data["xp_to_next_level"] = 100 - xp_in_level
            data["badges"] = json.loads(data.get("badges_json") or "[]")
            return data

    def award_xp(
        self,
        amount: int,
        reason: str,
        is_boss: bool = False,
        protect_focus: bool = False,
    ) -> Dict[str, Any]:
        """Award XP, check for level-ups, and unlock surprise dopamine drops."""
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM user_progress WHERE id = 1").fetchone()
            old_xp = row["xp"]
            old_level = max(1, (old_xp // 100) + 1)

            bonus_xp = 10 if random.random() < 0.25 else 0
            total_gain = amount + bonus_xp
            new_xp = old_xp + total_gain
            new_level = max(1, (new_xp // 100) + 1)

            bosses = row["bosses_defeated"] + (1 if is_boss else 0)
            focus_cnt = row["focus_protected_count"] + (1 if protect_focus else 0)
            badges: List[Dict[str, str]] = json.loads(row["badges_json"] or "[]")

            if is_boss and not any(b["id"] == "boss_master" for b in badges) and bosses >= 4:
                badges.append(
                    {
                        "id": "boss_master",
                        "name": "Boss Crusher",
                        "icon": "🏆",
                        "desc": "Defeated 4+ dreaded Daily Boss tasks!",
                    }
                )
            if protect_focus and not any(b["id"] == "sandbox_scientist" for b in badges) and focus_cnt >= 5:
                badges.append(
                    {
                        "id": "sandbox_scientist",
                        "name": "Sandbox Scientist",
                        "icon": "🧪",
                        "desc": "Parked 5+ Shiny Object ideas for background AI research!",
                    }
                )

            conn.execute(
                """
                UPDATE user_progress
                SET xp = ?, level = ?, bosses_defeated = ?, focus_protected_count = ?,
                    badges_json = ?, updated_at = ?
                WHERE id = 1
                """,
                (new_xp, new_level, bosses, focus_cnt, json.dumps(badges), datetime.now().isoformat()),
            )

        state = self.get_state()
        state["last_reward"] = {
            "xp_gained": total_gain,
            "base_xp": amount,
            "mystery_spark_bonus": bonus_xp,
            "reason": reason,
            "leveled_up": new_level > old_level,
            "new_level": new_level,
        }
        return state

    def set_energy_mode(self, mode: str) -> Dict[str, Any]:
        """Switch capacity mode ('high', 'steady', 'low_spoons'). Activates Grace Shield in Low-Spoons mode."""
        if mode not in ("high", "steady", "low_spoons"):
            mode = "steady"

        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM user_progress WHERE id = 1").fetchone()
            shield_active = row["grace_shield_active_today"]
            xp = row["xp"]
            shield_triggered = False

            if mode == "low_spoons" and not shield_active:
                shield_active = 1
                xp += 20
                shield_triggered = True

            conn.execute(
                """
                UPDATE user_progress
                SET energy_mode = ?, grace_shield_active_today = ?, xp = ?, updated_at = ?
                WHERE id = 1
                """,
                (mode, shield_active, xp, datetime.now().isoformat()),
            )

        state = self.get_state()
        state["grace_shield_just_activated"] = shield_triggered
        return state

    def spin_quick_win_roulette(self) -> Dict[str, Any]:
        """Pick one tiny, effortless 60-second action with a direct 1-click launch & auto-complete link."""
        with self.db.connect() as conn:
            email = conn.execute(
                "SELECT id, sender_name, subject, one_line_brief, draft_reply, xp_reward, target_url, local_file_path FROM triaged_emails WHERE status = 'pending' ORDER BY RANDOM() LIMIT 1"
            ).fetchone()
            prep = conn.execute(
                "SELECT id, title, starter_micro_step, xp_reward, horizon, target_url, local_file_path, target_label, inline_action_label FROM proactive_suggestions WHERE is_cleared = 0 ORDER BY is_daily_boss DESC, RANDOM() LIMIT 1"
            ).fetchone()

        candidates = []
        if email:
            candidates.append(
                {
                    "type": "email",
                    "id": email["id"],
                    "headline": f"60-Second Email Win: Approve & Send Reply to {email['sender_name']}",
                    "micro_action": f"Pre-drafted reply for '{email['subject']}': \"{email['draft_reply'][:120]}...\"",
                    "button_label": f"✉️ 1-Click Send Reply & Claim +{email['xp_reward']} XP",
                    "xp_reward": email["xp_reward"],
                    "target_tab": "inbox",
                    "draft_reply": email["draft_reply"],
                }
            )
        if prep:
            candidates.append(
                {
                    "type": "suggestion",
                    "id": prep["id"],
                    "headline": f"90-Second Launch & Win: {prep['title']}",
                    "micro_action": prep["starter_micro_step"],
                    "button_label": prep["inline_action_label"] or f"🚀 Launch Target & Auto-Complete (+{prep['xp_reward']} XP)",
                    "xp_reward": prep["xp_reward"],
                    "target_tab": "briefing",
                    "target_url": prep["target_url"],
                    "local_file_path": prep["local_file_path"],
                }
            )
        candidates.append(
            {
                "type": "hydration_reset",
                "id": 0,
                "headline": "Nervous System Micro-Reset: Drink Water & Drop Your Shoulders",
                "micro_action": "Unclench your jaw, take 1 slow breath, and take a sip of water. Instant +15 XP.",
                "button_label": "✓ Done! Claim +15 XP",
                "xp_reward": 15,
                "target_tab": "instant",
            }
        )
        return random.choice(candidates)
