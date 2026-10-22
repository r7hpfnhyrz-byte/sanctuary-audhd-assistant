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


if __name__ == "__main__":
    unittest.main()
