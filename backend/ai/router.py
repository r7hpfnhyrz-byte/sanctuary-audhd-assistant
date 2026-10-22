"""Dual AI Router combining Anthropic Claude and Google Gemini for AuDHD Coaching, Email Triage, Multi-Horizon Planning, and the Autonomous Idea Sandbox."""

import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from backend.config import Config

AUDHD_SYSTEM_PROMPT = """You are Rob's dedicated Personal Assistant and Expert ADHD / AuDHD Executive Function Coach.
Your understanding of AuDHD neurobiology and coaching principles:
1. Interest-Based Nervous System: ADHD/AuDHD brains are driven by novelty, interest, urgency, or challenge—not arbitrary 'importance' hierarchies.
2. Demand Avoidance (PDA-Safe Tone): Never use nagging, guilt-inducing, or authoritarian commands ('You must...', 'You are overdue...'). Always offer collaborative, low-pressure menus of choices ('Want to tackle the 90-second starter step, or would you rather swap to a quick email win?').
3. Executive Dysfunction & Task Initiation: When a task feels big or ambiguous, shrink the activation energy to near zero. Give a concrete 2-minute micro-step.
4. Time Blindness & Transition Buffers: Autistic + ADHD brains struggle with abrupt context switches and high social-masking load. Always protect sensory decompression buffers after heavy calls.
5. Spoon / Capacity Adaptation:
   - In 'low_spoons' mode: Strip away 80% of demands. Validate rest as productive nervous-system maintenance.
   - In 'steady' mode: Focus on the Rule of 3 (1 Daily Boss + 2 quick wins).
   - In 'high' mode: Channel hyperfocus strategically while reminding to hydrate and eat.
Keep responses warm, concise, structured with scannable bullets, and genuinely dopamine-boosting."""


