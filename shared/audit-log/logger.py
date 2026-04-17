"""
Audit Logger: centralized event logging for requests.

All events (start, intermediate steps, errors, approvals, completion) go through here.
Stores in DB and formats for Slack thread display.

Maintains full audit trail for compliance and debugging.
"""

import logging
from typing import Dict, Any, Optional
from enum import Enum
from datetime import datetime

logger = logging.getLogger(__name__)


class LogLevel(str, Enum):
    """Log levels for audit logs."""
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"
    APPROVAL = "APPROVAL"
    DONE = "DONE"


def log_event(
    request_id: str,
    step_id: Optional[str],
    level: LogLevel,
    message: str,
    user_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Log a single event to audit trail.
    
    Stores in audit_logs table and returns Slack-formatted message.
    
    Args:
        request_id: Request UUID
        step_id: Step UUID (optional, None if not tied to a step)
        level: Log level enum
        message: Event message (plain text, no formatting)
        user_id: User who triggered this event (optional)
    
    Returns:
        {
            "log_id": UUID,
            "slack_formatted": "ℹ️ [10:30:45] Starting PARSING...",
            "stored_at": "2026-04-09T10:30:45.123Z"
        }
    """
    logger.info(f"Log event: {request_id} / {level} / {message[:50]}...")
    
    # TODO: Insert into audit_logs table
    # TODO: Fields: log_id (UUID), request_id, step_id, level, message, user_id, created_at
    # TODO: Format for Slack and return
    
    slack_msg = format_slack_log(level, message)
    
    return {
        "log_id": "stub_uuid",
        "slack_formatted": slack_msg,
        "stored_at": datetime.utcnow().isoformat()
    }


def format_slack_log(level: LogLevel, message: str) -> str:
    """
    Format a log message for display in Slack thread.
    
    Adds emoji prefix and timestamp.
    
    Emoji mapping:
    - INFO: ℹ️
    - WARN: ⚠️
    - ERROR: ❌
    - APPROVAL: 🟡
    - DONE: ✅
    
    Args:
        level: Log level
        message: Message text (plain text)
    
    Returns:
        Formatted string:
        "ℹ️ [10:30:45] Starting PARSING..."
    """
    emoji_map = {
        LogLevel.INFO: "ℹ️",
        LogLevel.WARN: "⚠️",
        LogLevel.ERROR: "❌",
        LogLevel.APPROVAL: "🟡",
        LogLevel.DONE: "✅"
    }
    
    emoji = emoji_map.get(level, "•")
    timestamp = datetime.utcnow().strftime("%H:%M:%S")
    
    return f"{emoji} [{timestamp}] {message}"


def batch_log_events(events: list) -> Dict[str, Any]:
    """
    Log multiple events at once.
    
    Args:
        events: List of event dicts
               [
                   {
                       "request_id": "...",
                       "step_id": "...",
                       "level": LogLevel.INFO,
                       "message": "..."
                   }
               ]
    
    Returns:
        {
            "logged": 5,
            "failed": 0,
            "slack_lines": ["ℹ️ [...]", "✅ [...]", ...]
        }
    """
    logger.info(f"Batch logging {len(events)} events")
    
    results = []
    for event in events:
        try:
            result = log_event(
                request_id=event["request_id"],
                step_id=event.get("step_id"),
                level=event["level"],
                message=event["message"],
                user_id=event.get("user_id")
            )
            results.append(result["slack_formatted"])
        except Exception as e:
            logger.error(f"Failed to log event: {e}")
    
    return {
        "logged": len(results),
        "failed": len(events) - len(results),
        "slack_lines": results
    }


def query_logs(
    request_id: str,
    step_id: Optional[str] = None,
    level: Optional[LogLevel] = None,
    limit: int = 100
) -> list:
    """
    Query logs for a request.
    
    Args:
        request_id: Request UUID
        step_id: Optional step UUID filter
        level: Optional log level filter
        limit: Max number of results
    
    Returns:
        List of log entries
    """
    logger.info(f"Querying logs for {request_id}")
    
    # TODO: Query audit_logs table
    # TODO: Filter by request_id
    # TODO: Optionally filter by step_id, level
    # TODO: Order by created_at DESC
    # TODO: Return list of dicts
    
    return []


def generate_slack_thread(request_id: str, limit: int = 50) -> str:
    """
    Generate full Slack thread content from logs.
    
    Args:
        request_id: Request UUID
        limit: Max number of logs to include
    
    Returns:
        Markdown-formatted string suitable for Slack thread
    """
    logger.info(f"Generating Slack thread for {request_id}")
    
    # TODO: Query logs for request_id
    # TODO: Format each as Slack line (with format_slack_log)
    # TODO: Join with newlines
    # TODO: Return markdown
    
    return ""


# ============ Log record types ============

LOG_TEMPLATES = {
    "request_received": "ℹ️ 요청을 받았습니다",
    "parsing_started": "ℹ️ 텍스트 분석 중입니다",
    "parsing_complete": "✅ 텍스트 분석 완료",
    "meeting_parse_started": "ℹ️ 회의록 분석 중입니다",
    "meeting_parse_complete": "✅ 회의록 분석 완료",
    "jira_draft_started": "ℹ️ Jira 초안 생성 중입니다",
    "jira_draft_complete": "✅ Jira 초안 생성 완료",
    "review_started": "ℹ️ 검수 중입니다",
    "review_complete": "✅ 검수 완료",
    "approval_requested": "🟡 승인 대기 중입니다 (600초 내)",
    "approved": "✅ 승인되었습니다",
    "rejected": "⚠️ 수정 요청됨",
    "canceled": "❌ 취소되었습니다",
    "timeout": "⏱ 요청이 만료되었습니다",
    "error": "❌ 오류 발생"
}


def log_predefined(request_id: str, template_key: str, **kwargs) -> Dict[str, Any]:
    """
    Log using predefined template.
    
    Args:
        request_id: Request UUID
        template_key: Key from LOG_TEMPLATES
        **kwargs: Variables to substitute in template
    
    Returns:
        Result from log_event()
    """
    message = LOG_TEMPLATES.get(template_key, "ℹ️ Event")
    
    return log_event(
        request_id=request_id,
        step_id=kwargs.get("step_id"),
        level=LogLevel.INFO,
        message=message
    )


# Stub: complete implementation in next phase
logger.info("Audit logger module loaded")
