"""
Slack Bolt event and action handlers.

Bridges Slack events to the orchestrator layer.
Routes incoming messages, button clicks, and modals.
"""

import logging
import sys
import re
from typing import Dict, Any, Optional
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.orchestrator.orchestrator import Orchestrator

logger = logging.getLogger(__name__)


class SlackHandler:
    """Slack event/action handler wrapper."""

    def __init__(self):
        """Initialize Slack Bolt app and register handlers."""
        logger.info("Initializing SlackHandler")
        self.orchestrator = Orchestrator()
        
        # TODO: Initialize Slack Bolt app
        # from slack_bolt import App
        # self.app = App(
        #     token=os.getenv("SLACK_BOT_TOKEN"),
        #     signing_secret=os.getenv("SLACK_SIGNING_SECRET"),
        #     app_token=os.getenv("SLACK_APP_TOKEN")
        # )
        # self.register_handlers()

    def register_handlers(self):
        """Register event and action handlers with Slack Bolt app."""
        # TODO: Register handlers
        # @self.app.message(".*")
        # def handle_message(message, say):
        #     pass
        pass

    def handle_dm_message(self, user_id: str, text: str) -> Dict[str, Any]:
        """
        Handle direct message from a user.
        
        This is the main entry point for user requests.
        
        Args:
            user_id: Slack user ID (usually starts with 'U')
            text: Raw message text from user
        
        Returns:
            {
                "ack": True,
                "request_id": "550e8400-e29b-41d4-a716-446655440000",
                "status": "RECEIVED"
            }
        """
        logger.info(f"DM received from {user_id}: {text[:50]}...")
        
        # TODO: Validate user_id against user_profiles table
        # TODO: Call orchestrator.receive_request(user_id, tenant_id, text)
        # TODO: Send immediate DM acknowledgment
        # TODO: Create parent message in orchestration channel
        
        if not user_id or not text:
            return {"ack": False, "error": "invalid_dm_payload"}

        result = self.orchestrator.receive_request(
            user_id=user_id,
            tenant_id="DEFAULT",
            raw_text=text,
        )

        return {
            "ack": True,
            "request_id": result["request_id"],
            "status": result["status"],
            "trace_id": result["trace_id"],
        }

    def handle_button_action(
        self,
        action_type: str,
        user_id: str,
        payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Handle button clicks: approve, request_revision, cancel.
        
        Args:
            action_type: "approve" | "request_revision" | "cancel"
            user_id: Slack user ID who clicked
            payload: Full button payload from Slack
        
        Returns:
            {"ack": True, "result": "..."}
        """
        logger.info(f"Button action from {user_id}: {action_type}")
        
        request_id = payload.get("request_id") or _extract_request_id(payload)
        if not request_id:
            return {"ack": False, "error": "missing_request_id"}

        action_map = {
            "approve": "APPROVED",
            "request_revision": "REJECTED",
            "cancel": "CANCELED",
            "approved": "APPROVED",
            "rejected": "REJECTED",
            "canceled": "CANCELED",
        }
        normalized = action_map.get(action_type.lower(), action_type.upper())

        ok = self.orchestrator.handle_approval(
            request_id=request_id,
            action=normalized,
            approved_by=user_id,
        )
        if not ok:
            return {"ack": False, "error": "approval_failed"}

        status = self.orchestrator.get_request_status(request_id)
        return {
            "ack": True,
            "result": normalized,
            "request_id": request_id,
            "status": status.get("status") if status else None,
        }

    def handle_app_mention(self, user_id: str, text: str) -> Dict[str, Any]:
        """
        Handle app mention (@bot) in channels.
        
        Can be used for help messages, status queries, etc.
        
        Args:
            user_id: User who mentioned the bot
            text: Message text
        
        Returns:
            {"ack": True, "channel_message": "..."}
        """
        logger.info(f"App mention from {user_id}: {text[:50]}...")
        normalized = (text or "").strip().lower()
        mentioned_user_ids = self._extract_additional_mentions(text)
        question_text = self._strip_leading_mention(text)

        if "help" in normalized:
            return {
                "ack": True,
                "channel_message": "Try: 'status <request_id>' or send a DM to start a request.",
            }

        if mentioned_user_ids:
            mentioned_users = " ".join(f"<@{mention_id}>" for mention_id in mentioned_user_ids)
            response_text = (
                f"질문에 함께 태그된 사용자도 확인했다: {mentioned_users}. "
                f"질문 내용은 '{question_text or '내용 없음'}'으로 인식했다."
            )
        else:
            response_text = f"질문 내용을 확인했다: '{question_text or '내용 없음'}'."

        return {
            "ack": True,
            "channel_message": response_text
        }

    def _extract_additional_mentions(self, text: str) -> list[str]:
        """Return user IDs mentioned in the message, excluding the first app mention token."""
        mention_ids = re.findall(r"<@([UW][A-Z0-9]+)>", text or "")
        if len(mention_ids) <= 1:
            return []
        return mention_ids[1:]

    def _strip_leading_mention(self, text: str) -> str:
        """Remove the first Slack mention token so the remaining text is the actual question."""
        cleaned = (text or "").strip()
        cleaned = re.sub(r"^<@[UW][A-Z0-9]+>\s*", "", cleaned, count=1)
        return cleaned.strip()

    def update_orchestration_message(
        self,
        request_id: str,
        status: str,
        current_step: str
    ) -> bool:
        """
        Update parent message in orchestration channel.
        
        Called whenever request status changes.
        
        Args:
            request_id: Request UUID
            status: Current status
            current_step: Current step being executed
        
        Returns:
            True if successful
        """
        logger.info(f"Updating orchestration message for {request_id}")
        
        # TODO: Find existing parent message (via message_ts stored in requests table)
        # TODO: Update message blocks with new status
        # TODO: Post new log to thread
        
        return True

    def send_approval_request(
        self,
        user_id: str,
        request_id: str,
        summary: str,
        warnings: list
    ) -> bool:
        """
        Send approval request to orchestration channel.
        
        Called when request reaches WAITING_APPROVAL state.
        
        Args:
            user_id: For reference
            request_id: Request UUID
            summary: Summary of what's being approved
            warnings: List of warnings/flags
        
        Returns:
            True if successful
        """
        logger.info(f"Sending approval request for {request_id}")
        
        # TODO: Build Block Kit message
        # TODO: Post to orchestration channel
        # TODO: Store message_ts in requests table for later reference
        
        return True


# ============ Slack payload handlers ============

def handle_url_verification(body: Dict[str, Any]) -> Dict[str, Any]:
    """Handle Slack URL verification challenge."""
    logger.info("URL verification challenge")
    return {"challenge": body.get("challenge")}


def parse_dm_event(body: Dict[str, Any]) -> tuple:
    """
    Parse DM event from Slack Events API.
    
    Returns:
        (user_id, text, channel_id, timestamp)
    """
    event = body.get("event", {})
    return (
        event.get("user"),
        event.get("text"),
        event.get("channel"),
        event.get("ts")
    )


def parse_button_action(body: Dict[str, Any]) -> tuple:
    """
    Parse button action from Slack interactive payload.
    
    Returns:
        (user_id, action_type, payload, response_url)
    """
    user_id = body.get("user", {}).get("id")
    actions = body.get("actions", [])
    action = actions[0] if actions else {}
    
    action_type = action.get("action_id") or action.get("value") or action.get("type")

    return (user_id, action_type, body, body.get("response_url"))


def _extract_request_id(payload: Dict[str, Any]) -> Optional[str]:
    """Best-effort extraction of request_id from Slack payload."""
    if payload.get("request_id"):
        return payload.get("request_id")

    actions = payload.get("actions", [])
    if actions:
        action = actions[0]
        if action.get("value"):
            return action.get("value")

    container = payload.get("container", {})
    if container.get("message_ts"):
        return container.get("message_ts")

    return None


# Stub: complete implementation in next phase
logger.info("SlackHandler module loaded")