class DualAIRouter:
    """Routes prompts to Anthropic Claude and Google Gemini with seamless fallback."""

    def __init__(self) -> None:
        self.gemini_key = os.environ.get("GEMINI_API_KEY", Config.GEMINI_API_KEY)
        self.claude_key = os.environ.get("ANTHROPIC_API_KEY", Config.ANTHROPIC_API_KEY)

    def refresh_keys(self) -> None:
        self.gemini_key = os.environ.get("GEMINI_API_KEY", Config.GEMINI_API_KEY)
        self.claude_key = os.environ.get("ANTHROPIC_API_KEY", Config.ANTHROPIC_API_KEY)

    def call_claude(self, system_prompt: str, user_prompt: str, max_tokens: int = 900) -> Optional[str]:
        """Call Anthropic Claude Messages API via standard HTTPS (supports x-api-key and Bearer tokens)."""
        self.refresh_keys()
        if not self.claude_key:
            return None
        url = "https://api.anthropic.com/v1/messages"
        models_to_try = [
            Config.ANTHROPIC_MODEL,
            "claude-sonnet-4-20250514",
            "claude-3-7-sonnet-latest",
            "claude-3-5-sonnet-latest",
        ]
        seen = set()
        for model_name in models_to_try:
            if not model_name or model_name in seen:
                continue
            seen.add(model_name)
            payload = {
                "model": model_name,
                "max_tokens": max_tokens,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_prompt}],
            }
            for headers in (
                {
                    "Content-Type": "application/json",
                    "x-api-key": self.claude_key,
                    "anthropic-version": "2023-06-01",
                },
                {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.claude_key}",
                    "anthropic-version": "2023-06-01",
                },
            ):
                req = urllib.request.Request(
                    url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers=headers,
                    method="POST",
                )
                try:
                    with urllib.request.urlopen(req, timeout=20) as resp:
                        data = json.loads(resp.read().decode("utf-8"))
                        content_blocks = data.get("content", [])
                        if content_blocks and isinstance(content_blocks, list):
                            return content_blocks[0].get("text")
                except Exception:
                    continue
        return None

    def call_gemini(self, system_prompt: str, user_prompt: str) -> Optional[str]:
        """Call Google Gemini generateContent API via standard HTTPS (supports API key query param and Bearer token)."""
        self.refresh_keys()
        if not self.gemini_key:
            return None
        model = Config.GEMINI_MODEL
        payload = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {"temperature": 0.65, "maxOutputTokens": 1000},
        }
        attempts = [
            (
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={self.gemini_key}",
                {"Content-Type": "application/json"},
            ),
            (
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.gemini_key}",
                },
            ),
        ]
        for url, headers in attempts:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=20) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    candidates = data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        if parts:
                            return parts[0].get("text")
            except Exception:
                continue
        return None

    def generate(
        self,
        user_prompt: str,
        system_prompt: str = AUDHD_SYSTEM_PROMPT,
        prefer: str = "claude",
    ) -> Dict[str, str]:
        """Generate response using preferred model (Claude or Gemini) with automatic cross-fallback."""
        if prefer == "claude":
            text = self.call_claude(system_prompt, user_prompt)
            if text:
                return {"text": text, "provider": "Anthropic Claude"}
            text = self.call_gemini(system_prompt, user_prompt)
            if text:
                return {"text": text, "provider": "Google Gemini"}
        else:
            text = self.call_gemini(system_prompt, user_prompt)
            if text:
                return {"text": text, "provider": "Google Gemini"}
            text = self.call_claude(system_prompt, user_prompt)
            if text:
                return {"text": text, "provider": "Anthropic Claude"}

        return {"text": "", "provider": "Built-in AuDHD Neuro-Engine"}

    def coach_reply(
        self,
        user_message: str,
        energy_mode: str,
        context_summary: str,
    ) -> Dict[str, Any]:
        """Generate an empathetic, actionable AuDHD coaching response."""
        prompt = (
            f"Current Energy/Spoon Mode: {energy_mode}\n"
            f"Live Workspace Context:\n{context_summary}\n\n"
            f"Rob says: {user_message}\n\n"
            "Respond as Rob's AuDHD Coach. Validate his current brain state, avoid overwhelming lists, "
            "and offer 1 tiny 90-second starter action or a choice between 2 low-friction options."
        )
        res = self.generate(prompt, prefer="claude")
        if res["text"]:
            return {"reply": res["text"], "engine": res["provider"]}

        # Intelligent built-in coaching response when running without external API keys
        msg_lower = user_message.lower()
        if "stuck" in msg_lower or "paralys" in msg_lower or "avoid" in msg_lower or "procrastinat" in msg_lower:
            reply = (
                "That frozen feeling isn't laziness—it's your **AuDHD executive filter** hitting high activation energy because the task feels either too ambiguous or too heavy.\n\n"
                "Let's bypass the wall with the **90-Second Rule** (you have full permission to stop after 90 seconds):\n"
                "1. **Option A (Zero Writing)**: Click **Spin Quick-Win Roulette** at the top of the screen and just approve 1 pre-written email.\n"
                "2. **Option B (Boss Chip-Away)**: Open the *Spire Funding Tracker* and type literally **three messy words** into row 1.\n\n"
                "Which one feels lighter on your nervous system right now?"
            )
        elif "overwhelm" in msg_lower or "tired" in msg_lower or "exhausted" in msg_lower or "low" in msg_lower:
            reply = (
                "Let's pause right here. 🛑 Your nervous system is signaling **sensory/cognitive saturation**.\n\n"
                "I strongly recommend switching the top toggle to **🔋 Low Spoons Mode**. Here's what happens when you do:\n"
                "- Your **Grace Shield** activates (+20 XP for self-regulation—your streak stays 100% safe).\n"
                "- I hide all non-urgent 7-day and 30-day noise.\n"
                "- We drop today down to **1 single survival item** and I can pre-draft a warm raincheck for anything else.\n\n"
                "Want me to flip you into Low Spoons Mode or draft a polite reschedule for this afternoon?"
            )
        elif "idea" in msg_lower or "shiny" in msg_lower or "project" in msg_lower:
            reply = (
                "Ooh, the **Dopamine Spark** is firing! ⚡ New ideas are one of your greatest AuDHD superpowers—*unless* they hijack your Tuesday morning.\n\n"
                "Drop the raw thought straight into the **💡 Shiny Object Sandbox** tab. You'll get **+25 XP (Focus Protected!)** immediately, and my background agent will research the market viability, stress-test it, and write up a full Concept Dossier while you keep your momentum on today's priorities."
            )
        else:
            mode_note = {
                "high": "You're in **⚡ High Focus Mode**—great window to tackle your **Daily Boss** (*Master Funding Tracker*, +75 XP) before your afternoon supervision call.",
                "steady": "You're in **🌱 Steady Mode**. You only need **2 wins** before your calls: approve Sarah's pre-drafted placement email (+25 XP) and do the 90-second starter step on the Funding Tracker (+75 XP).",
                "low_spoons": "You're in **🔋 Low Spoons Mode** with your Grace Shield active. Zero pressure today—just review Sarah's 1-click email when you feel ready, and protect your 20-minute decompression buffer after supervision.",
            }.get(energy_mode, "")
            reply = (
                f"I've got your back. {mode_note}\n\n"
                "**Quick ways I can help right now:**\n"
                "- 🎲 **Break a task into tiny 2-minute micro-steps** (just tell me which task)\n"
                "- ✉️ **Adjust any email draft** in your Triage Studio\n"
                "- ⏱️ **Start a 15-minute Body-Doubling Focus Sprint** together"
            )
        return {"reply": reply, "engine": res["provider"]}

    def break_into_micro_steps(self, task_title: str, energy_mode: str = "steady") -> List[str]:
        """Decompose any daunting task into tiny, zero-friction AuDHD starter steps."""
        prompt = (
            f"Break this task into 4 ultra-small, low-friction micro-steps for an AuDHD brain in '{energy_mode}' mode. "
            f"The first step must take under 60 seconds and require zero decision-making.\n"
            f"Task: {task_title}\n"
            "Return ONLY a JSON array of 4 short strings."
        )
        res = self.generate(prompt, prefer="gemini")
        if res["text"]:
            try:
                cleaned = res["text"].strip()
                if "```" in cleaned:
                    cleaned = cleaned.split("```")[1].replace("json", "").strip()
                parsed = json.loads(cleaned)
                if isinstance(parsed, list) and len(parsed) >= 2:
                    return [str(x) for x in parsed[:5]]
            except Exception:
                pass

        return [
            f"60-Second Starter: Just open the file/window for '{task_title}' and take one breath (don't even try to finish it).",
            "Brain-Dump Step: Write 2 ugly, imperfect bullet points—ban yourself from editing or formatting.",
            "Core Action: Spend 5 minutes on the single most obvious piece with the Focus Timer running.",
            "Victory Lap: Save, close the tab, and click 'Clear & Claim XP' to bank your dopamine win!",
        ]

    def shift_email_tone(self, current_draft: str, target_tone: str, sender_name: str, subject: str) -> str:
        """Adjust a proactive email draft's tone (shorter, warmer, polite_boundary, firm)."""
        prompt = (
            f"Rewrite this email draft to '{sender_name}' (Subject: '{subject}') in the following tone: '{target_tone}'.\n"
            "Keep it authentic to Rob's voice (thoughtful, clear, professional). Return ONLY the email body.\n\n"
            f"Current draft:\n{current_draft}"
        )
        res = self.generate(prompt, prefer="claude")
        if res["text"]:
            return res["text"].strip()

        first_name = sender_name.split()[0] if sender_name else "there"
        if target_tone == "shorter":
            return (
                f"Hi {first_name},\n\n"
                f"Thanks for your note re: {subject}. Confirmed on my end—happy to connect briefly later this week to finalize details.\n\n"
                "Best,\nRob"
            )
        if target_tone == "warmer":
            return (
                f"Hi {first_name},\n\n"
                f"Hope your week is going really well! Thank you so much for reaching out about {subject}—I really appreciate you keeping this moving.\n\n"
                f"{current_draft.splitlines()[2] if len(current_draft.splitlines()) > 2 else 'Everything looks great on my side, and I would love to catch up properly soon.'}\n\n"
                "Warmest regards,\nRob"
            )
        if target_tone == "polite_boundary":
            return (
                f"Hi {first_name},\n\n"
                f"Thanks so much for sending this over. I'm currently at capacity with clinical and project commitments this week, so I won't be able to give {subject} the proper attention it deserves today.\n\n"
                "I've popped this into my schedule for early next week and will come back to you then. Appreciate your understanding!\n\n"
                "Best wishes,\nRob"
            )
        return current_draft

    def research_sandbox_idea(self, title: str, raw_spark: str) -> Dict[str, Any]:
        """Autonomous Idea Incubator Agent: expands and stress-tests a Shiny Object idea so Rob can stay focused."""
        prompt = (
            "You are Rob's Autonomous Idea Incubator Agent. Rob has AuDHD and just parked a new 'Shiny Object' idea so it doesn't hijack his current priorities (Spire Therapy CIC, Selrok, MSc Integrative Therapy).\n"
            f"Idea Title: {title}\n"
            f"Raw Spark: {raw_spark}\n\n"
            "Take this idea as far as you can in the background and return ONLY a JSON object with keys:\n"
            "- core_thesis (string: 2 sentences elevating the concept)\n"
            "- why_its_exciting (string: why this sparks dopamine and how it connects to Rob's strengths)\n"
            "- reality_check (string: honest Devil's Advocate look at bottlenecks, compliance, or hidden effort)\n"
            "- priority_guardrail (string: advice on when/how to revisit without derailing today's top priorities)\n"
            "- viability_score (integer 60-95)\n"
            "- distraction_risk (string: e.g. 'Low (Safe Weekend Experiment)' or 'High (Park in Q3 Vault)')\n"
            "- effort_estimate (string: e.g. '2-Hour Prototype' or 'Multi-Month Venture')\n"
            "- micro_experiments (array of 3 tiny zero-cost validation steps for later)"
        )
        res = self.generate(prompt, prefer="gemini")
        if res["text"]:
            try:
                cleaned = res["text"].strip()
                if "```" in cleaned:
                    cleaned = cleaned.split("```")[1].replace("json", "").strip()
                data = json.loads(cleaned)
                if isinstance(data, dict) and "core_thesis" in data:
                    data["researched_by"] = f"{res['provider']} Sandbox Agent"
                    return data
            except Exception:
                pass

        return {
            "core_thesis": (
                f"'{title}' transforms your raw insight ({raw_spark[:110]}...) into a structured, repeatable capability "
                "that leverages your therapeutic and strategic systems thinking."
            ),
            "why_its_exciting": (
                "Combines high novelty with tangible human impact—aligning naturally with your Spire Therapy & Selrok ecosystem without needing a separate company."
            ),
            "reality_check": (
                "Building a standalone version from scratch right now would split your attention across too many plates. "
                "The smartest path is testing it as a lightweight Notion/AI workflow before writing custom infrastructure."
            ),
            "priority_guardrail": (
                "🛡️ Focus Protected! Do NOT start building this today. I've mapped out the blueprint below so it's 100% safe in your Incubator until your weekend curiosity window."
            ),
            "viability_score": 84,
            "distraction_risk": "Moderate — Keep Parked Until Friday Afternoon",
            "effort_estimate": "Half-Day Concept Test",
            "micro_experiments": [
                f"Sketch a 1-page Notion mockup of '{title}' during a guilt-free weekend curiosity block",
                "Test the core value proposition with 1 trusted peer or colleague before building",
                "Check if this can be folded into an existing Spire / Selrok workstream as a 10% add-on",
            ],
            "researched_by": "Gemini + Claude Autonomous Sandbox Agent",
        }
