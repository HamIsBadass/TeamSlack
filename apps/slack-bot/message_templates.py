"""
Slack message templates for orchestration channel and DM.

Uses Slack Block Kit format for rich formatting.

These templates ensure consistent, professional formatting across all bot messages.
"""

import logging
from typing import Dict, List, Any

logger = logging.getLogger(__name__)


def orchestration_parent_message(
    request_id: str,
    user_id: str,
    request_type: str,
    status: str,
    current_step: str,
    engine_flow: List[str]
) -> Dict[str, Any]:
    """
    Create parent message for orchestration channel.
    
    Shows:
    - Request summary (who, what, when)
    - Current status with emoji
    - Progress bar (step visualization)
    - Current action (awaiting approval, processing, etc.)
    
    Args:
        request_id: Request UUID (shortened for display)
        user_id: Slack user ID of requester
        request_type: "meeting" | "doc_analysis" | "jira_draft" etc.
        status: Current status enum
        current_step: Current step being executed
        engine_flow: List of steps: ["PARSING", "MEETING_DONE", ...]
    
    Returns:
        Block Kit payload dict (ready for Slack API)
    """
    logger.info(f"Creating orchestration parent message for {request_id}")
    
    # Status emoji mapping
    status_emoji = {
        "RECEIVED": "📨",
        "PARSING": "⚙️",
        "MEETING_DONE": "📋",
        "JIRA_DRAFTED": "📝",
        "REVIEW_DONE": "✅",
        "WAITING_APPROVAL": "🟡",
        "APPROVED": "✅",
        "DONE": "✨",
        "FAILED": "❌",
        "CANCELED": "⏹️"
    }
    
    status_emoji_str = status_emoji.get(status, "❓")
    short_id = str(request_id)[:8]
    
    # Build progress bar
    step_indicators = []
    for step in engine_flow:
        if step == current_step:
            step_indicators.append(f"→ {step} ←")
        else:
            step_indicators.append(step)
    progress_bar = " → ".join(step_indicators)
    
    # TODO: Build Block Kit message with:
    # - Header section with emoji and request ID
    # - Section with requester and request type
    # - Divider
    # - Progress bar (step indicators)
    # - Current status section
    # - Context with created_at time
    
    return {
        "type": "header",
        "text": {
            "type": "plain_text",
            "text": f"{status_emoji_str} 요청 #{short_id}",
            "emoji": True
        }
    }


def approval_message(
    request_id: str,
    summary: str,
    warnings: List[str]
) -> Dict[str, Any]:
    """
    Create approval request message.
    
    Shows:
    - Summary of what's being approved (key details from drafts)
    - Any warnings/flags (missing fields, duplicates, etc.)
    - Buttons: Approve, Request Changes, Cancel
    - Timeout warning: "Expires in 10 minutes"
    
    Args:
        request_id: Request UUID
        summary: Summary text from review-bot (markdown)
        warnings: List of warning messages (empty if none)
    
    Returns:
        Block Kit payload dict
    """
    logger.info(f"Creating approval message for {request_id}")
    
    # TODO: Build Block Kit message with:
    # - Header: "🟡 승인 대기"
    # - Section: summary text (markdown)
    # - Divider
    # - Section: warnings (if any) with ⚠️ emoji
    # - Divider
    # - Actions: Approve button, Request Changes button, Cancel button
    # - Context: "승인하지 않으면 10분 후 자동 취소됩니다"
    
    return {
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"🟡 요청 #{str(request_id)[:8]}를 검토하고 승인해주세요"
        }
    }


def completion_message(
    request_id: str,
    result_summary: str,
    jira_links: List[Dict[str, str]]
) -> Dict[str, Any]:
    """
    Create completion message.
    
    Shows:
    - Result summary
    - Links to created Jira issues (if any)
    - Time elapsed
    - Next steps (if any)
    
    Args:
        request_id: Request UUID
        result_summary: Summary of what was completed (markdown)
        jira_links: List of {"key": "TS-123", "url": "https://...", "summary": "..."}
    
    Returns:
        Block Kit payload dict
    """
    logger.info(f"Creating completion message for {request_id}")
    
    # TODO: Build Block Kit message with:
    # - Header: "✅ 완료"
    # - Section: result_summary (markdown)
    # - Divider (if jira_links)
    # - Section: "생성된 Jira 이슈" + links
    #   (each link as clickable button or text link)
    # - Context: "완료됨, 소요시간: 3분 45초"
    
    return {
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"✅ 요청 #{str(request_id)[:8]}이 완료되었습니다"
        }
    }


