"""The 'Shiny Object' Idea Sandbox & Autonomous Incubator Agent Engine."""

import json
from datetime import datetime
from typing import Any, Dict, List

from backend.ai.router import DualAIRouter
from backend.database import Database
from backend.engine.gamification import GamificationEngine


class IdeaIncubatorEngine:
    """Parks weird and wonderful ideas (+25 XP Focus Protected!) and autonomously builds Concept & Feasibility Dossiers."""

    def __init__(self, db: Database, ai: DualAIRouter, game: GamificationEngine) -> None:
        self.db = db
        self.ai = ai
        self.game = game

    def list_ideas(self) -> List[Dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM idea_sandbox WHERE status != 'archived' ORDER BY id DESC"
            ).fetchall()
        results = []
        for r in rows:
            item = dict(r)
            item["dossier"] = json.loads(item.get("dossier_json") or "{}")
            results.append(item)
        return results

    def park_and_incubate_idea(
        self, title: str, raw_spark: str, category: str = "Wild Spark"
    ) -> Dict[str, Any]:
        """Capture a new idea, immediately award +25 XP for NOT derailing today's priorities, and run the AI Research Dossier."""
        now = datetime.now().isoformat()
        dossier = self.ai.research_sandbox_idea(title=title, raw_spark=raw_spark)
        score = int(dossier.get("viability_score", 82))
        risk = str(dossier.get("distraction_risk", "Moderate — Keep Parked Until Friday"))
        effort = str(dossier.get("effort_estimate", "Weekend Prototype"))

        with self.db.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO idea_sandbox (
                    title, raw_spark, category, status, viability_score,
                    distraction_risk, effort_estimate, dossier_json, xp_awarded,
                    synced_to_notion, created_at, updated_at
                ) VALUES (?, ?, ?, 'dossier_ready', ?, ?, ?, ?, 25, 1, ?, ?)
                """,
                (
                    title,
                    raw_spark,
                    category,
                    score,
                    risk,
                    effort,
                    json.dumps(dossier),
                    now,
                    now,
                ),
            )
            idea_id = cur.lastrowid

            # Log to Accomplishment Vault so the user sees they protected their focus!
            conn.execute(
                """
                INSERT INTO cleared_vault (
                    item_type, title, summary, account_label, horizon_tag,
                    xp_earned, was_boss, synced_to_notion, cleared_at
                ) VALUES ('idea_parked', ?, ?, 'Shiny Object Sandbox → Notion Incubator', '1d', 25, 0, 1, ?)
                """,
                (
                    f"🛡️ Focus Protected! Parked & Researched Idea: {title}",
                    dossier.get("core_thesis", raw_spark),
                    now,
                ),
            )

        progress = self.game.award_xp(
            amount=25,
            reason=f"🛡️ Focus Protected! Parked '{title}' in Idea Sandbox",
            protect_focus=True,
        )
        return {
            "ok": True,
            "idea": {
                "id": idea_id,
                "title": title,
                "raw_spark": raw_spark,
                "category": category,
                "status": "dossier_ready",
                "viability_score": score,
                "distraction_risk": risk,
                "effort_estimate": effort,
                "dossier": dossier,
                "created_at": now,
            },
            "progress": progress,
        }
