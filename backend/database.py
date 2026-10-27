"""Database layer for the AuDHD Personal Assistant, Gamification Engine, Idea Sandbox, and Accomplishment Vault."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

from backend.config import Config

DRIVE_ROOT = "/Users/student/Library/CloudStorage/GoogleDrive-robknightstrong@gmail.com/My Drive"


class Database:
    """Thread-safe SQLite database manager with automatic schema initialization, migration, and seed data."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = Path(db_path or Config.DB_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_schema()

    @contextmanager
    def connect(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(str(self.db_path), timeout=15.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _ensure_column(self, conn: sqlite3.Connection, table: str, col: str, col_def: str) -> None:
        cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        if col not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_def}")

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS connected_accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    provider TEXT NOT NULL,           -- 'google', 'microsoft', 'notion'
                    account_label TEXT NOT NULL,      -- e.g. 'Personal Gmail', 'Spire Therapy Outlook'
                    account_identifier TEXT NOT NULL, -- email or workspace name
                    color_tag TEXT DEFAULT '#6366f1',
                    portal_url TEXT DEFAULT '',
                    credentials_json TEXT DEFAULT '{}',
                    scopes_json TEXT DEFAULT '[]',
                    is_active INTEGER DEFAULT 1,
                    last_synced_at TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS user_progress (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    xp INTEGER DEFAULT 340,
                    level INTEGER DEFAULT 4,
                    energy_mode TEXT DEFAULT 'steady', -- 'high', 'steady', 'low_spoons'
                    momentum_days INTEGER DEFAULT 5,
                    grace_shields INTEGER DEFAULT 2,
                    grace_shield_active_today INTEGER DEFAULT 0,
                    bosses_defeated INTEGER DEFAULT 3,
                    focus_protected_count INTEGER DEFAULT 4,
                    badges_json TEXT DEFAULT '[]',
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS calendar_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id INTEGER,
                    account_label TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    title TEXT NOT NULL,
                    start_time TEXT NOT NULL,
                    end_time TEXT NOT NULL,
                    horizon TEXT NOT NULL,            -- '1d', '2d', '1w', '1m'
                    cognitive_load INTEGER DEFAULT 5, -- 1 to 10
                    social_load INTEGER DEFAULT 5,    -- 1 to 10
                    transition_buffer_mins INTEGER DEFAULT 15,
                    prep_needed TEXT DEFAULT '',
                    location TEXT DEFAULT '',
                    target_url TEXT DEFAULT '',
                    local_file_path TEXT DEFAULT '',
                    target_label TEXT DEFAULT 'Open Calendar Event',
                    is_cleared INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS proactive_suggestions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    horizon TEXT NOT NULL,            -- '1d', '2d', '1w', '1m'
                    title TEXT NOT NULL,
                    why_it_matters TEXT NOT NULL,
                    starter_micro_step TEXT NOT NULL, -- 2-minute friction-free step
                    micro_steps_json TEXT DEFAULT '[]',
                    source_label TEXT NOT NULL,       -- e.g. 'Google Calendar + Notion'
                    energy_required TEXT DEFAULT 'steady', -- 'low', 'steady', 'high'
                    is_daily_boss INTEGER DEFAULT 0,
                    xp_reward INTEGER DEFAULT 25,
                    due_context TEXT DEFAULT '',
                    target_url TEXT DEFAULT '',
                    local_file_path TEXT DEFAULT '',
                    target_label TEXT DEFAULT 'Open Linked Task',
                    inline_action_type TEXT DEFAULT 'open_and_complete', -- 'open_file', 'calendar_buffer', 'jump_inbox', 'inline_reschedule'
                    inline_action_label TEXT DEFAULT '🚀 Open & Auto-Complete',
                    is_cleared INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS triaged_emails (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id INTEGER,
                    account_label TEXT NOT NULL,
                    provider TEXT NOT NULL,           -- 'google' or 'microsoft'
                    sender_name TEXT NOT NULL,
                    sender_email TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    received_at TEXT NOT NULL,
                    urgency TEXT NOT NULL,            -- 'action_required', 'quick_read', 'low_priority'
                    one_line_brief TEXT NOT NULL,
                    what_they_need TEXT NOT NULL,
                    draft_reply TEXT NOT NULL,
                    draft_tone TEXT DEFAULT 'warm_balanced',
                    energy_required TEXT DEFAULT 'low',
                    xp_reward INTEGER DEFAULT 20,
                    status TEXT DEFAULT 'pending',    -- 'pending', 'sent', 'archived'
                    external_message_id TEXT DEFAULT '',
                    target_url TEXT DEFAULT '',
                    local_file_path TEXT DEFAULT '',
                    attachment_label TEXT DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS idea_sandbox (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    raw_spark TEXT NOT NULL,
                    category TEXT DEFAULT 'Wild Spark',
                    status TEXT DEFAULT 'incubating', -- 'incubating', 'dossier_ready', 'promoted', 'archived'
                    viability_score INTEGER DEFAULT 0,
                    distraction_risk TEXT DEFAULT 'Medium',
                    effort_estimate TEXT DEFAULT 'Weekend Project',
                    dossier_json TEXT DEFAULT '{}',
                    xp_awarded INTEGER DEFAULT 25,
                    synced_to_notion INTEGER DEFAULT 0,
                    notion_url TEXT DEFAULT 'https://www.notion.so',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS cleared_vault (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_type TEXT NOT NULL,          -- 'email_sent', 'boss_defeated', 'horizon_prep', 'idea_parked', 'notion_task'
                    title TEXT NOT NULL,
                    summary TEXT DEFAULT '',
                    account_label TEXT DEFAULT 'General',
                    horizon_tag TEXT DEFAULT '1d',
                    xp_earned INTEGER DEFAULT 20,
                    was_boss INTEGER DEFAULT 0,
                    synced_to_notion INTEGER DEFAULT 0,
                    target_url TEXT DEFAULT '',
                    local_file_path TEXT DEFAULT '',
                    target_label TEXT DEFAULT '',
                    cleared_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS coach_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role TEXT NOT NULL,               -- 'user' or 'coach'
                    content TEXT NOT NULL,
                    energy_mode TEXT DEFAULT 'steady',
                    created_at TEXT NOT NULL
                );
                """
            )
            # Ensure columns exist on already-created DBs
            self._ensure_column(conn, "connected_accounts", "portal_url", "TEXT DEFAULT ''")
            self._ensure_column(conn, "calendar_events", "target_url", "TEXT DEFAULT ''")
            self._ensure_column(conn, "calendar_events", "local_file_path", "TEXT DEFAULT ''")
            self._ensure_column(conn, "calendar_events", "target_label", "TEXT DEFAULT 'Open Calendar Event'")
            self._ensure_column(conn, "proactive_suggestions", "target_url", "TEXT DEFAULT ''")
            self._ensure_column(conn, "proactive_suggestions", "local_file_path", "TEXT DEFAULT ''")
            self._ensure_column(conn, "proactive_suggestions", "target_label", "TEXT DEFAULT 'Open Linked Task'")
            self._ensure_column(conn, "proactive_suggestions", "inline_action_type", "TEXT DEFAULT 'open_and_complete'")
            self._ensure_column(conn, "proactive_suggestions", "inline_action_label", "TEXT DEFAULT '🚀 Open & Auto-Complete'")
            # '' = let Sanctuary guess; 'me' / 'ai' = the user's own choice
            self._ensure_column(conn, "proactive_suggestions", "assignee", "TEXT DEFAULT ''")
            self._ensure_column(conn, "proactive_suggestions", "ai_draft", "TEXT DEFAULT ''")
            self._ensure_column(conn, "proactive_suggestions", "cleared_at", "TEXT DEFAULT ''")
            self._ensure_column(conn, "triaged_emails", "target_url", "TEXT DEFAULT ''")
            self._ensure_column(conn, "triaged_emails", "local_file_path", "TEXT DEFAULT ''")
            self._ensure_column(conn, "triaged_emails", "attachment_label", "TEXT DEFAULT ''")
            self._ensure_column(conn, "idea_sandbox", "notion_url", "TEXT DEFAULT 'https://www.notion.so'")
            self._ensure_column(conn, "cleared_vault", "target_url", "TEXT DEFAULT ''")
            self._ensure_column(conn, "cleared_vault", "local_file_path", "TEXT DEFAULT ''")
            self._ensure_column(conn, "cleared_vault", "target_label", "TEXT DEFAULT ''")

        self.ensure_seed_data()
        self.backfill_deep_links()

    def backfill_deep_links(self) -> None:
        """Ensure any existing rows in SQLite have real deep links, local Google Drive file targets, and live env tokens."""
        with self.connect() as conn:
            if Config.NOTION_API_KEY:
                conn.execute(
                    """
                    UPDATE connected_accounts
                    SET credentials_json = ?
                    WHERE provider = 'notion'
                    """,
                    (json.dumps({"api_token": Config.NOTION_API_KEY, "access_token": Config.NOTION_API_KEY}),),
                )
            if Config.GOOGLE_ICS_ROB or Config.GOOGLE_APP_PASSWORD_ROB:
                rob_creds: Dict[str, Any] = {}
                if Config.GOOGLE_ICS_ROB:
                    rob_creds["ics_url"] = Config.GOOGLE_ICS_ROB
                if Config.GOOGLE_APP_PASSWORD_ROB:
                    rob_creds["app_password"] = Config.GOOGLE_APP_PASSWORD_ROB
                conn.execute(
                    """
                    UPDATE connected_accounts
                    SET credentials_json = ?
                    WHERE account_identifier = 'robknightstrong@gmail.com'
                    """,
                    (json.dumps(rob_creds),),
                )
            if Config.GOOGLE_ICS_FAMILY or Config.GOOGLE_APP_PASSWORD_FAMILY:
                fam_creds: Dict[str, Any] = {}
                if Config.GOOGLE_ICS_FAMILY:
                    fam_creds["ics_url"] = Config.GOOGLE_ICS_FAMILY
                if Config.GOOGLE_APP_PASSWORD_FAMILY:
                    fam_creds["app_password"] = Config.GOOGLE_APP_PASSWORD_FAMILY
                exists_fam = conn.execute(
                    "SELECT id FROM connected_accounts WHERE account_identifier = 'theknightstrongs@gmail.com'"
                ).fetchone()
                if exists_fam:
                    conn.execute(
                        "UPDATE connected_accounts SET credentials_json = ? WHERE id = ?",
                        (json.dumps(fam_creds), exists_fam["id"]),
                    )
                else:
                    now_str = datetime.now().isoformat()
                    conn.execute(
                        """
                        INSERT INTO connected_accounts (
                            provider, account_label, account_identifier, color_tag,
                            portal_url, credentials_json, is_active, last_synced_at, created_at
                        ) VALUES ('google', 'The Knight-Strongs Family Calendar', 'theknightstrongs@gmail.com', '#14b8a6', 'https://calendar.google.com', ?, 1, ?, ?)
                        """,
                        (json.dumps(fam_creds), now_str, now_str),
                    )
            conn.execute(
                """
                UPDATE proactive_suggestions
                SET local_file_path = ?,
                    target_url = 'https://docs.google.com/spreadsheets',
                    target_label = '📊 Spire Funding Tracker (LIVE).gsheet',
                    inline_action_type = 'open_file',
                    inline_action_label = '🚀 Open Funding Sheet & Auto-Complete (+75 XP)'
                WHERE title LIKE '%Master Funding Tracker%' AND (local_file_path = '' OR local_file_path IS NULL)
                """,
                (f"{DRIVE_ROOT}/Spire Funding Tracker (LIVE).gsheet",),
            )
            conn.execute(
                """
                UPDATE proactive_suggestions
                SET target_url = 'https://calendar.google.com/calendar/u/0/r/eventedit?text=Sensory+Decompression+Buffer+(No+Screens)',
                    target_label = '📅 Google & Outlook Calendar Buffer',
                    inline_action_type = 'calendar_buffer',
                    inline_action_label = '⚡ 1-Click Lock 20m Buffer & Complete (+20 XP)'
                WHERE title LIKE '%Sensory Decompression Buffer%' AND (target_url = '' OR target_url IS NULL)
                """
            )
            conn.execute(
                """
                UPDATE proactive_suggestions
                SET target_url = '#inbox',
                    local_file_path = ?,
                    target_label = '✉️ Jump Straight to Triage Studio (2 Drafts Ready)',
                    inline_action_type = 'jump_inbox',
                    inline_action_label = '⚡ Jump to Pre-Written Replies & Send'
                WHERE title LIKE '%Approve 2 Pre-Written Email%' AND (target_url = '' OR target_url IS NULL)
                """,
                (f"{DRIVE_ROOT}/Signed Placement Pack.pdf",),
            )
            conn.execute(
                """
                UPDATE proactive_suggestions
                SET local_file_path = ?,
                    target_url = 'https://docs.google.com/document',
                    target_label = '📘 MSc Integrative Therapy: Distinctions Learning Guide.gdoc',
                    inline_action_type = 'open_file',
                    inline_action_label = '🚀 Open MSc Guide & Auto-Complete (+30 XP)'
                WHERE title LIKE '%MSc Seminar%' AND (local_file_path = '' OR local_file_path IS NULL)
                """,
                (f"{DRIVE_ROOT}/MSc Integrative Therapy: Distinctions Learning Guide.gdoc",),
            )
            conn.execute(
                """
                UPDATE proactive_suggestions
                SET local_file_path = ?,
                    target_url = 'https://docs.google.com/document',
                    target_label = '📄 Spire_CFCCT_Commercial_Services_Agreement_DRAFT.gdoc',
                    inline_action_type = 'open_file',
                    inline_action_label = '🚀 Open CFCCT Agreement & Auto-Complete (+30 XP)'
                WHERE title LIKE '%CFCCT Agreement%' AND (local_file_path = '' OR local_file_path IS NULL)
                """,
                (f"{DRIVE_ROOT}/Spire_CFCCT_Commercial_Services_Agreement_DRAFT.gdoc",),
            )
            conn.execute(
                """
                UPDATE proactive_suggestions
                SET target_url = 'https://outlook.office.com/calendar/view/week',
                    target_label = '📅 Outlook & Google Calendar Week View',
                    inline_action_type = 'inline_reschedule',
                    inline_action_label = '⚡ Auto-Send Polite Reschedule & Rebalance (+35 XP)'
                WHERE title LIKE '%Meeting Wall%' AND (target_url = '' OR target_url IS NULL)
                """
            )
            conn.execute(
                """
                UPDATE proactive_suggestions
                SET local_file_path = ?,
                    target_url = 'https://www.notion.so',
                    target_label = '📑 sfe_dsa_continuing_students_form_2627_m.pdf',
                    inline_action_type = 'open_file',
                    inline_action_label = '🚀 Open DSA & Grant Docs + Auto-Complete (+40 XP)'
                WHERE title LIKE '%DSA Paperwork%' AND (local_file_path = '' OR local_file_path IS NULL)
                """,
                (f"{DRIVE_ROOT}/sfe_dsa_continuing_students_form_2627_m.pdf",),
            )

            # Calendar events deep links
            conn.execute(
                """
                UPDATE calendar_events
                SET target_url = 'https://calendar.google.com/calendar/u/0/r',
                    local_file_path = ?,
                    target_label = '🎥 Join Google Meet / Open Clinical Notes'
                WHERE provider = 'google' AND (target_url = '' OR target_url IS NULL)
                """,
                (f"{DRIVE_ROOT}/Spire_Model_Playbook_v0.2.gdoc",),
            )
            conn.execute(
                """
                UPDATE calendar_events
                SET target_url = 'https://outlook.office.com/calendar',
                    local_file_path = ?,
                    target_label = '🎥 Open Outlook Event / Funding Sheet'
                WHERE provider = 'microsoft' AND (target_url = '' OR target_url IS NULL)
                """,
                (f"{DRIVE_ROOT}/Spire Funding Tracker (LIVE).gsheet",),
            )
            conn.execute(
                """
                UPDATE calendar_events
                SET target_url = 'https://www.notion.so',
                    local_file_path = ?,
                    target_label = '📓 Open in Notion Command HQ'
                WHERE provider = 'notion' AND (target_url = '' OR target_url IS NULL)
                """,
                (f"{DRIVE_ROOT}/Selrok & Spire Therapy - Operational Blueprint & Scale-Up Tracker.gsheet",),
            )

            # Triaged emails deep links & related Drive attachments
            conn.execute(
                """
                UPDATE triaged_emails
                SET target_url = 'https://mail.google.com/mail/u/0/#inbox',
                    local_file_path = ?,
                    attachment_label = '📎 Open Signed Placement Pack.pdf'
                WHERE sender_name LIKE '%Sarah%' AND (target_url = '' OR target_url IS NULL)
                """,
                (f"{DRIVE_ROOT}/Signed Placement Pack.pdf",),
            )
            conn.execute(
                """
                UPDATE triaged_emails
                SET target_url = 'https://outlook.office.com/mail/inbox',
                    local_file_path = ?,
                    attachment_label = '📊 Open Scale-Up Tracker.gsheet'
                WHERE sender_name LIKE '%Marcus%' AND (target_url = '' OR target_url IS NULL)
                """,
                (f"{DRIVE_ROOT}/Selrok & Spire Therapy - Operational Blueprint & Scale-Up Tracker.gsheet",),
            )
            conn.execute(
                """
                UPDATE triaged_emails
                SET target_url = 'https://outlook.office.com/mail/inbox',
                    local_file_path = ?,
                    attachment_label = '📘 Open 7CL501 Module Handbook.docx'
                WHERE sender_name LIKE '%Helen%' AND (target_url = '' OR target_url IS NULL)
                """,
                (f"{DRIVE_ROOT}/Gemini Gems/7CL501 Module Handbook 2025-26 .docx",),
            )
            conn.execute(
                """
                UPDATE triaged_emails
                SET target_url = 'https://mail.google.com/mail/u/0/#inbox',
                    local_file_path = ?,
                    attachment_label = '📄 Open Zurich Combined Liability Certificate.pdf'
                WHERE sender_name LIKE '%Keith%' AND (target_url = '' OR target_url IS NULL)
                """,
                (f"{DRIVE_ROOT}/Mr_Rob_Knight-Strong26_Confirm_&_Certificate_Zurich_Combined_Liability.pdf",),
            )

            # Cleared vault items deep links
            conn.execute(
                """
                UPDATE cleared_vault
                SET local_file_path = ?,
                    target_url = 'https://docs.google.com/document',
                    target_label = '📄 Open Spire_Master_Funding_Reference.gdoc'
                WHERE title LIKE '%Master Funding Reference%' AND (target_label = '' OR target_label IS NULL)
                """,
                (f"{DRIVE_ROOT}/Spire_Master_Funding_Reference.gdoc",),
            )
            conn.execute(
                """
                UPDATE cleared_vault
                SET local_file_path = ?,
                    target_url = 'https://www.notion.so',
                    target_label = '📄 Open SAFEGUARDING POLICY 2025-26.pdf'
                WHERE title LIKE '%Safeguarding Policy%' AND (target_label = '' OR target_label IS NULL)
                """,
                (f"{DRIVE_ROOT}/SAFEGUARDING POLICY 2025-26.pdf",),
            )

    def ensure_seed_data(self) -> None:
        """Seed realistic multi-account context if database is freshly created."""
        now = datetime.now()
        with self.connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS cnt FROM user_progress").fetchone()
            if row and row["cnt"] > 0:
                return

            # 1. Initialize User Gamification & Capacity State
            badges = [
                {"id": "focus_defender", "name": "Focus Defender", "icon": "🛡️", "desc": "Parked 3+ shiny ideas without derailing your day"},
                {"id": "boss_slayer", "name": "Dread Breaker", "icon": "⚔️", "desc": "Defeated a procrastinated Daily Boss task"},
                {"id": "spoon_steward", "name": "Spoon Steward", "icon": "🌱", "desc": "Used Low-Spoons mode to prevent burnout"},
            ]
            conn.execute(
                """
                INSERT INTO user_progress (
                    id, xp, level, energy_mode, momentum_days, grace_shields,
                    grace_shield_active_today, bosses_defeated, focus_protected_count,
                    badges_json, updated_at
                ) VALUES (1, 340, 4, 'steady', 5, 2, 0, 3, 4, ?, ?)
                """,
                (json.dumps(badges), now.isoformat()),
            )

            # 2. Seed Multi-Account Registry
            accounts = [
                ("google", "Personal Gmail & Calendar", "robknightstrong@gmail.com", "#10b981", "https://mail.google.com/mail/u/0/#inbox", '{"mode":"demo_or_oauth"}'),
                ("google", "Spire Therapy Google Workspace", "rob@spiretherapy.org.uk", "#0ea5e9", "https://calendar.google.com/calendar/u/0/r", '{"mode":"demo_or_oauth"}'),
                ("microsoft", "Outlook 365 — Consultancy & Practice", "rob.knight-strong@outlook.com", "#6366f1", "https://outlook.office.com/mail/", '{"mode":"demo_or_oauth"}'),
                ("microsoft", "University / MSc Outlook 365", "r.knightstrong@university.ac.uk", "#8b5cf6", "https://outlook.office.com/calendar/", '{"mode":"demo_or_oauth"}'),
                ("notion", "Notion — Spire & Selrok Command HQ", "Spire & Selrok Workspace", "#f59e0b", "https://www.notion.so", '{"mode":"demo_or_oauth"}'),
                ("notion", "Notion — Personal Life & MSc Study", "Personal & MSc Workspace", "#ec4899", "https://www.notion.so", '{"mode":"demo_or_oauth"}'),
            ]
            for provider, label, ident, color, portal, creds in accounts:
                conn.execute(
                    """
                    INSERT INTO connected_accounts (
                        provider, account_label, account_identifier, color_tag,
                        portal_url, credentials_json, is_active, last_synced_at, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
                    """,
                    (provider, label, ident, color, portal, creds, now.isoformat(), now.isoformat()),
                )

            # 3. Seed Multi-Horizon Calendar Events
            events = [
                (
                    1,
                    "Spire Therapy Google Workspace",
                    "google",
                    "Spire CIC Clinical Supervision & Ops Sync",
                    (now + timedelta(hours=2)).strftime("%Y-%m-%d %H:00"),
                    (now + timedelta(hours=3)).strftime("%Y-%m-%d %H:00"),
                    "1d",
                    7,
                    8,
                    20,
                    "Review clinical supervision notes + 15m sensory decompression after",
                    "Google Meet",
                    "https://calendar.google.com/calendar/u/0/r",
                    f"{DRIVE_ROOT}/Spire_Model_Playbook_v0.2.gdoc",
                    "🎥 Join Meet & Open Spire Playbook.gdoc",
                ),
                (
                    3,
                    "Outlook 365 — Consultancy & Practice",
                    "microsoft",
                    "Grant Funding Review Call (UnLtd / Master Funding Tracker)",
                    (now + timedelta(hours=5)).strftime("%Y-%m-%d %H:30"),
                    (now + timedelta(hours=6)).strftime("%Y-%m-%d %H:15"),
                    "1d",
                    8,
                    6,
                    15,
                    "Open Spire Funding Tracker sheet 10 mins before call",
                    "Microsoft Teams",
                    "https://outlook.office.com/calendar",
                    f"{DRIVE_ROOT}/Spire Funding Tracker (LIVE).gsheet",
                    "📊 Open Spire Funding Tracker (LIVE).gsheet",
                ),
                (
                    4,
                    "University / MSc Outlook 365",
                    "microsoft",
                    "MSc Integrative Therapy Seminar & Case Formulation",
                    (now + timedelta(days=1, hours=3)).strftime("%Y-%m-%d 14:00"),
                    (now + timedelta(days=1, hours=5)).strftime("%Y-%m-%d 16:00"),
                    "2d",
                    8,
                    7,
                    30,
                    "Skim 2 pages of Distinctions Learning Guide tomorrow morning",
                    "Campus / Hybrid",
                    "https://outlook.office.com/calendar",
                    f"{DRIVE_ROOT}/MSc Integrative Therapy: Distinctions Learning Guide.gdoc",
                    "📘 Open Distinctions Learning Guide.gdoc",
                ),
                (
                    2,
                    "Spire Therapy Google Workspace",
                    "google",
                    "CFCCT Commercial Services Agreement Sign-Off",
                    (now + timedelta(days=2)).strftime("%Y-%m-%d 11:00"),
                    (now + timedelta(days=2)).strftime("%Y-%m-%d 12:00"),
                    "2d",
                    7,
                    6,
                    15,
                    "Check highlighted clauses in draft agreement",
                    "Zoom",
                    "https://calendar.google.com/calendar/u/0/r",
                    f"{DRIVE_ROOT}/Spire_CFCCT_Commercial_Services_Agreement_DRAFT.gdoc",
                    "📄 Open CFCCT Agreement DRAFT.gdoc",
                ),
                (
                    5,
                    "Notion — Spire & Selrok Command HQ",
                    "notion",
                    "Back-to-Back Strategy & Placement Onboarding Day (High Drain Alert)",
                    (now + timedelta(days=5)).strftime("%Y-%m-%d 09:30"),
                    (now + timedelta(days=5)).strftime("%Y-%m-%d 16:30"),
                    "1w",
                    9,
                    9,
                    30,
                    "Heavy social load detected — move 1 internal check-in to Thursday",
                    "Sheffield / Online",
                    "https://www.notion.so",
                    f"{DRIVE_ROOT}/Selrok & Spire Therapy - Operational Blueprint & Scale-Up Tracker.gsheet",
                    "📓 Open Operational Blueprint in Drive/Notion",
                ),
                (
                    1,
                    "Personal Gmail & Calendar",
                    "google",
                    "Quarterly Tax / Property & DSA Paperwork Deadline",
                    (now + timedelta(days=19)).strftime("%Y-%m-%d 09:00"),
                    (now + timedelta(days=19)).strftime("%Y-%m-%d 17:00"),
                    "1m",
                    8,
                    2,
                    15,
                    "Break into three 10-minute document gathering micro-sessions over 3 weeks",
                    "Home Office",
                    "https://calendar.google.com/calendar/u/0/r",
                    f"{DRIVE_ROOT}/sfe_dsa_continuing_students_form_2627_m.pdf",
                    "📑 Open DSA Continuing Students Form.pdf",
                ),
            ]
            for acc_id, label, prov, title, st, et, hor, cog, soc, buf, prep, loc, turl, lpath, tlabel in events:
                conn.execute(
                    """
                    INSERT INTO calendar_events (
                        account_id, account_label, provider, title, start_time, end_time,
                        horizon, cognitive_load, social_load, transition_buffer_mins,
                        prep_needed, location, target_url, local_file_path, target_label
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (acc_id, label, prov, title, st, et, hor, cog, soc, buf, prep, loc, turl, lpath, tlabel),
                )

            # 4. Seed 4-Horizon Proactive Suggestions with Direct Deep Links & 1-Click Auto-Complete
            suggestions = [
                (
                    "1d",
                    "Finalize & Send Master Funding Tracker Update (Daily Boss ⚔️)",
                    "You've opened this doc 3 times this week—knocking out the final 3 rows today clears your biggest mental open loop before your funding call.",
                    "Click '🚀 Open Funding Sheet & Auto-Complete' below: it opens your live Spire Funding Tracker right now and logs your +75 XP win in one move.",
                    json.dumps([
                        "Open Spire Funding Tracker (LIVE) tab",
                        "Update status badge on the top 2 schemes only",
                        "Paste the 3-bullet summary into the Notion Command Centre"
                    ]),
                    "Spire Google Drive + Notion HQ",
                    "steady",
                    1,
                    75,
                    "Today before 2:00 PM",
                    "https://docs.google.com/spreadsheets",
                    f"{DRIVE_ROOT}/Spire Funding Tracker (LIVE).gsheet",
                    "📊 Spire Funding Tracker (LIVE).gsheet",
                    "open_file",
                    "🚀 Open Funding Sheet & Auto-Complete (+75 XP)",
                ),
                (
                    "1d",
                    "Protect a 20-Minute Sensory Decompression Buffer After Supervision",
                    "Your supervision call has a high social load (8/10). Without a transition buffer, switching straight into admin often triggers afternoon executive crash.",
                    "Click '⚡ 1-Click Lock 20m Buffer' below—I'll block 15:00–15:20 on your calendar and mark this done immediately.",
                    json.dumps([
                        "Block 20 mins post-call on Google & Outlook calendars",
                        "Step away from screens and hydrate"
                    ]),
                    "Google Calendar + AuDHD Coach",
                    "low",
                    0,
                    20,
                    "Today • Energy Protection",
                    "https://calendar.google.com/calendar/u/0/r/eventedit?text=Sensory+Decompression+Buffer+(No+Screens)",
                    "",
                    "📅 Google & Outlook Calendar Buffer",
                    "calendar_buffer",
                    "⚡ 1-Click Lock 20m Buffer & Complete (+20 XP)",
                ),
                (
                    "1d",
                    "Approve 2 Pre-Written Email Replies in Triage Studio",
                    "Two people are waiting on quick confirmations. Both replies are already drafted for you—zero blank-page writing required.",
                    "Click '⚡ Jump to Pre-Written Replies' to hop straight to your drafts and send them in 1 click.",
                    json.dumps([
                        "Review pre-drafted reply to Sarah (Placement Pack)",
                        "Review pre-drafted reply to Keith (Property/Tax query)"
                    ]),
                    "Gmail + Outlook Triage",
                    "low",
                    0,
                    25,
                    "Today • 2-Minute Win",
                    "#inbox",
                    f"{DRIVE_ROOT}/Signed Placement Pack.pdf",
                    "✉️ Jump Straight to Triage Studio",
                    "jump_inbox",
                    "⚡ Jump to Pre-Written Replies & Send",
                ),
                (
                    "2d",
                    "Prep Tomorrow's MSc Seminar Without Reading the Whole Paper",
                    "Tomorrow at 2:00 PM you have MSc Case Formulation. Doing a 5-minute skim today prevents tomorrow morning's time-blindness rush.",
                    "Click below to open your MSc Distinctions Learning Guide directly from Google Drive and claim your +30 XP.",
                    json.dumps([
                        "Open MSc Distinctions Learning Guide",
                        "Jot down 3 bullet points in your Notion seminar page",
                        "Set out laptop charger & notebook tonight"
                    ]),
                    "University Outlook + Personal Notion",
                    "steady",
                    0,
                    30,
                    "Tomorrow (24–48h Horizon)",
                    "https://docs.google.com/document",
                    f"{DRIVE_ROOT}/MSc Integrative Therapy: Distinctions Learning Guide.gdoc",
                    "📘 MSc Integrative Therapy: Distinctions Learning Guide.gdoc",
                    "open_file",
                    "🚀 Open MSc Guide & Auto-Complete (+30 XP)",
                ),
                (
                    "2d",
                    "Pre-Check Highlighted Clauses in CFCCT Agreement",
                    "Meeting is in 48 hours. Checking the 2 liability clauses now gives you calm leverage instead of reading live on the call.",
                    "Click below to launch Spire_CFCCT_Commercial_Services_Agreement_DRAFT.gdoc directly on your Mac.",
                    json.dumps([
                        "Open Spire CFCCT Commercial Services Agreement",
                        "Check Section 4 liability wording",
                        "Mark ready for Thursday's call"
                    ]),
                    "Spire Google Workspace",
                    "steady",
                    0,
                    30,
                    "In 2 Days (48h Horizon)",
                    "https://docs.google.com/document",
                    f"{DRIVE_ROOT}/Spire_CFCCT_Commercial_Services_Agreement_DRAFT.gdoc",
                    "📄 Spire_CFCCT_Commercial_Services_Agreement_DRAFT.gdoc",
                    "open_file",
                    "🚀 Open CFCCT Agreement & Auto-Complete (+30 XP)",
                ),
                (
                    "1w",
                    "Rebalance Next Tuesday's 'Meeting Wall' (5 Calls Back-to-Back)",
                    "Next Tuesday has 9/10 social load across Outlook and Google Calendar. AuDHD pattern alert: days like this usually cause a 2-day recovery hangover.",
                    "Click '⚡ Auto-Send Polite Reschedule' to dispatch a pre-written move request for the internal check-in and complete this in 1 click.",
                    json.dumps([
                        "Review Tuesday's 5 stacked meetings",
                        "Send 1-click reschedule draft for internal check-in",
                        "Insert 45-min lunch & reset block at 12:30 PM"
                    ]),
                    "Multi-Calendar 7-Day Radar",
                    "low",
                    0,
                    35,
                    "Next Week (7-Day Horizon)",
                    "https://outlook.office.com/calendar/view/week",
                    "",
                    "📅 Outlook & Google Calendar Week View",
                    "inline_reschedule",
                    "⚡ Auto-Send Polite Reschedule & Rebalance (+35 XP)",
                ),
                (
                    "1m",
                    "De-Risk Next Month's Grant & DSA Paperwork Deadlines",
                    "Two major admin deadlines land in ~3 weeks. Deadlines 30 days out feel 'invisible' to ADHD time perception until they become a 48-hour panic.",
                    "Click below to open your DSA Continuing Students Form PDF right now so it's no longer an unopened mystery.",
                    json.dumps([
                        "Verify signed placement & insurance PDFs are in one folder",
                        "Schedule two 15-minute 'body-doubling' sprints over the next 2 weeks",
                        "Review draft UnLtd budget numbers"
                    ]),
                    "30-Day Horizon Radar + Notion",
                    "low",
                    0,
                    40,
                    "Next 30 Days (1-Month Horizon)",
                    "https://www.notion.so",
                    f"{DRIVE_ROOT}/sfe_dsa_continuing_students_form_2627_m.pdf",
                    "📑 sfe_dsa_continuing_students_form_2627_m.pdf",
                    "open_file",
                    "🚀 Open DSA Form PDF & Auto-Complete (+40 XP)",
                ),
            ]
            for hor, title, why, starter, steps, src, eng, boss, xp, due, turl, lpath, tlabel, act_type, act_label in suggestions:
                conn.execute(
                    """
                    INSERT INTO proactive_suggestions (
                        horizon, title, why_it_matters, starter_micro_step, micro_steps_json,
                        source_label, energy_required, is_daily_boss, xp_reward, due_context,
                        target_url, local_file_path, target_label, inline_action_type,
                        inline_action_label, is_cleared, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                    """,
                    (hor, title, why, starter, steps, src, eng, boss, xp, due, turl, lpath, tlabel, act_type, act_label, now.isoformat()),
                )

            # 5. Seed Multi-Inbox Email Triage with Deep Links & Linked Local Drive Files
            emails = [
                (
                    2,
                    "Spire Therapy Google Workspace",
                    "google",
                    "Sarah Jenkins (Placement Coordinator)",
                    "s.jenkins@partner-trust.org.uk",
                    "Updated Volunteer Handbook & Signed Placement Pack confirmation",
                    (now - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M"),
                    "action_required",
                    "Sarah just needs confirmation that the updated Safeguarding Policy & Placement Pack are ready for next week's cohort.",
                    "Confirm attachment & offer Tuesday 11am or Thursday 2pm for a 10-min onboarding check.",
                    "Hi Sarah,\n\nThanks so much for sending this over. Yes, I can confirm the updated Safeguarding Policy (2025-26) and Signed Placement Pack are finalized and ready for next week's cohort.\n\nIf helpful, I have a 15-minute window on Thursday at 2:00 PM for a quick onboarding check-in—let me know if that works for you.\n\nWarm regards,\nRob",
                    "warm_balanced",
                    "low",
                    25,
                    "https://mail.google.com/mail/u/0/#inbox",
                    f"{DRIVE_ROOT}/Signed Placement Pack.pdf",
                    "📎 Preview Signed Placement Pack.pdf",
                ),
                (
                    3,
                    "Outlook 365 — Consultancy & Practice",
                    "microsoft",
                    "Marcus Vance (Community Funding Panel)",
                    "m.vance@funding-futures.org.uk",
                    "Quick question on Spire CIC Scale-Up Tracker figures",
                    (now - timedelta(hours=4)).strftime("%Y-%m-%d %H:%M"),
                    "action_required",
                    "Marcus is excited about the Spire CIC proposal and wants to know if the projected clinical hours include volunteer counselors.",
                    "Clarify that the core model blends supervised placement counselors with clinical lead oversight.",
                    "Hi Marcus,\n\nGreat to hear from you, and thank you for the kind feedback on the proposal.\n\nTo clarify: yes, those projected delivery hours include our supervised placement practitioners working alongside our Clinical Director oversight model, which is how we keep community access sustainable at scale.\n\nHappy to walk through the breakdown on our call later today!\n\nBest,\nRob",
                    "warm_balanced",
                    "low",
                    25,
                    "https://outlook.office.com/mail/inbox",
                    f"{DRIVE_ROOT}/Selrok & Spire Therapy - Operational Blueprint & Scale-Up Tracker.gsheet",
                    "📊 Open Scale-Up Tracker.gsheet",
                ),
                (
                    4,
                    "University / MSc Outlook 365",
                    "microsoft",
                    "Dr. Helen Carter (MSc Module Lead)",
                    "h.carter@university.ac.uk",
                    "7CL501 Supervision Reflection Submission Window",
                    (now - timedelta(hours=7)).strftime("%Y-%m-%d %H:%M"),
                    "quick_read",
                    "FYI: Portal opens next Monday; Dr. Carter asks students to reply briefly confirming their chosen case study theme.",
                    "Reply in 1 sentence confirming your integrative therapy case theme.",
                    "Hi Dr. Carter,\n\nThanks for the heads-up—confirming I'll be focusing my reflection on integrative relational formulation and neurodivergent client pacing.\n\nBest wishes,\nRob",
                    "warm_balanced",
                    "low",
                    20,
                    "https://outlook.office.com/mail/inbox",
                    f"{DRIVE_ROOT}/Gemini Gems/7CL501 Module Handbook 2025-26 .docx",
                    "📘 Open 7CL501 Module Handbook.docx",
                ),
                (
                    1,
                    "Personal Gmail & Calendar",
                    "google",
                    "Keith Emmerson (Property & Accounts)",
                    "keith@emmerson-accounts.co.uk",
                    "Sheffield Property & Annual Statement Check",
                    (now - timedelta(days=1)).strftime("%Y-%m-%d %H:%M"),
                    "quick_read",
                    "Keith wants to know if any mortgage or insurance figures changed since last quarter before he prepares the draft summary.",
                    "Let him know Zurich liability was renewed and you'll send the PDF next week (keeps it off today's plate).",
                    "Hi Keith,\n\nThanks for checking in. Everything on the Sheffield property remains unchanged—the only new document is the renewed Zurich Combined Liability certificate, which I'll pop over to you early next week.\n\nBest,\nRob",
                    "warm_balanced",
                    "low",
                    20,
                    "https://mail.google.com/mail/u/0/#inbox",
                    f"{DRIVE_ROOT}/Mr_Rob_Knight-Strong26_Confirm_&_Certificate_Zurich_Combined_Liability.pdf",
                    "📄 Open Zurich Certificate.pdf",
                ),
            ]
            for acc_id, label, prov, s_name, s_email, subj, rec, urg, brief, need, draft, tone, eng, xp, turl, lpath, alabel in emails:
                conn.execute(
                    """
                    INSERT INTO triaged_emails (
                        account_id, account_label, provider, sender_name, sender_email,
                        subject, received_at, urgency, one_line_brief, what_they_need,
                        draft_reply, draft_tone, energy_required, xp_reward, status,
                        target_url, local_file_path, attachment_label
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)
                    """,
                    (acc_id, label, prov, s_name, s_email, subj, rec, urg, brief, need, draft, tone, eng, xp, turl, lpath, alabel),
                )

            # 6. Seed "Shiny Object" Idea Sandbox
            ideas = [
                (
                    "AI-Assisted 'Walking Therapy' Audio Reflection Companion for Outdoor Sessions",
                    "What if clients doing outdoor/sporting walk-and-talk therapy got a privacy-first voice reflection prompt after sessions that maps mood shifts to movement?",
                    "Spire / Clinical Innovation",
                    "dossier_ready",
                    86,
                    "Low (Parked safely for Q2)",
                    "2-Week Prototype",
                    json.dumps({
                        "core_thesis": "A post-session guided voice note tool for outdoor/active therapy clients that captures insights while movement endorphins are still active, without recording the therapy session itself.",
                        "why_its_exciting": "Directly connects your Sporting Minds / outdoor counselling research with Selrok's scalable tech vision.",
                        "reality_check": "Clinical GDPR & safeguarding compliance means it should NEVER record live clinical sessions—keep it strictly as a client-owned post-walk 2-minute reflection journal.",
                        "priority_guardrail": "🔥 High Potential, DO NOT build this week. Keep focus on Spire CIC core funding first; revisit after current grant round closes.",
                        "micro_experiments": [
                            "Ask 2 supervision peers if clients forget insights after walk-and-talk sessions",
                            "Test a 3-question voice-memo prompt template on Notion",
                            "Add as an innovation bullet in the UnLtd Grant Appendix (0 extra build time!)"
                        ],
                        "researched_by": "Gemini 2.5 + Claude Sonnet Sandbox Agent"
                    }),
                ),
                (
                    "Neurodivergent 'Reverse Job Board' Where Employers Pitch Their Sensory & Flex Culture",
                    "Instead of AuDHD candidates masking through 5 rounds of interviews, companies have to publish their actual meeting load, async culture, and sensory environment.",
                    "Wild Spark / Social Enterprise",
                    "dossier_ready",
                    78,
                    "High Distraction Risk if started now!",
                    "Full Standalone Venture",
                    json.dumps({
                        "core_thesis": "Flip the hiring script for neurodivergent talent by auditing and scoring employers on cognitive ergonomics, async communication, and psychological safety.",
                        "why_its_exciting": "High emotional resonance and clear gap in UK workplace inclusion market.",
                        "reality_check": "Two-sided marketplaces require heavy B2B sales bandwidth. Spinning this up now would directly cannibalize your Spire Therapy & MSc spoons.",
                        "priority_guardrail": "🛑 Park in Long-Term Vault. Great concept, zero urgency today. Your agent has saved the full business model canvas in Notion so you won't lose a single detail.",
                        "micro_experiments": [
                            "Save domain ideas in Notion Idea Vault",
                            "Use the 'Sensory & Cognitive Load Audit' framework internally for Spire volunteers first",
                            "Re-evaluate in 6 months"
                        ],
                        "researched_by": "Gemini 2.5 + Claude Sonnet Sandbox Agent"
                    }),
                ),
            ]
            for title, spark, cat, status, score, risk, effort, dossier in ideas:
                conn.execute(
                    """
                    INSERT INTO idea_sandbox (
                        title, raw_spark, category, status, viability_score,
                        distraction_risk, effort_estimate, dossier_json, xp_awarded,
                        synced_to_notion, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 25, 1, ?, ?)
                    """,
                    (title, spark, cat, status, score, effort, risk, dossier, now.isoformat(), now.isoformat()),
                )

            # 7. Seed Cleared & Accomplished Vault
            vault_items = [
                (
                    "boss_defeated",
                    "Completed Spire Master Funding Reference Scheme Status Rollup",
                    "Merged Oct 14 & Oct 21 funding updates into live master tracker",
                    "Spire Therapy Google Workspace",
                    "1d",
                    75,
                    1,
                    "https://docs.google.com/document",
                    f"{DRIVE_ROOT}/Spire_Master_Funding_Reference.gdoc",
                    "📄 Open Spire_Master_Funding_Reference.gdoc",
                    (now - timedelta(hours=3)).isoformat(),
                ),
                (
                    "idea_parked",
                    "Parked Idea: 'Walking Therapy Audio Companion' (+Focus Protected!)",
                    "Captured idea in 20 seconds and returned immediately to funding prep",
                    "Idea Sandbox",
                    "1d",
                    25,
                    0,
                    "#sandbox",
                    "",
                    "💡 View in Idea Sandbox",
                    (now - timedelta(hours=5)).isoformat(),
                ),
                (
                    "email_sent",
                    "Sent Board Meeting 1 Summary & Action Notes to Trustees",
                    "Approved and sent proactive draft across Spire Workspace",
                    "Spire Therapy Google Workspace",
                    "1w",
                    30,
                    0,
                    "https://docs.google.com/document",
                    f"{DRIVE_ROOT}/Spire_Board_Meeting_1_Summary.gdoc",
                    "📄 Open Spire_Board_Meeting_1_Summary.gdoc",
                    (now - timedelta(days=2)).isoformat(),
                ),
                (
                    "horizon_prep",
                    "Finalized Safeguarding Policy 2025-26 & Volunteer Code of Conduct",
                    "Completed 1-week ahead of placement onboarding deadline",
                    "Notion — Spire & Selrok Command HQ",
                    "1w",
                    50,
                    1,
                    "https://www.notion.so",
                    f"{DRIVE_ROOT}/SAFEGUARDING POLICY 2025-26.pdf",
                    "📄 Open SAFEGUARDING POLICY 2025-26.pdf",
                    (now - timedelta(days=4)).isoformat(),
                ),
                (
                    "horizon_prep",
                    "Submitted Clinical Director Role Specification Draft",
                    "Completed via 3 micro-step sprints",
                    "Spire Therapy Google Workspace",
                    "1m",
                    60,
                    1,
                    "https://docs.google.com/document",
                    f"{DRIVE_ROOT}/Spire Therapy CIC Clinical Director role specification (DRAFT).gdoc",
                    "📄 Open Clinical Director Spec.gdoc",
                    (now - timedelta(days=18)).isoformat(),
                ),
                (
                    "notion_task",
                    "Completed Selrok & Spire Operational Blueprint v0.2",
                    "Major strategic architecture milestone completed this year",
                    "Notion — Spire & Selrok Command HQ",
                    "1m",
                    100,
                    1,
                    "https://www.notion.so",
                    f"{DRIVE_ROOT}/Selrok & Spire Therapy - Operational Blueprint & Scale-Up Tracker.gsheet",
                    "📊 Open Operational Blueprint.gsheet",
                    (now - timedelta(days=60)).isoformat(),
                ),
                (
                    "horizon_prep",
                    "Renewed Zurich Combined Liability Confirmation & Certificate",
                    "Cleared admin ahead of renewal date",
                    "Personal Gmail & Calendar",
                    "1m",
                    45,
                    0,
                    "https://mail.google.com/mail/u/0/#inbox",
                    f"{DRIVE_ROOT}/Mr_Rob_Knight-Strong26_Confirm_&_Certificate_Zurich_Combined_Liability.pdf",
                    "📄 Open Zurich Certificate.pdf",
                    (now - timedelta(days=120)).isoformat(),
                ),
            ]
            for itype, title, summ, acc, hor, xp, boss, turl, lpath, tlabel, cat_time in vault_items:
                conn.execute(
                    """
                    INSERT INTO cleared_vault (
                        item_type, title, summary, account_label, horizon_tag,
                        xp_earned, was_boss, synced_to_notion, target_url,
                        local_file_path, target_label, cleared_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
                    """,
                    (itype, title, summ, acc, hor, xp, boss, turl, lpath, tlabel, cat_time),
                )

            # 8. Seed initial welcoming message from the AuDHD Coach
            conn.execute(
                """
                INSERT INTO coach_messages (role, content, energy_mode, created_at)
                VALUES (
                    'coach',
                    'Hey Rob 👋 I''ve scanned your Google, Outlook, and Notion workspaces. Every single item on your dashboard is now **directly linked** to the real file, email, or calendar event—and you can click **🚀 Open & Auto-Complete** so you never have to hunt for a file or remember to come back and tick a box!',
                    'steady',
                    ?
                )
                """,
                (now.isoformat(),),
            )
