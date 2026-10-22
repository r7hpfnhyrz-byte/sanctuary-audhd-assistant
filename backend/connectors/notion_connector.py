"""Multi-workspace Notion Connector for reading tasks and syncing the Daily Command Centre, Idea Incubator, and Cleared Archive."""

import json
import os
import urllib.request
from datetime import datetime
from typing import Any, Dict, List, Optional

from backend.config import Config


class NotionWorkspaceConnector:
    """Bi-directional Notion API v1 integration across multiple Notion workspaces."""

    NOTION_VERSION = "2022-06-28"

    @classmethod
    def _discover_first_parent(cls, notion_token: str) -> Optional[Dict[str, str]]:
        """Auto-discover the first accessible page or database shared with the integration."""
        url = "https://api.notion.com/v1/search"
        req = urllib.request.Request(
            url,
            data=json.dumps({"page_size": 10}).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {notion_token}",
                "Notion-Version": cls.NOTION_VERSION,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                results = data.get("results", [])
                for r in results:
                    if r.get("object") == "page":
                        return {"type": "page_id", "id": r["id"], "url": r.get("url", "")}
                for r in results:
                    if r.get("object") == "database":
                        return {"type": "database_id", "id": r["id"], "url": r.get("url", "")}
        except Exception:
            return None
        return None

    @classmethod
    def sync_command_centre_and_vault(
        cls,
        credentials: Dict[str, Any],
        briefing_summary: Dict[str, Any],
        cleared_items: List[Dict[str, Any]],
        sandbox_ideas: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Push Daily Briefing, Accomplishment Vault items, and Idea Sandbox dossiers to Notion."""
        notion_token = (
            credentials.get("api_token")
            or credentials.get("access_token")
            or os.environ.get("NOTION_API_KEY", Config.NOTION_API_KEY)
        )
        database_id = credentials.get("database_id")

        sync_manifest: Dict[str, Any] = {
            "synced_at": datetime.now().isoformat(),
            "command_centre_blocks": {
                "energy_mode": briefing_summary.get("energy_mode", "steady"),
                "daily_boss": briefing_summary.get("daily_boss_title", ""),
                "top_priorities_count": len(briefing_summary.get("today_priorities", [])),
            },
            "vault_records_synced": len(cleared_items),
            "idea_dossiers_synced": len(sandbox_ideas),
        }

        if not notion_token:
            sync_manifest["mode"] = "local_and_ready_for_notion_token"
            return sync_manifest

        parent_spec: Optional[Dict[str, str]] = None
        if database_id:
            parent_spec = {"database_id": database_id}
        else:
            discovered = cls._discover_first_parent(notion_token)
            if discovered:
                parent_spec = {discovered["type"]: discovered["id"]}

        if not parent_spec:
            sync_manifest["mode"] = "notion_token_valid_awaiting_shared_page"
            sync_manifest["note"] = (
                "Notion API key is connected! In Notion, click '...' on any page → 'Connect to' → select your Integration so Sanctuary can write pages there."
            )
            return sync_manifest

        children_blocks = [
            {
                "object": "block",
                "type": "heading_2",
                "heading_2": {
                    "rich_text": [{"type": "text", "text": {"content": "🏆 Recent Accomplishment Vault Wins"}}]
                },
            }
        ]
        for item in cleared_items[:8]:
            children_blocks.append(
                {
                    "object": "block",
                    "type": "bulleted_list_item",
                    "bulleted_list_item": {
                        "rich_text": [
                            {
                                "type": "text",
                                "text": {
                                    "content": f"[+{item.get('xp_earned', 20)} XP] {item.get('title', '')} ({item.get('cleared_at', '')[:10]})"
                                },
                            }
                        ]
                    },
                }
            )

        children_blocks.append(
            {
                "object": "block",
                "type": "heading_2",
                "heading_2": {
                    "rich_text": [{"type": "text", "text": {"content": "💡 Shiny Object Idea Incubator Dossiers"}}]
                },
            }
        )
        for idea in sandbox_ideas[:5]:
            children_blocks.append(
                {
                    "object": "block",
                    "type": "bulleted_list_item",
                    "bulleted_list_item": {
                        "rich_text": [
                            {
                                "type": "text",
                                "text": {
                                    "content": f"{idea.get('title', '')} — Viability {idea.get('viability_score', 80)}/100 ({idea.get('distraction_risk', '')})"
                                },
                            }
                        ]
                    },
                }
            )

        url = "https://api.notion.com/v1/pages"
        title_prop_key = "Name" if "database_id" in parent_spec else "title"
        payload = {
            "parent": parent_spec,
            "properties": {
                title_prop_key: {
                    "title": [
                        {
                            "text": {
                                "content": f"Sanctuary AuDHD Briefing & Vault — {datetime.now().strftime('%Y-%m-%d %H:%M')}"
                            }
                        }
                    ]
                }
            },
            "children": children_blocks,
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {notion_token}",
                "Notion-Version": cls.NOTION_VERSION,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                sync_manifest["mode"] = "live_notion_api"
                sync_manifest["page_id"] = data.get("id")
                sync_manifest["page_url"] = data.get("url", "https://www.notion.so")
                return sync_manifest
        except Exception as exc:
            sync_manifest["mode"] = "notion_api_warning"
            sync_manifest["warning"] = str(exc)
            return sync_manifest
