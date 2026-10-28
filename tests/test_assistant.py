import os
import tempfile
import unittest
from pathlib import Path

from backend.main import AssistantApplication


class TestAuDHDAssistant(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["AUDHD_TEST_MODE"] = "1"
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "test_assistant.db"
        self.app = AssistantApplication(db_path=self.db_path)

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_01_multi_account_registry_and_addition(self) -> None:
        status, data = self.app.handle_api("GET", "/api/accounts", {}, {})
        self.assertEqual(status, 200)
        accounts = data["accounts"]
        providers = {a["provider"] for a in accounts}
        self.assertEqual(providers, {"google", "microsoft", "notion"})
        self.assertGreaterEqual(len(accounts), 6)

        # Add another Outlook account
        status, add_res = self.app.handle_api(
            "POST",
            "/api/accounts",
            {},
            {
                "provider": "microsoft",
                "account_label": "Secondary Clinical Outlook",
                "account_identifier": "clinical@spire.org.uk",
                "api_token": "",
            },
        )
        self.assertEqual(status, 200)
        self.assertTrue(add_res["ok"])
        self.assertIn("login.microsoftonline.com", add_res["oauth_url"])

    def test_02_briefing_and_four_horizons(self) -> None:
        status, briefing = self.app.handle_api("GET", "/api/briefing", {}, {})
        self.assertEqual(status, 200)
        horizons = briefing["horizons"]
        self.assertIn("1d", horizons)
        self.assertIn("2d", horizons)
        self.assertIn("1w", horizons)
        self.assertIn("1m", horizons)
        self.assertGreaterEqual(len(horizons["1d"]), 2)
        self.assertGreaterEqual(len(horizons["2d"]), 1)
        self.assertGreaterEqual(len(horizons["1w"]), 1)
        self.assertGreaterEqual(len(horizons["1m"]), 1)
        self.assertIsNotNone(briefing["daily_boss"])

    def test_03_energy_modes_and_low_spoons_grace_shield(self) -> None:
        # Switch to low_spoons mode
        status, res = self.app.handle_api(
            "POST", "/api/energy-mode", {}, {"mode": "low_spoons"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(res["progress"]["energy_mode"], "low_spoons")
        self.assertEqual(res["progress"]["grace_shield_active_today"], 1)
        self.assertTrue(res["progress"]["grace_shield_just_activated"])
        # In Low Spoons mode, 30-day noise is hidden to prevent overwhelm
        self.assertEqual(len(res["briefing"]["horizons"]["1m"]), 0)

    def test_04_daily_boss_defeat_and_vault_archiving(self) -> None:
        _, briefing = self.app.handle_api("GET", "/api/briefing", {}, {})
        boss_id = briefing["daily_boss"]["id"]
        old_xp = briefing["progress"]["xp"]

        status, res = self.app.handle_api(
            "POST", "/api/suggestions/complete", {}, {"id": boss_id}
        )
        self.assertEqual(status, 200)
        self.assertTrue(res["ok"])
        self.assertGreaterEqual(res["progress"]["xp"], old_xp + 75)

        # Verify boss defeat appears in the Accomplishment Vault
        _, vault = self.app.handle_api("GET", "/api/vault", {"window": "day"}, {})
        titles = [item["title"] for item in vault["items"]]
        self.assertTrue(any("Master Funding Tracker" in t for t in titles))

    def test_05_email_triage_tone_shift_and_send(self) -> None:
        status, data = self.app.handle_api("GET", "/api/emails", {}, {})
        self.assertEqual(status, 200)
        emails = data["emails"]
        self.assertGreaterEqual(len(emails), 3)
        target_email = emails[0]

        # Shift tone to polite_boundary
        status, tone_res = self.app.handle_api(
            "POST",
            "/api/emails/tone",
            {},
            {"id": target_email["id"], "tone": "polite_boundary"},
        )
        self.assertEqual(status, 200)
        self.assertTrue(tone_res["ok"])
        self.assertIn("capacity", tone_res["draft_reply"].lower())

        # Approve & Send email
        status, send_res = self.app.handle_api(
            "POST",
            "/api/emails/send",
            {},
            {
                "id": target_email["id"],
                "draft_reply": tone_res["draft_reply"],
                "action": "send",
            },
        )
        self.assertEqual(status, 200)
        self.assertTrue(send_res["ok"])

    def test_06_shiny_object_idea_sandbox_and_dossier(self) -> None:
        status, res = self.app.handle_api(
            "POST",
            "/api/ideas",
            {},
            {
                "title": "VR Sensory Decompression Room for Neurodivergent Students",
                "raw_spark": "Build a lightweight web VR calming space between university lectures.",
                "category": "Wild Spark",
            },
        )
        self.assertEqual(status, 200)
        self.assertTrue(res["ok"])
        idea = res["idea"]
        self.assertEqual(idea["status"], "dossier_ready")
        self.assertIn("core_thesis", idea["dossier"])
        self.assertIn("priority_guardrail", idea["dossier"])
        self.assertGreaterEqual(len(idea["dossier"]["micro_experiments"]), 2)

    def test_07_vault_day_week_month_year_and_notion_sync(self) -> None:
        for window in ("day", "week", "month", "year"):
            status, v = self.app.handle_api("GET", "/api/vault", {"window": window}, {})
            self.assertEqual(status, 200)
            self.assertEqual(v["window"], window)
            self.assertGreaterEqual(v["total_items"], 1)

        status, sync = self.app.handle_api("POST", "/api/vault/sync-notion", {}, {})
        self.assertEqual(status, 200)
        self.assertTrue(sync["ok"])
        self.assertGreaterEqual(len(sync["workspaces_synced"]), 2)

    def test_08_coach_and_roulette_and_micro_step_breaker(self) -> None:
        status, r_res = self.app.handle_api("POST", "/api/roulette", {}, {})
        self.assertEqual(status, 200)
        self.assertTrue(r_res["ok"])
        self.assertIn("headline", r_res["roulette"])

        status, c_res = self.app.handle_api(
            "POST",
            "/api/coach",
            {},
            {"message": "I am stuck in task paralysis and avoiding my admin"},
        )
        self.assertEqual(status, 200)
        self.assertTrue(c_res["ok"])
        self.assertIn("90-Second", c_res["reply"])

        status, b_res = self.app.handle_api(
            "POST",
            "/api/tasks/break-down",
            {},
            {"title": "Complete annual tax return spreadsheet"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(b_res["micro_steps"]), 4)

    def test_09_direct_launch_and_auto_complete(self) -> None:
        _, briefing = self.app.handle_api("GET", "/api/briefing", {}, {})
        boss = briefing["daily_boss"]
        self.assertTrue(boss["target_label"])
        self.assertTrue(boss["local_file_path"] or boss["target_url"])

        # 1. Test Peek / Pin mode (auto_complete = False)
        status, peek_res = self.app.handle_api(
            "POST",
            "/api/actions/launch-and-complete",
            {},
            {"id": boss["id"], "auto_complete": False},
        )
        self.assertEqual(status, 200)
        self.assertTrue(peek_res["ok"])
        self.assertFalse(peek_res["auto_completed"])
        self.assertEqual(peek_res["pinned_item"]["id"], boss["id"])

        # 2. Test 1-Click Launch & Auto-Complete (auto_complete = True)
        status, launch_res = self.app.handle_api(
            "POST",
            "/api/actions/launch-and-complete",
            {},
            {"id": boss["id"], "auto_complete": True},
        )
        self.assertEqual(status, 200)
        self.assertTrue(launch_res["ok"])
        self.assertTrue(launch_res["auto_completed"])
        self.assertIn("launched", launch_res)

    def test_10_urgency_and_assignee_rules(self) -> None:
        from datetime import date

        from backend.engine.briefing_horizon import classify_urgency, guess_assignee

        today = date(2026, 10, 27)
        self.assertEqual(classify_urgency({"title": "x", "due_context": "2025-01-12"}, today), "urgent")
        self.assertEqual(classify_urgency({"title": "x", "due_context": "2026-10-28"}, today), "urgent")
        self.assertEqual(classify_urgency({"title": "x", "due_context": "2026-11-01"}, today), "soon")
        self.assertEqual(
            classify_urgency({"title": "[7CL503 • Priority: High] x", "due_context": "2026-11-01"}, today),
            "urgent",
        )
        self.assertEqual(classify_urgency({"title": "x", "due_context": "2026-12-01"}, today), "later")
        self.assertEqual(classify_urgency({"title": "x", "due_context": "Not started"}, today), "later")
        self.assertEqual(classify_urgency({"title": "[Priority: High] x", "due_context": ""}, today), "soon")
        self.assertEqual(classify_urgency({"title": "x", "due_context": "Today before 2:00 PM"}, today), "urgent")

        # Assessed work stays with the person even when it also says "write" or "draft"
        self.assertEqual(guess_assignee({"title": "⏰ [7CL503 • Hard Deadline] Write reflective essay draft"}), "me")
        self.assertEqual(guess_assignee({"title": "Notion: Draft email to placement manager"}), "me")
        self.assertEqual(guess_assignee({"title": "Draft agenda for team meeting"}), "ai")
        self.assertEqual(guess_assignee({"title": "Call the GP surgery"}), "me")
        self.assertEqual(guess_assignee({"title": "Draft funding report summary"}), "ai")
        self.assertEqual(guess_assignee({"title": "Tidy desk"}), "me")
        # The user's own choice always wins
        self.assertEqual(guess_assignee({"title": "Tidy desk", "assignee": "ai"}), "ai")

    def test_11_done_today_undo_assignee_and_ai_draft(self) -> None:
        _, briefing = self.app.handle_api("GET", "/api/briefing", {}, {})
        task = briefing["horizons"]["1d"][0]
        for key in ("urgency", "assignee", "assignee_is_choice"):
            self.assertIn(key, task)

        # Done shows up under done_today, and Undo puts it back
        self.app.handle_api("POST", "/api/suggestions/complete", {}, {"id": task["id"]})
        _, briefing = self.app.handle_api("GET", "/api/briefing", {}, {})
        self.assertIn(task["id"], [d["id"] for d in briefing["done_today"]])
        self.assertEqual(briefing["status_counts"]["done_today"], len(briefing["done_today"]))

        _, res = self.app.handle_api("POST", "/api/suggestions/reopen", {}, {"id": task["id"]})
        self.assertTrue(res["ok"])
        _, briefing = self.app.handle_api("GET", "/api/briefing", {}, {})
        self.assertNotIn(task["id"], [d["id"] for d in briefing["done_today"]])

        # Switching You / AI sticks
        _, res = self.app.handle_api("POST", "/api/suggestions/assignee", {}, {"id": task["id"], "assignee": "ai"})
        self.assertTrue(res["ok"])
        _, res = self.app.handle_api("POST", "/api/suggestions/assignee", {}, {"id": task["id"], "assignee": "robot"})
        self.assertFalse(res["ok"])
        _, briefing = self.app.handle_api("GET", "/api/briefing", {}, {})
        all_items = [s for items in briefing["horizons"].values() for s in items]
        if briefing["daily_boss"]:
            all_items.append(briefing["daily_boss"])
        saved = next(s for s in all_items if s["id"] == task["id"])
        self.assertEqual(saved["assignee"], "ai")
        self.assertTrue(saved["assignee_is_choice"])

        # AI draft is saved on the task; a failed AI call reports it plainly
        self.app.briefing.ai.generate = lambda *a, **k: {"text": "", "provider": ""}
        _, res = self.app.handle_api("POST", "/api/suggestions/ai-draft", {}, {"id": task["id"]})
        self.assertFalse(res["ok"])
        self.app.briefing.ai.generate = lambda *a, **k: {"text": "Dear team,\nHere is the plan.", "provider": "Test"}
        _, res = self.app.handle_api("POST", "/api/suggestions/ai-draft", {}, {"id": task["id"]})
        self.assertTrue(res["ok"])
        _, briefing = self.app.handle_api("GET", "/api/briefing", {}, {})
        all_items = [s for items in briefing["horizons"].values() for s in items]
        if briefing["daily_boss"]:
            all_items.append(briefing["daily_boss"])
        self.assertEqual(next(s for s in all_items if s["id"] == task["id"])["ai_draft"], "Dear team,\nHere is the plan.")


    def test_12_ai_router_models_thinking_blocks_and_error_reasons(self) -> None:
        import io
        import json
        import urllib.error
        from unittest import mock

        from backend.ai.router import DualAIRouter

        router = DualAIRouter()
        router.claude_key = "sk-test"
        router.gemini_key = "gm-secret-key"
        router.refresh_keys = lambda: None
        seen_models = []

        def http_error(url, code, message):
            body = io.BytesIO(json.dumps({"error": {"message": message}}).encode())
            return urllib.error.HTTPError(url, code, "err", {}, body)

        class Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_urlopen(req, timeout=0):
            url = req.full_url
            if "anthropic" in url:
                model = json.loads(req.data)["model"]
                seen_models.append(model)
                if model != "claude-sonnet-5-5":
                    raise http_error(url, 404, f"model: {model}")
                # A thinking block arrives before the answer on current models
                return Resp(json.dumps({
                    "stop_reason": "end_turn",
                    "content": [{"type": "thinking", "thinking": ""}, {"type": "text", "text": "Draft text"}],
                }).encode())
            raise http_error(url, 404, "models/gemini is not found")

        with mock.patch("urllib.request.urlopen", fake_urlopen), \
                mock.patch("backend.ai.router.Config.ANTHROPIC_MODEL", "claude-3-7-sonnet-latest"):
            res = router.generate("hi", prefer="claude")
        self.assertEqual(res["text"], "Draft text")
        self.assertEqual(seen_models, ["claude-3-7-sonnet-latest", "claude-sonnet-5-5"])

        # Bad Claude key and missing Gemini models: the reasons come back, the Gemini key never does
        def all_fail(req, timeout=0):
            if "anthropic" in req.full_url:
                raise http_error(req.full_url, 401, "invalid x-api-key")
            raise http_error(req.full_url, 404, "models/gemini-flash-latest is not found")

        with mock.patch("urllib.request.urlopen", all_fail):
            res = router.generate("hi", prefer="claude")
        self.assertEqual(res["text"], "")
        joined = " ".join(res["errors"])
        self.assertIn("HTTP 401: invalid x-api-key", joined)
        self.assertIn("HTTP 404", joined)
        self.assertNotIn("gm-secret-key", joined)
        # A bad key is not retried on every model
        self.assertEqual(sum("Claude (" in e for e in res["errors"]), 1)


if __name__ == "__main__":
    unittest.main()
