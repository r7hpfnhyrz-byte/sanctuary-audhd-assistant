"""Accomplishment & Cleared Vault Engine: Day, Week, Month, and Year lookbacks + Notion Sync."""

import json
from datetime import datetime, timedelta
from typing import Any, Dict, List

from backend.connectors.notion_connector import NotionWorkspaceConnector
from backend.database import Database


class AccomplishmentVaultEngine:
    """Combats ADHD 'productivity amnesia' by storing and summarizing cleared items across Day, Week, Month, and Year."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def get_vault_lookback(self, window: str = "week") -> Dict[str, Any]:
        """Return cleared items filtered by 'day', 'week', 'month', or 'year' with celebration metrics."""
        now = datetime.now()
        cutoff_map = {
            "day": now - timedelta(days=1),
            "week": now - timedelta(days=7),
            "month": now - timedelta(days=31),
            "year": now - timedelta(days=365),
        }
        cutoff = cutoff_map.get(window, now - timedelta(days=7)).isoformat()

        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM cleared_vault
                WHERE cleared_at >= ?
                ORDER BY cleared_at DESC
                """,
                (cutoff,),
            ).fetchall()

            all_counts = {
                "day": conn.execute(
                    "SELECT COUNT(*) AS c FROM cleared_vault WHERE cleared_at >= ?",
                    ((now - timedelta(days=1)).isoformat(),),
                ).fetchone()["c"],
                "week": conn.execute(
                    "SELECT COUNT(*) AS c FROM cleared_vault WHERE cleared_at >= ?",
                    ((now - timedelta(days=7)).isoformat(),),
                ).fetchone()["c"],
                "month": conn.execute(
                    "SELECT COUNT(*) AS c FROM cleared_vault WHERE cleared_at >= ?",
                    ((now - timedelta(days=31)).isoformat(),),
                ).fetchone()["c"],
                "year": conn.execute(
                    "SELECT COUNT(*) AS c FROM cleared_vault WHERE cleared_at >= ?",
                    ((now - timedelta(days=365)).isoformat(),),
                ).fetchone()["c"],
            }

        items = [dict(r) for r in rows]
        total_xp = sum(int(i.get("xp_earned", 0)) for i in items)
        bosses_slain = sum(1 for i in items if i.get("was_boss"))
        emails_cleared = sum(1 for i in items if i.get("item_type") == "email_sent")
        ideas_parked = sum(1 for i in items if i.get("item_type") == "idea_parked")

        window_labels = {
            "day": "Today",
            "week": "This week",
            "month": "This month",
            "year": "This year",
        }

        def count(n: int, word: str) -> str:
            return f"{n} {word}" if n == 1 else f"{n} {word}s"

        narrative = (
            f"**{window_labels.get(window, 'This period')}:** you finished **{count(len(items), 'thing')}**, "
            f"handled **{count(emails_cleared, 'email')}** and parked **{count(ideas_parked, 'idea')}** for later."
        )

        return {
            "window": window,
            "window_label": window_labels.get(window, "This Week"),
            "counts_by_window": all_counts,
            "total_items": len(items),
            "total_xp_earned": total_xp,
            "bosses_slain": bosses_slain,
            "emails_cleared": emails_cleared,
            "ideas_parked": ideas_parked,
            "coach_celebration_summary": narrative,
            "items": items,
        }

    def sync_all_to_notion(self) -> Dict[str, Any]:
        """Trigger a manual or scheduled sync of the Daily Briefing, Idea Sandbox, and Cleared Vault to Notion."""
        with self.db.connect() as conn:
            notion_accs = conn.execute(
                "SELECT * FROM connected_accounts WHERE provider = 'notion' AND is_active = 1"
            ).fetchall()
            cleared = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM cleared_vault ORDER BY cleared_at DESC LIMIT 50"
                ).fetchall()
            ]
            ideas = [
                dict(r)
                for r in conn.execute("SELECT * FROM idea_sandbox ORDER BY id DESC").fetchall()
            ]
            prog = dict(conn.execute("SELECT * FROM user_progress WHERE id = 1").fetchone())

        results = []
        for acc in notion_accs:
            creds = json.loads(acc["credentials_json"] or "{}")
            res = NotionWorkspaceConnector.sync_command_centre_and_vault(
                credentials=creds,
                briefing_summary={"energy_mode": prog.get("energy_mode"), "today_priorities": cleared[:3]},
                cleared_items=cleared,
                sandbox_ideas=ideas,
            )
            res["workspace"] = acc["account_label"]
            results.append(res)

        return {"ok": True, "workspaces_synced": results}