def dm_confirmation_message(request_type: str, persona_style: str = "concise") -> str:
    """
    Create DM confirmation message after user submits request.
    
    Personalized based on user's persona_style.
    
    Args:
        request_type: Type of request ("meeting", "jira_draft", etc.)
        persona_style: User's persona ("pm", "developer", "designer", "concise")
    
    Returns:
        Plain text message (string)
    """
    logger.info(f"Creating DM confirmation for {request_type} ({persona_style})")
    
    messages = {
        "pm": {
            "meeting": "📊 회의 분석을 시작했습니다. 주요 결정과 리스크를 추출해드릴게요.",
            "default": "📋 요청을 받았습니다. 처리 중입니다..."
        },
        "developer": {
            "meeting": "💻 회의 내용을 분석 중입니다. 기술 태스크를 구조화해드릴게요.",
            "default": "🔧 요청을 받았습니다. 처리 중입니다..."
        },
        "designer": {
            "meeting": "🎨 회의 내용을 분석 중입니다. UX 관련 결정사항을 정리해드릴게요.",
            "default": "✏️ 요청을 받았습니다. 처리 중입니다..."
        },
        "concise": {
            "meeting": "📝 요청을 받았습니다. 처리 중입니다...",
            "default": "✓ 요청을 받았습니다. 처리 중입니다..."
        }
    }
    
    persona_msgs = messages.get(persona_style, messages["concise"])
    msg = persona_msgs.get(request_type, persona_msgs["default"])
    
    return msg


def error_message(error_type: str, user_facing: bool = True) -> str:
    """
    Create standardized error message.
    
    Args:
        error_type: "invalid_input" | "timeout" | "permission" | "system_error"
        user_facing: If True, return user-friendly message; if False, return tech details
    
    Returns:
        Error message string
    """
    if user_facing:
        messages = {
            "invalid_input": "❌ 요청 형식이 올바르지 않습니다. 다시 입력해주세요.",
            "timeout": "⏱ 처리 시간이 초과되었습니다. 잠시 후 다시 시도해주세요.",
            "permission": "🔒 권한이 없습니다.",
            "system_error": "❌ 시스템 오류가 발생했습니다. 운영자에게 문의해주세요."
        }
    else:
        messages = {
            "invalid_input": "Validation error: check input format",
            "timeout": "Request timeout: exceeded SLA",
            "permission": "Insufficient permissions: check user_profiles",
            "system_error": "Unhandled exception: check logs"
        }
    
    return messages.get(error_type, "❌ 오류가 발생했습니다")


def status_update_message(
    request_id: str,
    old_status: str,
    new_status: str,
    timestamp: str
) -> str:
    """
    Create status update message for Slack thread.
    
    Args:
        request_id: Request UUID
        old_status: Previous status
        new_status: New status
        timestamp: ISO 8601 timestamp
    
    Returns:
        Thread message (short text, 1-2 lines)
    """
    status_emoji = {
        "RECEIVED": "📨",
        "PARSING": "⚙️",
        "MEETING_DONE": "📋",
        "JIRA_DRAFTED": "📝",
        "REVIEW_DONE": "✅",
        "WAITING_APPROVAL": "🟡",
        "APPROVED": "✅",
        "DONE": "✨",
        "FAILED": "❌",
        "CANCELED": "⏹️"
    }
    
    emoji = status_emoji.get(new_status, "•")
    time_str = timestamp.split("T")[1].split(".")[0]  # HH:MM:SS
    
    return f"{emoji} [{time_str}] 상태 변경: {old_status} → {new_status}"


# ============ Block Kit helpers ============

def button(action_id: str, text: str, style: str = "primary") -> Dict[str, Any]:
    """
    Create a Slack button element.
    
    Args:
        action_id: Unique identifier for the button action
        text: Button label text
        style: "primary" (blue), "danger" (red), or default (gray)
    
    Returns:
        Block Kit button element dict
    """
    return {
        "type": "button",
        "action_id": action_id,
        "text": {
            "type": "plain_text",
            "text": text,
            "emoji": True
        },
        "style": style
    }


def section(text: str, markdown: bool = True) -> Dict[str, Any]:
    """
    Create a Slack section element.
    
    Args:
        text: Section text
        markdown: If True, treat as markdown; if False, plain text
    
    Returns:
        Block Kit section element dict
    """
    return {
        "type": "section",
        "text": {
            "type": "mrkdwn" if markdown else "plain_text",
            "text": text,
            "emoji": True if not markdown else False
        }
    }


# Stub: complete implementation in next phase
logger.info("Message templates module loaded")
