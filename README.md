# Sanctuary • 24/7 AuDHD Personal Assistant, Executive Function Coach & Idea Incubator

Sanctuary is a neurodivergent-first Personal Assistant designed specifically for **ADHD & AuDHD brains**. It lives safely in your **Google Drive** (`My Drive/AuDHD-Assistant`) so you never lose access when switching laptops, and deploys with one command to run **24/7 in the cloud** (Railway, Render, or Google Cloud Run).

## Core Capabilities

1. **Multi-Account Connectors**:
   - Multiple **Google** accounts (Gmail + Google Calendar)
   - Multiple **Microsoft 365 / Outlook** accounts (Mail + Calendar via Microsoft Graph)
   - Multiple **Notion Workspaces** (Tasks, Daily Command Centre, Idea Incubator, and Cleared Archive)
2. **Proactive 4-Horizon Radar (`1-Day`, `2-Day`, `1-Week`, `1-Month`)**:
   - Externalizes time blindness by flagging upcoming meetings, missing prep blocks, sensory/social overload days, and 30-day deadlines before they become last-minute crises.
3. **Email Triage & Proactive Draft Studio**:
   - Filters inbox noise, summarizes what each sender actually needs in **1 calm sentence**, and pre-writes replies in your voice with 1-click tone shifters (*⚡ Shorter*, *💛 Warmer*, *🛡️ Polite Boundary / Next Week*).
4. **Minimalistic, Shame-Free Gamification**:
   - **Daily Boss Battles (3× XP)** for the #1 task you're procrastinating on.
   - **60-Second Quick-Win Roulette** to break executive paralysis instantly.
   - **Grace Shields in Low-Spoons Mode** (+20 XP for self-regulation; hides 80% of non-urgent clutter and protects your streak).
5. **The "Shiny Object" Idea Sandbox & Autonomous Incubator Agent**:
   - Park your weird and wonderful ideas in 10 seconds to earn **+25 XP (Focus Protected!)** while a background AI agent (**Google Gemini + Anthropic Claude**) researches viability, Devil's Advocate pitfalls, and 3 micro-experiments for your free time.
6. **The Accomplishment & Cleared Vault (`Day / Week / Month / Year`)**:
   - Cures ADHD "productivity amnesia" by archiving every cleared email, defeated Boss, and parked idea with lookback filters and bi-directional Notion sync.

---

## Quick Start (Local or Laptop Switch)

Zero installation or virtual-environment setup is required—runs out of the box on macOS:

```bash
chmod +x start.sh
./start.sh
```

Then open **http://localhost:8765** in your browser.

---

## 24/7 Cloud Deployment (Run Even When Your Mac Is Closed)

- **Railway**: Connect repo or run `railway up` (uses `railway.json` & `Dockerfile`).
- **Render**: Connect repo as a Blueprint (uses `render.yaml`).
- **Google Cloud Run**: Run `./deploy_cloud_run.sh`.
- **Cloud Cron Trigger**: Point any cloud cron scheduler at `POST /api/cron/daily-briefing` to auto-generate your morning briefing and sync your Notion Command Centre every morning at `07:30`.
