"""Socket Mode personal Slack bot runner for /psearch, /usdtw, /reply, and /summary."""

import os
import sys
import re
import json
import time
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from uuid import uuid4

import requests
from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk.errors import SlackApiError

try:
    from google import genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

# Setup paths for shared modules
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from shared.utils import parse_psearch_input, select_perplexity_model, select_gemini_model, to_slack_format

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load personal bot env first, then fall back to default env.
_env_file = os.getenv("TEAMSLACK_ENV_FILE", ".env.personal-bot").strip() or ".env.personal-bot"
load_dotenv(REPO_ROOT / _env_file)
load_dotenv(REPO_ROOT / ".env", override=False)

PERPLEXITY_API_URL = "https://api.perplexity.ai/chat/completions"

# 기본 지침
SYSTEM_PROMPT_BASE = (
    "불필요한 수식어 금지: 인삿말, 과도한 리액션, 칭찬, 스몰토크 없이 본론만 답변한다.\n"
    "말투: 기본 말투는 존댓말이 아닌 반말로 답한다.\n"
    "맥락 격리: 질문의 주제와 상관없는 사용자의 개인적 취향(선호하는 음료, 습관, 기호 등)을 대화에 끌어들여 언급하지 않는다. 특히 비즈니스나 정보 검색 시 사적인 내용을 섞어 칭찬하지 않는다.\n"
    "효율적 구조: 서론과 결론의 군더더기를 빼고, 사용자가 묻는 핵심 내용에 대해 즉시 답한다.\n"
    "담백한 어조: 정확성과 효율성 중심의 전문적이고 드라이한 어조를 유지한다.\n"
    "말투: 당당한 성격으로 단정적으로 답하고 문장 끝은 기본적으로 '~다!'로 마무리한다."
)

# /psearch 지침
SYSTEM_PROMPT_PSEARCH = SYSTEM_PROMPT_BASE + (
    "\n\n금융/경제 질문: Perplexity Finance 데이터베이스를 우선 활용하여 최신 시장 데이터 기반 답변을 제공한다."
)

SYSTEM_PROMPT_PSEARCH_FINANCE = SYSTEM_PROMPT_PSEARCH + (
    "\n금융/주식/환율/코인/금리 질문: Perplexity Finance 데이터베이스를 최우선으로 활용하고, 실시간 시장 수치와 근거가 확인되는 정보만 답한다."
)

# 검색 결과 전용 지침(말투 강제 없음, Slack 가독 포맷 우선)
SYSTEM_PROMPT_PSEARCH_FORMATTED = (
    "너는 Slack 검색 비서다. 웹 검색 기반 사실만 정리한다.\n"
    "출력은 한국어로 작성하고, 과장/추측/말투 강제(예: ~다!, ~햄)를 하지 않는다.\n"
    "출력 형식은 Slack 친화 마크다운으로 고정한다:\n"
    "1) *핵심 요약* (2~3줄)\n"
    "2) *주요 근거* (불릿 3~5개, 필요 시 *볼드* 키워드 사용)\n"
    "3) *추가 메모* (있을 때만, 1~2줄)\n"
    "본문에 [1], [2] 같은 인용 번호/출처 메타텍스트는 포함하지 않는다."
)

SYSTEM_PROMPT_PSEARCH_FORMATTED_FINANCE = SYSTEM_PROMPT_PSEARCH_FORMATTED + (
    "\n금융/주식/환율/코인/금리 답변은 숫자, 시점, 근거를 먼저 제시하고 추측성 표현을 배제한다."
)

# /usdtw 지침
SYSTEM_PROMPT_USDTW = (
    "미화-원화 환율 함수: USD→KRW 환율을 제공한다.\n"
    "첫 문장 필수 형식: '지금 기준으로 1달러는 약 00원이다! :hamster:'\n"
    "판단 포함: 최근 6개월 환율 흐름을 고려하여 현재가 저점/고점인지 한 줄 의견 제시. 문장은 '~다!'로 끝낸다.\n"
    "출처 생략: 참고 문헌이나 출처표시 [1][2] 등은 제공하지 않는다."
)


def _required_env(name: str) -> str:
    # Personal bot must not silently fall back to orchestrator Slack tokens.
    personal_only = {
        "SLACK_BOT_TOKEN": "SLACK_BOT_TOKEN_PERSONAL",
        "SLACK_APP_TOKEN": "SLACK_APP_TOKEN_PERSONAL",
        "SLACK_SIGNING_SECRET": "SLACK_SIGNING_SECRET_PERSONAL",
    }

    if name in personal_only:
        personal_key = personal_only[name]
        value = os.getenv(personal_key, "").strip()
        if value:
            return value
        raise RuntimeError(
            f"Missing required environment variable: {personal_key} (personal bot)"
        )

    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _optional_env_csv(name: str) -> list[str]:
    value = os.getenv(name, "").strip()
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


ALLOWED_USER_IDS = set(_optional_env_csv("SLACK_ALLOWED_USER_IDS"))
ALLOWED_CHANNEL_IDS = set(_optional_env_csv("SLACK_ALLOWED_CHANNEL_IDS"))
# 0 (default): allow all users/channels, 1: enforce allowlists above.
ENFORCE_ALLOWLIST = os.getenv("SLACK_ENFORCE_ALLOWLIST", "0").strip() == "1"
PENDING_REPLY_INPUTS: Dict[str, Dict[str, str]] = {}
LAST_REPLY_DRAFTS: Dict[str, Dict[str, str]] = {}
REPLY_SHORTCUT_SESSIONS: Dict[str, Dict[str, str]] = {}
PENDING_DIRECT_SENDS: Dict[str, Dict[str, str]] = {}
PENDING_TASK_WORKFLOWS: Dict[str, Dict[str, str]] = {}
CHANNEL_RESOLUTION_CACHE: Dict[str, str] = {}
USER_RESOLUTION_CACHE: Dict[str, str] = {}
DM_CHAT_ENABLED = os.getenv("PERSONAL_DM_CHAT_ENABLED", "1").strip() == "1"
DM_CONTEXT_LIMIT = max(8, int(os.getenv("PERSONAL_DM_CONTEXT_LIMIT", "16").strip() or "16"))

# ============ N-Step Workflow Definition ============
# Workflow templates define sequential steps for complex multi-part tasks.
# Each step can require user input or automatic approval gates.
# Format: {
#   "step_name": {
#     "prompt": str,  # Prompt shown to user when awaiting this step
#     "requires_user_input": bool,  # If True, await user response
#     "requires_approval": bool,  # If True, show approval buttons/prompts
#     "handler": callable,  # Function to execute this step (optional)
#   }
# }

WORKFLOW_STEPS = {
    "search_then_send": {
        "query": {
            "prompt": "검색어를 알려주세요. 예: 오늘의 명언",
            "requires_user_input": True,
            "awaiting_key": "search_query",
        },
        "channel": {
            "prompt": "검색 결과를 보낼 채널을 알려주세요. 예: [비공개채널]",
            "requires_user_input": True,
            "awaiting_key": "channel_ref",
        },
        "search": {
            "prompt": "검색 중입니다...",
            "requires_user_input": False,
            "execute": "perplexity_search",
        },
        "approval": {
            "prompt": "위 내용을 채널에 발송할까요?",
            "requires_user_input": False,
            "requires_approval": True,
        },
        "send": {
            "prompt": "전송 중입니다...",
            "requires_user_input": False,
            "execute": "send_to_channel",
        },
    },
    # 3+ step example: search → summarize → send
    "search_summarize_send": {
        "query": {
            "prompt": "검색어를 알려주세요.",
            "requires_user_input": True,
            "awaiting_key": "search_query",
        },
        "channel": {
            "prompt": "결과를 보낼 채널을 알려주세요.",
            "requires_user_input": True,
            "awaiting_key": "channel_ref",
        },
        "search": {
            "prompt": "검색 중입니다...",
            "requires_user_input": False,
            "execute": "perplexity_search",
        },
        "summarize": {
            "prompt": "내용을 정리 중입니다...",
            "requires_user_input": False,
            "execute": "gemini_summarize",
        },
        "approval": {
            "prompt": "정리된 내용을 채널에 발송할까요?",
            "requires_user_input": False,
            "requires_approval": True,
        },
        "send": {
            "prompt": "전송 중입니다...",
            "requires_user_input": False,
            "execute": "send_to_channel",
        },
    },
}

# Workflow execution order (steps are executed in this order for each workflow type)
WORKFLOW_EXECUTION_ORDER = {
    "search_then_send": ["query", "channel", "search", "approval", "send"],
    "search_summarize_send": ["query", "channel", "search", "summarize", "approval", "send"],
}


def _remove_citation_marks(text: str) -> str:
    """Remove citation marks like [1][2][3] from text."""
    return re.sub(r'\[\d+\]', '', text).strip()


def _to_single_line(text: str) -> str:
    """Collapse multiline text into one line."""
    return re.sub(r"\s+", " ", (text or "").strip())


def _clip_text(text: str, max_len: int = 400) -> str:
    """Return a compact preview text for DM display."""
    normalized = _to_single_line(text)
    if len(normalized) <= max_len:
        return normalized
    return normalized[:max_len].rstrip() + "..."


def _limit_chars(text: str, max_chars: int = 1000) -> str:
    """Limit output text length to max_chars."""
    normalized = (text or "").strip()
    if len(normalized) <= max_chars:
        return normalized
    return normalized[:max_chars].rstrip()


def _extract_reply_only(text: str) -> str:
    """Keep only final reply body without meta/instruction lines."""
    normalized = (text or "").strip()
    if not normalized:
        return ""

    # If model includes labels, keep only the content after the last label.
    markers = [
        "<답변 초안>",
        "답변 초안:",
        "수정된 답변:",
        "최종 답변:",
        "답변:",
        "수정본:",
    ]
    for marker in markers:
        if marker in normalized:
            normalized = normalized.split(marker)[-1].strip()

    # Remove common wrapper lines that are not part of the actual reply.
    lines = [line.strip() for line in normalized.splitlines()]
    filtered = []
    for line in lines:
        if not line:
            filtered.append("")
            continue
        lower = line.lower()
        if lower.startswith("네,") and ("작성" in line or "반영" in line):
            continue
        # Drop standalone metadata/title lines (with optional markdown decoration).
        compact = re.sub(r"[*_`<>\[\]()]", "", line).strip().replace(" ", "")
        if compact in ("답변초안", "수정된답변", "최종답변", "답변", "수정본"):
            continue
        if compact.startswith("답변초안:"):
            continue
        if "수정된 답변" in line or "최종 답변" in line or "답변 초안" in line:
            continue
        filtered.append(line)

    cleaned = "\n".join(filtered).strip()
    return cleaned


def _reply_session_to_blocks(session: Dict[str, str]) -> list[dict[str, Any]]:
    """Build DM blocks for reply draft preview and actions."""
    source_permalink = (session.get("source_permalink") or "").strip()
    session_id = session.get("session_id", "")
    current_draft = to_slack_format(session.get("current_draft", ""))
    original_preview = session.get("original_preview", "")

    actions: list[dict[str, Any]] = [
        {
            "type": "button",
            "text": {"type": "plain_text", "text": "수정 요청"},
            "action_id": "reply_draft_edit",
            "value": session_id,
        },
        {
            "type": "button",
            "text": {"type": "plain_text", "text": "발송"},
            "style": "primary",
            "action_id": "reply_draft_send",
            "value": session_id,
        },
    ]
    if source_permalink:
        actions.append(
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "원문 열기"},
                "url": source_permalink,
                "action_id": "reply_draft_open_source",
                "value": session_id,
            }
        )

    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*원문 미리보기*\n> {original_preview}",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*초안*\n{current_draft}",
            },
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "API: Google Gemini API | 모델: gemini-2.5-flash-lite | 문장 정책: 초기 초안 3문장, 수정 후 제한 없음",
                }
            ],
        },
        {
            "type": "actions",
            "elements": actions,
        },
    ]


def _create_reply_shortcut_session(
    *,
    user_id: str,
    dm_channel_id: str,
    source_channel_id: str,
    source_ts: str,
    source_permalink: str,
    original_message: str,
    current_draft: str,
) -> Dict[str, str]:
    session_id = str(uuid4())
    session = {
        "session_id": session_id,
        "user_id": user_id,
        "dm_channel_id": dm_channel_id,
        "source_channel_id": source_channel_id,
        "source_ts": source_ts,
        "source_permalink": source_permalink,
        "original_message": original_message,
        "original_preview": _clip_text(original_message, max_len=500),
        "current_draft": current_draft,
    }
    REPLY_SHORTCUT_SESSIONS[session_id] = session
    return session


def _post_reply_shortcut_dm(client, session: Dict[str, str]) -> None:
    """Post current session draft to user DM with interactive actions."""
    blocks = _reply_session_to_blocks(session)
    fallback_text = (
        "답변 초안\n"
        f"원문: {session.get('original_preview', '')}\n"
        f"초안: {to_slack_format(session.get('current_draft', ''))}"
    )
    client.chat_postMessage(
        channel=session["dm_channel_id"],
        text=fallback_text,
        blocks=blocks,
    )


def _format_amount(value: float) -> str:
    """Format numeric amount for user-facing text."""
    if float(value).is_integer():
        return str(int(value))
    return str(value)


def _is_command_allowed(command: Dict[str, Any]) -> tuple[bool, str]:
    """Check whether a slash command is allowed to run."""
    if not ENFORCE_ALLOWLIST:
        return True, ""

    user_id = (command.get("user_id") or "").strip()
    channel_id = (command.get("channel_id") or "").strip()

    if ALLOWED_USER_IDS and user_id not in ALLOWED_USER_IDS:
        return False, "허용된 테스트 사용자만 실행할 수 있습니다."

    if ALLOWED_CHANNEL_IDS and channel_id not in ALLOWED_CHANNEL_IDS:
        return False, "허용된 테스트 채널에서만 실행할 수 있습니다."

    return True, ""


def _is_payload_allowed(payload: Dict[str, Any]) -> tuple[bool, str]:
    """Check whether a slash command or shortcut payload is allowed."""
    if not ENFORCE_ALLOWLIST:
        return True, ""

    if not payload:
        return False, "허용된 테스트 사용자만 실행할 수 있습니다."

    user_id = ""
    channel_id = ""

    if isinstance(payload.get("user"), dict):
        user_id = (payload.get("user", {}).get("id") or "").strip()
    else:
        user_id = (payload.get("user_id") or "").strip()

    if isinstance(payload.get("channel"), dict):
        channel_id = (payload.get("channel", {}).get("id") or "").strip()
    else:
        channel_id = (payload.get("channel_id") or "").strip()

    if ALLOWED_USER_IDS and user_id not in ALLOWED_USER_IDS:
        return False, "허용된 테스트 사용자만 실행할 수 있습니다."

    if ALLOWED_CHANNEL_IDS and channel_id not in ALLOWED_CHANNEL_IDS:
        return False, "허용된 테스트 채널에서만 실행할 수 있습니다."

    return True, ""


def _parse_usdtw_input(raw_text: str) -> Tuple[Optional[float], str, str]:
    """Parse /usdtw input into amount and currency.

    Rules:
    - Empty input: returns (None, "USD", "달러")
    - Number only: interpreted as USD amount (e.g. 0.1 -> 0.1 USD)
    - Number + currency: parses common KR/EN currency aliases
    """
    text = (raw_text or "").strip().lower()
    if not text:
        return None, "USD", "달러"

    # Number with optional currency token, e.g. "0.1", "1달러", "20 usd"
    match = re.match(r"^([0-9]+(?:\.[0-9]+)?)\s*([a-zA-Z가-힣]+)?$", text)
    if not match:
        return None, "USD", "달러"

    amount = float(match.group(1))
    token = (match.group(2) or "usd").strip()

    currency_map = {
        "usd": ("USD", "달러"),
        "dollar": ("USD", "달러"),
        "달러": ("USD", "달러"),
        "eur": ("EUR", "유로"),
        "euro": ("EUR", "유로"),
        "유로": ("EUR", "유로"),
        "jpy": ("JPY", "엔"),
        "yen": ("JPY", "엔"),
        "엔": ("JPY", "엔"),
        "cny": ("CNY", "위안"),
        "yuan": ("CNY", "위안"),
        "위안": ("CNY", "위안"),
        "gbp": ("GBP", "파운드"),
        "pound": ("GBP", "파운드"),
        "파운드": ("GBP", "파운드"),
    }

    code, label = currency_map.get(token, (token.upper(), token))
    return amount, code, label


def add_gom_emojis(text: str) -> str:
    """Apply personal bot style markers to first and last sentences.

    Rules:
    - Keep existing emoji timing (first sentence + final sentence emphasis).
    - Replace previous style markers with personal style: '~다!' and ':hamster:'.
    """
    if not text or len(text.strip()) == 0:
        return text

    def _normalize_sentence_ending(sentence: str) -> str:
        s = (sentence or "").rstrip()
        if not s:
            return s

        # Remove trailing punctuation before style normalization.
        s = re.sub(r"[.!?~]+$", "", s).rstrip()
        if not s:
            return s

        # Requested rule: "~했다" -> "~햄".
        if s.endswith("했다"):
            return s[:-2] + "햄"

        # Requested rule: nominal sentence should become "~이다햄!".
        if s.endswith("입니다"):
            return s[:-3] + "이다햄!"
        if s.endswith("이다"):
            return s[:-2] + "이다햄!"

        # Do not force "다!" when sentence ends as a noun phrase.
        return s

    # Remove legacy markers first, then apply personal style consistently.
    text = (
        text.replace("🐻‍❄️", "")
        .replace(":king_gom:", "")
        .replace(":polar_bear:", "")
        .replace(":북극곰:", "")
        .replace(":hamster:", "")
    )
    # Strip legacy suffix marker only when it appears as a token-like ending.
    text = re.sub(r"곰(?=[.!?:\s]|$)", "", text)

    # Preserve multiline layout (lists/paragraph breaks) to avoid collapsing
    # search result formatting in Slack.
    if "\n" in text:
        lines = text.splitlines()
        non_empty_indexes = [idx for idx, line in enumerate(lines) if line.strip()]
        if not non_empty_indexes:
            return _normalize_sentence_ending(text) + " :hamster:"

        first_idx = non_empty_indexes[0]
        last_idx = non_empty_indexes[-1]

        first_line = _normalize_sentence_ending(lines[first_idx].strip())
        lines[first_idx] = first_line + " :hamster:"

        if last_idx != first_idx:
            last_line = _normalize_sentence_ending(lines[last_idx].strip())
            if not last_line.endswith(":hamster:"):
                last_line = last_line + " :hamster:"
            lines[last_idx] = last_line

        return "\n".join(lines).strip()

    # Sentence-aware styling for plain prose. If sentence split is not possible,
    # fall back to one-line style enforcement.
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", text) if p.strip()]
    if not parts:
        return _normalize_sentence_ending(text) + " :hamster:"

    styled: list[str] = []
    for idx, part in enumerate(parts):
        sentence = _normalize_sentence_ending(part)
        if idx == 0:
            sentence = sentence + " :hamster:"
        if idx == len(parts) - 1 and not sentence.endswith(":hamster:"):
            sentence = sentence + " :hamster:"
        styled.append(sentence)

    return " ".join(styled).strip()


def _parse_message_link(link: str) -> Tuple[Optional[str], Optional[str]]:
    """Parse Slack message link to extract channel_id and message_ts.
    
    Format: https://workspace.slack.com/archives/C0AS0C51H0S/p1712000000000000
    Returns: (channel_id, message_ts) or (None, None) if invalid
    
    Examples:
    - "https://...​/archives/C0AS0C51H0S/p1712000000000000" -> ("C0AS0C51H0S", "1712000.000000")
    """
    try:
        # Extract channel_id and ts_no_dots from link
        pattern = r'archives/([A-Z0-9]+)/p(\d+)'
        match = re.search(pattern, link)
        if not match:
            return None, None
        
        channel_id = match.group(1)
        ts_no_dots = match.group(2)
        
        # Convert p1712000000000000 -> 1712000.000000
        if len(ts_no_dots) >= 10:
            message_ts = f"{ts_no_dots[:10]}.{ts_no_dots[10:]}"
        else:
            return None, None
        
        return channel_id, message_ts
    except Exception:
        return None, None


def _extract_first_slack_message_link(text: str) -> Optional[str]:
    """Extract first Slack archive message link from command text."""
    if not text:
        return None
    match = re.search(r"https?://[^\s>]+/archives/[A-Z0-9]+/p\d+", text)
    if not match:
        return None
    return match.group(0)


def _fetch_summary_source_from_link(client, message_link: str) -> Tuple[bool, str, Optional[str]]:
    """Fetch root message and thread replies from Slack link for summary input."""
    channel_id, message_ts = _parse_message_link(message_link)
    if not channel_id or not message_ts:
        return False, "Slack 메시지 링크 형식이 올바르지 않습니다.", None

    try:
        history = client.conversations_history(
            channel=channel_id,
            latest=message_ts,
            limit=1,
            inclusive=True,
        )
        root_messages = history.get("messages") or []
        if not root_messages:
            return False, "링크 원문 메시지를 찾지 못했습니다.", None

        root_text = (root_messages[0].get("text") or "").strip()

        replies_result = client.conversations_replies(
            channel=channel_id,
            ts=message_ts,
            limit=50,
            inclusive=True,
        )
        replies = replies_result.get("messages") or []

        lines: list[str] = []
        if root_text:
            lines.append("[원문]")
            lines.append(root_text)

        thread_lines = []
        for msg in replies[1:]:
            msg_text = (msg.get("text") or "").strip()
            if msg_text:
                thread_lines.append(f"- {msg_text}")

        if thread_lines:
            lines.append("\n[스레드 답글]")
            lines.extend(thread_lines)

        merged = "\n".join(lines).strip()
        if not merged:
            return False, "요약 가능한 텍스트를 찾지 못했습니다.", None

        return True, "", merged
    except SlackApiError as exc:
        error_code = ""
        try:
            error_code = (exc.response or {}).get("error", "")
        except Exception:
            error_code = ""

        if error_code in ("channel_not_found", "not_in_channel"):
            return False, "해당 대화방에 봇이 접근할 수 없습니다. 채널 초대 후 다시 시도해주세요.", None
        if error_code == "missing_scope":
            return False, "Slack 권한(scope)이 부족합니다. channels:history/groups:history/im:history 를 확인해주세요.", None
        return False, f"Slack API 오류({error_code or 'unknown'})", None
    except Exception as exc:
        logger.exception("Failed to fetch summary source from link")
        return False, f"링크 내용 조회 실패: {exc}", None


def _fetch_reply_source_message(
    client,
    *,
    source_channel_id: str,
    source_ts: str,
    fallback_text: str = "",
) -> Tuple[bool, str, Optional[str]]:
    """Fetch source message text for reply generation with shared error handling."""
    if source_channel_id and source_ts:
        try:
            history = client.conversations_history(
                channel=source_channel_id,
                latest=source_ts,
                limit=1,
                inclusive=True,
            )
            messages = history.get("messages") or []
            original_message = (messages[0].get("text") if messages else "") or ""
            if original_message.strip():
                return True, "", original_message
        except SlackApiError as exc:
            error_code = ""
            try:
                error_code = (exc.response or {}).get("error", "")
            except Exception:
                error_code = ""

            if error_code in ("channel_not_found", "not_in_channel", "missing_scope"):
                return (
                    False,
                    "봇이 해당 대화방에 접근할 수 없거나 권한이 부족합니다. "
                    "공개 채널/봇 참여 채널에서 다시 시도하거나, shortcut을 사용해주세요.",
                    None,
                )
            raise

    if fallback_text.strip():
        return True, "", fallback_text.strip()

    return False, "원문 메시지를 찾지 못했습니다. 스레드에서 다시 시도하거나 메시지 링크를 입력해주세요.", None


def _build_reply_draft_common(original_message: str) -> Tuple[bool, str, Optional[str]]:
    """Generate reply draft from source text with unified behavior."""
    if not (original_message or "").strip():
        return False, "원문 메시지가 비어 있어 답변 초안을 생성할 수 없습니다.", None

    reply_draft = _gemini_generate_reply(original_message, "대기", "")
    if not reply_draft:
        return False, "자동 답변 초안 생성을 할 수 없습니다. 잠시 후 다시 시도해주세요.", None

    return True, "", reply_draft


def _limit_sentences(text: str, max_sentences: int = 3) -> str:
    """Trim text to at most max_sentences sentences."""
    cleaned = (text or "").strip()
    if not cleaned:
        return cleaned

    parts = re.split(r"(?<=[.!?])\s+", cleaned)
    if len(parts) <= max_sentences:
        return cleaned
    return " ".join(parts[:max_sentences]).strip()


def _gemini_generate_reply(message_text: str, choice: str, context: str = "") -> Optional[str]:
    """Generate reply draft using Gemini API.
    
    Args:
        message_text: Original message content
        choice: "예" (affirmative) | "아니오" (negative) | "대기" (neutral)
        context: Optional additional context for Gemini
    
    Returns:
        Generated reply text or None if API fails
    """
    if not GEMINI_AVAILABLE:
        return None
    
    try:
        api_key = _required_env("GEMINI_API_KEY")
        client = genai.Client(api_key=api_key)
        
        # Keep prompt compact to reduce token usage.
        normalized_message = (message_text or "").strip()
        if len(normalized_message) > 900:
            normalized_message = normalized_message[:900]

        choice_map = {
            "예": "긍정적이고 동의하는",
            "아니오": "거절하거나 반박하는",
            "대기": "중립적이고 추가 정보를 요청하는",
        }
        choice_description = choice_map.get(choice, "일반적인")
        
        system_prompt = (
            "원본 메시지에 대한 답변 초안을 생성해달라. "
            "사용자의 선택 옵션을 고려하여 적절한 톤과 내용으로 작성한다. "
            "답변은 간결하고 명확하며 실행 가능해야 한다. "
            "기본 답변은 최대 3문장으로 작성한다. "
            "직장인 업무 커뮤니케이션 말투를 사용한다. "
            "존댓말을 유지하고 불필요한 감탄/이모지/과장 표현을 사용하지 않는다. "
            "마크다운 형식을 사용하여 가독성을 높인다."
        )
        
        prompt = (
            f"지침: {system_prompt}\n\n"
            f"원본 메시지: {normalized_message}\n\n"
            f"응답 톤: {choice_description} 답변\n"
        )
        if context:
            prompt += f"추가 맥락: {context}\n"
        
        prompt += "\n위 메시지에 대한 답변 초안을 생성해주세요."
        
        response = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=prompt,
            config=genai.types.GenerateContentConfig(
                max_output_tokens=260,
                temperature=0.4,
            ),
        )

        if response and response.text:
            text = response.text.strip()
            return _limit_sentences(text, max_sentences=3)
    except Exception as e:
        logger.warning(f"Gemini API failed: {e}")
    
    return None


def _gemini_generate_summary(text: str) -> Optional[str]:
    """Generate concise summary text from raw user input."""
    if not GEMINI_AVAILABLE:
        return None

    normalized_text = (text or "").strip()
    if not normalized_text:
        return None

    try:
        api_key = _required_env("GEMINI_API_KEY")
        client = genai.Client(api_key=api_key)
        prompt = (
            "다음 내용을 업무용 요약으로 정리한다. "
            "핵심만 남기고 군더더기는 제거한다. "
            "출력 형식은 다음 순서로 고정한다: \n"
            "1) 한 줄 핵심\n"
            "2) 주요 포인트(불릿 3개 이내)\n"
            "3) 액션 아이템(있으면)\n\n"
            f"원문:\n{normalized_text}"
        )

        response = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=prompt,
            config=genai.types.GenerateContentConfig(
                max_output_tokens=360,
                temperature=0.3,
            ),
        )
        if response and response.text:
            return response.text.strip()
    except Exception as e:
        logger.warning(f"Gemini summary failed: {e}")

    return None


def _looks_like_search_request(user_text: str) -> bool:
    """Heuristic detection for requests that should use web search engine."""
    text = (user_text or "").strip().lower()
    if not text:
        return False

    if text.startswith("/psearch"):
        return True

    keywords = [
        "검색", "찾아", "알아봐", "리서치", "조사", "근거", "출처", "최신",
        "뭐야", "뭐지", "무엇", "뜻", "정의", "실존", "팩트", "사실",
        "날씨", "기온", "강수", "강수량", "예보", "미세먼지", "초미세먼지",
        "주식", "주가", "종목", "환율", "달러", "원달러", "코스피", "코스닥", "코인", "비트코인", "이더리움", "금리", "국채",
        "news", "search", "find", "look up", "lookup", "research",
        "weather", "forecast", "temperature", "air quality",
    ]
    if any(k in text for k in keywords):
        return True

    # Explicit Korean request patterns such as "~검색해줘" variants.
    search_patterns = [
        r"검색해\s*줘",
        r"검색해\s*주세요",
        r"찾아\s*줘",
        r"찾아\s*주세요",
        r"알아봐\s*줘",
        r"알아봐\s*주세요",
        r".+\s*(이|가|은|는)?\s*뭐야\??$",
        r".+\s*(이|가|은|는)?\s*뭐지\??$",
        r".+\s*뜻\s*(이야|이야\?|인가|뭐야)?\??$",
        r".+\s*날씨\s*(어때|어떰|알려줘|알려\s*줘|보여줘|보여\s*줘)?\??$",
        r"(오늘|내일|이번주|주말)\s*날씨\??$",
        r".+\s*(주식|주가|환율|코인|비트코인|이더리움|금리|국채)\s*(어때|어떰|알려줘|알려\s*줘|전망|분석)?\??$",
    ]
    return any(re.search(pattern, text) for pattern in search_patterns)


def _is_finance_query(user_text: str) -> bool:
    text = (user_text or "").strip().lower()
    if not text:
        return False

    finance_keywords = [
        "주식", "주가", "종목", "환율", "달러", "원달러", "usd", "krw",
        "코스피", "코스닥", "코인", "비트코인", "이더리움", "금리", "국채", "채권",
        "금값", "유가", "경제지표", "경제", "시장", "증시", "배당", "실적",
    ]
    return any(keyword in text for keyword in finance_keywords)


def _perplexity_system_prompt_for_query(user_text: str, *, formatted: bool = False) -> str:
    if _is_finance_query(user_text):
        return SYSTEM_PROMPT_PSEARCH_FORMATTED_FINANCE if formatted else SYSTEM_PROMPT_PSEARCH_FINANCE
    return SYSTEM_PROMPT_PSEARCH_FORMATTED if formatted else SYSTEM_PROMPT_PSEARCH


def _extract_search_query(user_text: str) -> str:
    """Extract core search keywords from natural-language search requests."""
    text = (user_text or "").strip()
    if not text:
        return ""

    # Strip common request endings.
    endings = [
        "검색해줘", "검색해 줘", "검색해주세요", "검색해 주세요",
        "찾아줘", "찾아 줘", "찾아주세요", "찾아 주세요",
        "알아봐줘", "알아봐 줘", "알아봐주세요", "알아봐 주세요",
    ]
    lowered = text.lower()
    for ending in endings:
        idx = lowered.find(ending)
        if idx != -1:
            text = text[:idx].strip()
            break

    # Remove trailing search nouns (e.g., "영화 검색", "뉴스 찾기").
    text = re.sub(r"\s*(검색|찾기|조회|리서치|조사)\s*$", "", text, flags=re.IGNORECASE).strip()

    # Remove leading command-like tokens.
    text = re.sub(r"^[/#@\-\s]+", "", text).strip()

    # Normalize definition-style questions to pure keyword.
    # Examples: "밤티말빵이 뭐야" -> "밤티말빵", "OO 뜻이야?" -> "OO"
    text = re.sub(r"\s*(이|가|은|는)?\s*뭐(야|지)\??$", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"\s*뜻\s*(이야|인가|뭐야)?\??$", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"\s*(무엇|정의)\s*(인가|이야)?\??$", "", text, flags=re.IGNORECASE).strip()

    # If extraction failed, use original text as fallback.
    return text or (user_text or "").strip()


def _extract_year_terms(text: str) -> list[str]:
    """Extract explicit year-like constraints such as '26년' or '2026'."""
    raw = (text or "").strip()
    if not raw:
        return []

    # Keep unique order.
    seen: set[str] = set()
    years: list[str] = []

    patterns = [
        r"\b(19\d{2}|20\d{2})\b",   # 1999, 2026
        r"\b(\d{2})년\b",            # 26년
        r"\b(19\d{2}|20\d{2})년\b", # 2026년
    ]
    for pattern in patterns:
        for match in re.findall(pattern, raw):
            token = f"{match}년" if pattern.endswith("년\\b") else str(match)
            if token not in seen:
                seen.add(token)
                years.append(token)

    return years


def _build_recent_dm_context(client, channel_id: str, latest_ts: str, requester_user_id: str) -> str:
    """Fetch recent DM messages to provide multi-turn context to model."""
    try:
        history = client.conversations_history(
            channel=channel_id,
            latest=latest_ts,
            inclusive=False,
            limit=DM_CONTEXT_LIMIT,
        )
        messages = history.get("messages") or []
        if not messages:
            return ""

        # Slack returns newest-first; reverse for chronological flow.
        messages = list(reversed(messages))
        lines: list[str] = []
        for msg in messages:
            text = (msg.get("text") or "").strip()
            if not text:
                continue

            msg_user = (msg.get("user") or "").strip()
            role = "사용자" if msg_user == requester_user_id else "봇"
            lines.append(f"{role}: {_clip_text(text, max_len=600)}")

        return "\n".join(lines).strip()
    except Exception as exc:
        logger.warning(f"Failed to build DM context: {exc}")
        return ""


def _build_recent_channel_context(client, channel_id: str, latest_ts: str, requester_user_id: str) -> str:
    """Fetch recent channel messages for mention-based public replies."""
    try:
        history = client.conversations_history(
            channel=channel_id,
            latest=latest_ts,
            inclusive=False,
            limit=8,
        )
        messages = history.get("messages") or []
        if not messages:
            return ""

        messages = list(reversed(messages))
        lines: list[str] = []
        for msg in messages:
            text = (msg.get("text") or "").strip()
            if not text:
                continue

            msg_user = (msg.get("user") or "").strip()
            if msg_user == requester_user_id:
                role = "요청자"
            elif msg.get("bot_id"):
                role = "봇"
            else:
                role = "대화참여자"

            lines.append(f"{role}: {_clip_text(text, max_len=400)}")

        return "\n".join(lines).strip()
    except Exception as exc:
        logger.warning(f"Failed to build channel context: {exc}")
        return ""


def _pending_direct_send_key(user_id: str) -> str:
    return user_id.strip()


def _normalize_channel_reference(channel_ref: str) -> str:
    cleaned = (channel_ref or "").strip()
    cleaned = cleaned.lstrip("#@")
    cleaned = re.sub(r"\s*채널\s*$", "", cleaned).strip()
    cleaned = re.sub(r"(에게|한테|으로|로|에)$", "", cleaned).strip()
    cleaned = re.sub(r"\s+", "", cleaned)
    return cleaned


def _looks_like_channel_reference(text: str) -> bool:
    candidate = _normalize_channel_reference(text)
    if not candidate:
        return False
    return len(candidate) <= 50 and " " not in candidate


def _extract_user_id_from_reference(user_ref: str) -> Optional[str]:
    """Extract Slack user id from mention or raw user id token."""
    raw = (user_ref or "").strip()
    if not raw:
        return None

    mention_match = re.search(r"<@([UW][A-Z0-9]{8,})>", raw)
    if mention_match:
        return (mention_match.group(1) or "").strip()

    if re.fullmatch(r"[UW][A-Z0-9]{8,}", raw):
        return raw

    return None


def _normalize_user_reference(user_ref: str) -> str:
    cleaned = (user_ref or "").strip()
    cleaned = re.sub(r"^@+", "", cleaned).strip()
    cleaned = re.sub(r"\s*님\s*$", "", cleaned).strip()
    cleaned = re.sub(r"(에게|한테|으로|로|에)$", "", cleaned).strip()
    return cleaned


def _normalize_name_token(name: str) -> str:
    token = (name or "").strip().lower()
    token = re.sub(r"\s+", "", token)
    token = re.sub(r"[^\w가-힣]", "", token)
    return token


def _resolve_user_reference(client, user_ref: str) -> Tuple[bool, str, Optional[str]]:
    direct_user_id = _extract_user_id_from_reference(user_ref)
    if direct_user_id:
        return True, "", direct_user_id

    target_name = _normalize_user_reference(user_ref)
    if not target_name:
        return False, "사용자 정보가 비어 있습니다.", None

    normalized_target = _normalize_name_token(target_name)
    cached_user_id = USER_RESOLUTION_CACHE.get(normalized_target)
    if cached_user_id:
        return True, "", cached_user_id

    def _retry_after_seconds(exc: SlackApiError, default: int = 2) -> int:
        try:
            headers = (exc.response or {}).headers  # type: ignore[attr-defined]
            value = (headers.get("Retry-After") or "").strip()
            if value.isdigit():
                return max(1, int(value))
        except Exception:
            pass
        return default

    try:
        cursor = None
        exact_matches: list[dict[str, Any]] = []
        partial_matches: list[dict[str, Any]] = []

        while True:
            response = None
            for attempt in range(4):
                try:
                    response = client.users_list(limit=200, cursor=cursor)
                    break
                except SlackApiError as exc:
                    error_code = ""
                    try:
                        error_code = (exc.response or {}).get("error", "")
                    except Exception:
                        error_code = ""

                    if error_code == "ratelimited" and attempt < 3:
                        wait_seconds = _retry_after_seconds(exc, default=(attempt + 1) * 2)
                        logger.warning(
                            "User lookup rate-limited; retrying in %ss (attempt %s/3)",
                            wait_seconds,
                            attempt + 1,
                        )
                        time.sleep(wait_seconds)
                        continue
                    raise

            if response is None:
                return False, "사용자 조회 실패: ratelimited (재시도 초과)", None

            for member in response.get("members") or []:
                if member.get("deleted") or member.get("is_bot"):
                    continue

                user_id = (member.get("id") or "").strip()
                profile = member.get("profile") or {}
                candidate_names = [
                    member.get("name") or "",
                    profile.get("display_name") or "",
                    profile.get("display_name_normalized") or "",
                    profile.get("real_name") or "",
                    profile.get("real_name_normalized") or "",
                ]

                normalized_candidates = {_normalize_name_token(name) for name in candidate_names if name}
                normalized_candidates.discard("")
                if not normalized_candidates:
                    continue

                if normalized_target in normalized_candidates:
                    exact_matches.append({"id": user_id, "name": profile.get("real_name") or member.get("name") or user_id})
                    continue

                if any(normalized_target in candidate or candidate in normalized_target for candidate in normalized_candidates):
                    partial_matches.append({"id": user_id, "name": profile.get("real_name") or member.get("name") or user_id})

            cursor = (response.get("response_metadata") or {}).get("next_cursor", "").strip()
            if not cursor:
                break

        if len(exact_matches) == 1:
            user_id = exact_matches[0]["id"]
            USER_RESOLUTION_CACHE[normalized_target] = user_id
            return True, "", user_id

        if len(exact_matches) > 1:
            candidates = ", ".join(f"<{m['id']}> {m['name']}" for m in exact_matches[:5])
            return False, f"동일 이름 사용자가 여러 명입니다. Slack 태그(<@U...>)로 지정해주세요. 후보: {candidates}", None

        if len(partial_matches) == 1:
            user_id = partial_matches[0]["id"]
            USER_RESOLUTION_CACHE[normalized_target] = user_id
            return True, "", user_id

        if len(partial_matches) > 1:
            candidates = ", ".join(f"<{m['id']}> {m['name']}" for m in partial_matches[:5])
            return False, f"유사 사용자명이 여러 명입니다. Slack 태그(<@U...>)로 지정해주세요. 후보: {candidates}", None

        return False, f"사용자 '{user_ref}'을 찾지 못했습니다. 사용자명 또는 @사용자명을 확인해주세요.", None
    except SlackApiError as exc:
        error_code = ""
        try:
            error_code = (exc.response or {}).get("error", "")
        except Exception:
            error_code = ""
        logger.exception("Failed to resolve user reference")
        return False, f"사용자 조회 실패: {error_code or 'unknown'}", None


def _looks_like_user_reference(text: str) -> bool:
    raw = (text or "").strip()
    if _extract_user_id_from_reference(raw):
        return True
    return raw.startswith("@") and len(_normalize_user_reference(raw)) >= 2


def _looks_like_delivery_target(text: str) -> bool:
    return _looks_like_channel_reference(text) or _looks_like_user_reference(text)


def _display_delivery_target(target_ref: str) -> str:
    user_id = _extract_user_id_from_reference(target_ref)
    if user_id:
        return f"<@{user_id}> DM"
    if (target_ref or "").strip().startswith("@"):
        return f"{target_ref.strip()} DM"
    return f"#{_normalize_channel_reference(target_ref)}"


def _extract_last_bot_message(recent_context: str) -> str:
    lines = [line.strip() for line in (recent_context or "").splitlines() if line.strip()]
    for line in reversed(lines):
        if line.startswith("봇:"):
            return line.split(":", 1)[-1].strip()
    return ""


def _extract_direct_send_request(text: str) -> Tuple[Optional[str], Optional[str], bool]:
    normalized = (text or "").strip()
    if not normalized:
        return None, None, False

    trigger_verbs = ["보내주세요", "전송해주세요", "발송해주세요", "보내줘", "전송해줘", "발송해줘", "보내", "전송", "발송"]
    trigger_index = -1
    trigger_verb = ""
    for verb in trigger_verbs:
        idx = normalized.find(verb)
        if idx != -1 and (trigger_index == -1 or idx < trigger_index or (idx == trigger_index and len(verb) > len(trigger_verb))):
            trigger_index = idx
            trigger_verb = verb

    if trigger_index == -1:
        return None, None, False

    body = normalized[:trigger_index].strip().rstrip(".?!, ")
    if not body:
        return None, None, True

    # Prefer quoted message if present.
    quoted_match = re.search(r'"([^"]+)"|“([^”]+)”|\'([^\']+)\'', body)
    quoted_message = ""
    if quoted_match:
        quoted_message = next((g for g in quoted_match.groups() if g), "").strip()

    channel_ref = ""
    remainder = body

    # 0) User mention target: <@U123...>
    tagged_user = re.search(r"<@([UW][A-Z0-9]{8,})>", remainder)
    if tagged_user:
        channel_ref = f"<@{(tagged_user.group(1) or '').strip()}>"
        remainder = re.sub(r"<@([UW][A-Z0-9]{8,})>\s*(에게|한테|에|으로|로)?", " ", remainder, count=1)

    # 0-1) Plain @display-name target: @홍길동님 / @username
    if not channel_ref and remainder.strip().startswith("@"):
        prefix = remainder.strip()
        plain_user = re.match(r"^(@.+?님)(?:\s*(에게|한테|에|으로|로))?(?:\s+|$)", prefix)
        if not plain_user:
            plain_user = re.match(r"^(@\S+)(?:\s*(에게|한테|에|으로|로))?(?:\s+|$)", prefix)

        if plain_user:
            user_text = (plain_user.group(1) or "").strip()
            if _normalize_user_reference(user_text):
                channel_ref = user_text
                remainder = prefix[len(plain_user.group(0)):].strip()

    # 1) Slack channel mention tag: <#C12345678|channel-name>
    tagged = re.search(r"<#([CGD][A-Z0-9]{8,})(?:\|[^>]+)?>", remainder)
    if tagged:
        channel_ref = (tagged.group(1) or "").strip()
        remainder = re.sub(r"<#([CGD][A-Z0-9]{8,})(?:\|[^>]+)?>\s*(에게|한테|에|으로|로)?", " ", remainder, count=1)

    # 2) [채널] notation
    if not channel_ref:
        bracket = re.search(r"\[([^\]]+)\]", remainder)
        if bracket:
            channel_ref = (bracket.group(1) or "").strip()
            remainder = re.sub(r"\[[^\]]+\]\s*(에게|한테|에|으로|로)?", " ", remainder, count=1)

    # 3) #channel notation
    if not channel_ref:
        hash_channel = re.search(r"#([\w\-가-힣]+)", remainder)
        if hash_channel:
            channel_ref = (hash_channel.group(1) or "").strip()
            remainder = re.sub(r"#[\w\-가-힣]+\s*(에게|한테|에|으로|로)?", " ", remainder, count=1)

    # 4) plain "채널" suffix notation: 콘텐츠-기획제작 채널
    if not channel_ref:
        named_channel = re.search(r"([\w\-가-힣]+)\s*채널", remainder)
        if named_channel:
            channel_ref = (named_channel.group(1) or "").strip()
            remainder = re.sub(r"[\w\-가-힣]+\s*채널\s*(에게|한테|에|으로|로)?", " ", remainder, count=1)

    # Fallback to legacy pattern if channel not found.
    if not channel_ref:
        channel_message_match = re.match(r"^(?P<channel>.+?)(?:에게|한테|에|으로|로)\s*(?P<message>.*)$", body)
        if channel_message_match:
            channel_ref = (channel_message_match.group("channel") or "").strip()
            remainder = (channel_message_match.group("message") or "").strip()
        else:
            # Try to identify channel in "message channel" format (most common user input order)
            # Channel names typically have hyphens or underscores; otherwise look at position
            words = body.split()
            if len(words) >= 2:
                # Check if the last word/phrase looks like a channel name (contains hyphen or underscore)
                last_phrase = " ".join(words[-2:]) if len(words) >= 2 else words[-1]
                if "-" in words[-1] or "_" in words[-1]:
                    # Last word looks like channel (has hyphen/underscore), treat it as channel
                    channel_ref = words[-1]
                    remainder = " ".join(words[:-1])
                else:
                    # Fall back to original "channel message" assumption
                    parts = body.split(maxsplit=1)
                    if len(parts) == 2:
                        channel_ref, remainder = parts[0].strip(), parts[1].strip()
                    else:
                        channel_ref = body.strip()
            else:
                channel_ref = body.strip()

    # Build message text from quoted content first, then remainder fallback.
    message_text = quoted_message or remainder
    message_text = re.sub(r"\s+", " ", message_text).strip()
    message_text = re.sub(r"^(메시지|문구|내용)\s*(를|을)?\s*", "", message_text).strip()
    message_text = re.sub(r"\s+(라고|고|라고도|라고는|라고만|에게|한테|을|를|이|가|에|에서|로|으로|에게서|한테서|처럼|같이|보다|마다|째)\s*$", "", message_text).strip()
    message_text = message_text.strip("\"'""` ")

    return channel_ref or None, message_text or None, True


def _format_direct_send_approval_text(channel_ref: str, message_text: str) -> str:
    return (
        f"다음 내용을 {_display_delivery_target(channel_ref)} 에 발송할까요?\n\n"
        f"*메시지*\n{message_text}\n\n"
        "진행하려면 `예`, 중단하려면 `아니오`라고 답해주세요."
    )


def _build_direct_send_approval_blocks(*, target_ref: str, message_text: str, pending_key: str) -> list[dict[str, Any]]:
    target_label = _display_delivery_target(target_ref)
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*발송 확인*\n다음 내용을 {target_label} 에 발송할까요?",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*메시지*\n{to_slack_format(message_text)}",
            },
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "발송"},
                    "action_id": "direct_send_approve",
                    "value": pending_key,
                    "style": "primary",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "취소"},
                    "action_id": "direct_send_reject",
                    "value": pending_key,
                    "style": "danger",
                },
            ],
        },
    ]


def _resolve_channel_reference(client, channel_ref: str) -> Tuple[bool, str, Optional[str]]:
    cleaned = _normalize_channel_reference(channel_ref)
    if not cleaned:
        return False, "대상 채널이 비어 있습니다.", None

    if re.fullmatch(r"[CGD][A-Z0-9]{8,}", cleaned):
        return True, "", cleaned

    exact_target = cleaned.lower()

    cached_id = CHANNEL_RESOLUTION_CACHE.get(exact_target)
    if cached_id:
        return True, "", cached_id

    def _retry_after_seconds(exc: SlackApiError, default: int = 2) -> int:
        try:
            headers = (exc.response or {}).headers  # type: ignore[attr-defined]
            value = (headers.get("Retry-After") or "").strip()
            if value.isdigit():
                return max(1, int(value))
        except Exception:
            pass
        return default

    try:
        cursor = None
        exact_matches: list[dict[str, Any]] = []
        loose_matches: list[dict[str, Any]] = []
        normalized_target = cleaned.lower().replace("_", "").replace("-", "")

        while True:
            response = None
            for attempt in range(4):
                try:
                    response = client.conversations_list(
                        types="public_channel,private_channel",
                        limit=200,
                        cursor=cursor,
                    )
                    break
                except SlackApiError as exc:
                    error_code = ""
                    try:
                        error_code = (exc.response or {}).get("error", "")
                    except Exception:
                        error_code = ""

                    if error_code == "ratelimited" and attempt < 3:
                        wait_seconds = _retry_after_seconds(exc, default=(attempt + 1) * 2)
                        logger.warning(
                            "Channel lookup rate-limited; retrying in %ss (attempt %s/3)",
                            wait_seconds,
                            attempt + 1,
                        )
                        time.sleep(wait_seconds)
                        continue
                    raise

            if response is None:
                return False, "채널 조회 실패: ratelimited (재시도 초과)", None

            for channel in response.get("channels") or []:
                raw_name = (channel.get("name") or "").strip()
                if not raw_name:
                    continue

                name_lower = raw_name.lower()
                if name_lower == exact_target:
                    exact_matches.append(channel)
                    continue

                # Backward-compatible loose matching path; used only if exact match is absent.
                normalized_name = name_lower.replace("_", "").replace("-", "")
                if normalized_name == normalized_target:
                    loose_matches.append(channel)

            cursor = (response.get("response_metadata") or {}).get("next_cursor", "").strip()
            if not cursor:
                break

        if len(exact_matches) == 1:
            channel_id = exact_matches[0]["id"]
            CHANNEL_RESOLUTION_CACHE[exact_target] = channel_id
            return True, "", channel_id

        if len(exact_matches) > 1:
            candidate_names = ", ".join(f"#{(c.get('name') or '').strip()}" for c in exact_matches[:5])
            return False, f"동일 이름 채널이 여러 개입니다. ID로 지정해주세요. 후보: {candidate_names}", None

        if len(loose_matches) == 1:
            channel_id = loose_matches[0]["id"]
            CHANNEL_RESOLUTION_CACHE[exact_target] = channel_id
            return True, "", channel_id

        if len(loose_matches) > 1:
            candidate_names = ", ".join(f"#{(c.get('name') or '').strip()}" for c in loose_matches[:5])
            return False, f"유사 채널명이 여러 개입니다. 정확한 채널명 또는 ID를 입력해주세요. 후보: {candidate_names}", None

        return False, f"채널 '{channel_ref}'을 찾지 못했습니다. 채널명 또는 #채널명을 확인해주세요.", None
    except SlackApiError as exc:
        error_code = ""
        try:
            error_code = (exc.response or {}).get("error", "")
        except Exception:
            error_code = ""

        if error_code == "missing_scope":
            return False, "채널 이름 확인을 위해 channels:read/groups:read scope가 필요합니다.", None

        logger.exception("Failed to resolve channel reference")
        return False, f"채널 조회 실패: {error_code or 'unknown'}", None


def _build_direct_send_prompt_state(
    *,
    user_id: str,
    channel_ref: str = "",
    message_text: str = "",
    awaiting: str = "",
) -> Dict[str, str]:
    return {
        "user_id": user_id,
        "channel_ref": channel_ref.strip(),
        "message_text": message_text.strip(),
        "awaiting": awaiting.strip(),
    }


def _ask_direct_send_followup(
    client,
    *,
    user_id: str,
    channel_id: str,
    prompt_text: str,
    channel_ref: str = "",
    message_text: str = "",
    awaiting: str,
) -> None:
    PENDING_DIRECT_SENDS[_pending_direct_send_key(user_id)] = _build_direct_send_prompt_state(
        user_id=user_id,
        channel_ref=channel_ref,
        message_text=message_text,
        awaiting=awaiting,
    )
    client.chat_postMessage(channel=channel_id, text=prompt_text)


def _build_workflow_approval_blocks(
    *,
    preview_text: str,
    target_channel: str,
    workflow_key: str,
) -> list[dict[str, Any]]:
    """Build Slack Block Kit elements for workflow approval with buttons + fallback text."""
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*1단계 완료: 검색 결과*\n\n{preview_text}",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*2단계로 #{target_channel} 에 위 내용을 발송할까요?*",
            },
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "발송"},
                    "action_id": "workflow_step_approve",
                    "value": workflow_key,
                    "style": "primary",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "취소"},
                    "action_id": "workflow_step_reject",
                    "value": workflow_key,
                    "style": "danger",
                },
            ],
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "💡 또는 채팅창에 `예` / `아니오` 입력해도 인식됩니다",
                }
            ],
        },
    ]


def _send_direct_message_to_channel(
    client,
    *,
    user_id: str,
    user_dm_channel_id: str,
    channel_ref: str,
    message_text: str,
) -> Tuple[bool, bool]:
    ok, error_message, target_channel_id = _resolve_channel_reference(client, channel_ref)
    if not ok or not target_channel_id:
        client.chat_postMessage(
            channel=user_dm_channel_id,
            text=f"전송 실패: {error_message}",
        )
        return False, "ratelimited" in (error_message or "")

    def _retry_after_seconds(exc: SlackApiError, default: int = 2) -> int:
        try:
            headers = (exc.response or {}).headers  # type: ignore[attr-defined]
            value = (headers.get("Retry-After") or "").strip()
            if value.isdigit():
                return max(1, int(value))
        except Exception:
            pass
        return default

    try:
        sent = False
        sent_channel_id = target_channel_id
        for attempt in range(4):
            try:
                send_resp = client.chat_postMessage(
                    channel=target_channel_id,
                    text=to_slack_format(message_text),
                )
                if not bool((send_resp or {}).get("ok", True)):
                    client.chat_postMessage(
                        channel=user_dm_channel_id,
                        text="전송 실패: Slack API 응답이 ok=false 입니다.",
                    )
                    return False, False
                sent = True
                break
            except SlackApiError as exc:
                error_code = ""
                try:
                    error_code = (exc.response or {}).get("error", "")
                except Exception:
                    error_code = ""

                if error_code == "ratelimited" and attempt < 3:
                    wait_seconds = _retry_after_seconds(exc, default=(attempt + 1) * 2)
                    logger.warning(
                        "Channel send rate-limited; retrying in %ss (attempt %s/3)",
                        wait_seconds,
                        attempt + 1,
                    )
                    time.sleep(wait_seconds)
                    continue
                raise

        if not sent:
            client.chat_postMessage(
                channel=user_dm_channel_id,
                text="전송 실패: ratelimited (재시도 초과). 잠시 후 `예`라고 다시 입력하면 같은 내용으로 재시도합니다.",
            )
            return False, True

        client.chat_postMessage(
            channel=user_dm_channel_id,
            text=f"전송 완료: <#{sent_channel_id}>에 메시지를 게시했습니다.",
        )
        return True, False
    except SlackApiError as exc:
        error_code = ""
        try:
            error_code = (exc.response or {}).get("error", "")
        except Exception:
            error_code = ""

        logger.exception("Direct channel send failed")
        client.chat_postMessage(
            channel=user_dm_channel_id,
            text=f"전송 실패: {error_code or exc}",
        )
        return False, error_code == "ratelimited"
    except Exception as exc:
        logger.exception("Direct channel send failed")
        client.chat_postMessage(
            channel=user_dm_channel_id,
            text=f"전송 실패: {exc}",
        )
        return False, False


def _send_direct_message_to_target(
    client,
    *,
    user_id: str,
    user_dm_channel_id: str,
    target_ref: str,
    message_text: str,
) -> Tuple[bool, bool]:
    """Send message to channel or user DM target.

    Returns (send_ok, retryable_failure).
    """
    target_user_id = _extract_user_id_from_reference(target_ref)
    if not target_user_id and _looks_like_user_reference(target_ref):
        ok, error_message, resolved_user_id = _resolve_user_reference(client, target_ref)
        if not ok or not resolved_user_id:
            client.chat_postMessage(
                channel=user_dm_channel_id,
                text=f"전송 실패: {error_message}",
            )
            return False, "ratelimited" in (error_message or "")
        target_user_id = resolved_user_id

    if not target_user_id:
        return _send_direct_message_to_channel(
            client,
            user_id=user_id,
            user_dm_channel_id=user_dm_channel_id,
            channel_ref=target_ref,
            message_text=message_text,
        )

    def _retry_after_seconds(exc: SlackApiError, default: int = 2) -> int:
        try:
            headers = (exc.response or {}).headers  # type: ignore[attr-defined]
            value = (headers.get("Retry-After") or "").strip()
            if value.isdigit():
                return max(1, int(value))
        except Exception:
            pass
        return default

    try:
        for attempt in range(4):
            try:
                open_result = client.conversations_open(users=[target_user_id])
                dm_channel_id = ((open_result.get("channel") or {}).get("id") or "").strip()
                if not dm_channel_id:
                    client.chat_postMessage(
                        channel=user_dm_channel_id,
                        text="전송 실패: 사용자 DM 채널을 열지 못했습니다.",
                    )
                    return False, False

                post_result = client.chat_postMessage(
                    channel=dm_channel_id,
                    text=to_slack_format(message_text),
                )
                if not bool((post_result or {}).get("ok", True)):
                    client.chat_postMessage(
                        channel=user_dm_channel_id,
                        text="전송 실패: Slack API 응답이 ok=false 입니다.",
                    )
                    return False, False

                client.chat_postMessage(
                    channel=user_dm_channel_id,
                    text=f"전송 완료: <@{target_user_id}> DM으로 메시지를 보냈습니다.",
                )
                return True, False
            except SlackApiError as exc:
                error_code = ""
                try:
                    error_code = (exc.response or {}).get("error", "")
                except Exception:
                    error_code = ""

                if error_code == "ratelimited" and attempt < 3:
                    wait_seconds = _retry_after_seconds(exc, default=(attempt + 1) * 2)
                    logger.warning(
                        "Direct DM send rate-limited; retrying in %ss (attempt %s/3)",
                        wait_seconds,
                        attempt + 1,
                    )
                    time.sleep(wait_seconds)
                    continue

                client.chat_postMessage(
                    channel=user_dm_channel_id,
                    text=f"전송 실패: {error_code or exc}",
                )
                return False, error_code == "ratelimited"

        client.chat_postMessage(
            channel=user_dm_channel_id,
            text="전송 실패: ratelimited (재시도 초과). 잠시 후 `예`라고 다시 입력하면 같은 내용으로 재시도합니다.",
        )
        return False, True
    except Exception as exc:
        logger.exception("Direct DM send failed")
        client.chat_postMessage(
            channel=user_dm_channel_id,
            text=f"전송 실패: {exc}",
        )
        return False, False


def _is_affirmative(text: str) -> bool:
    normalized = (text or "").strip().lower()
    return normalized in {"예", "네", "y", "yes", "진행", "진행해", "진행해주세요", "보내", "보내줘", "발송", "발송해", "승인"}


def _is_negative(text: str) -> bool:
    normalized = (text or "").strip().lower()
    return normalized in {"아니오", "아니요", "n", "no", "취소", "중단", "하지마", "멈춰"}


def _extract_search_then_send_request(text: str) -> Tuple[Optional[str], Optional[str], bool]:
    normalized = (text or "").strip()
    if not normalized:
        return None, None, False

    has_search_intent = bool(re.search(r"검색|찾아|리서치|조사", normalized))
    has_send_intent = bool(re.search(r"발송|보내|전송", normalized))
    if not (has_search_intent and has_send_intent):
        return None, None, False

    query = ""
    channel_ref = ""

    search_match = re.search(r"(검색(?:해)?(?:서)?|찾아(?:봐)?(?:서)?|리서치(?:해)?(?:서)?|조사(?:해)?(?:서)?)", normalized)
    if search_match:
        query = normalized[:search_match.start()].strip().rstrip(".?!, ")

    bracket_channel = re.search(r"\[([^\]]+)\]", normalized)
    if bracket_channel:
        channel_ref = (bracket_channel.group(1) or "").strip()
    else:
        channel_match = re.search(r"(#?[^\s\]]+)\s*(?:에|으로|로)\s*(?:발송|보내|전송)", normalized)
        if channel_match:
            channel_ref = (channel_match.group(1) or "").strip()

    return (query or None), (channel_ref or None), True


def _task_workflow_key(user_id: str) -> str:
    return user_id.strip()


def _start_search_then_send_workflow(
    client,
    *,
    user_id: str,
    user_dm_channel_id: str,
    search_query: Optional[str],
    channel_ref: Optional[str],
    recent_context: str,
) -> None:
    key = _task_workflow_key(user_id)

    query = (search_query or "").strip()
    channel = (channel_ref or "").strip()

    if not query:
        PENDING_TASK_WORKFLOWS[key] = {
            "type": "search_then_send",
            "awaiting": "query",
            "channel_ref": channel,
            "search_query": "",
            "message_text": "",
        }
        client.chat_postMessage(
            channel=user_dm_channel_id,
            text="1단계 검색을 위해 검색어를 알려주세요. 예: 오늘의 명언",
        )
        return

    if not channel:
        PENDING_TASK_WORKFLOWS[key] = {
            "type": "search_then_send",
            "awaiting": "channel",
            "channel_ref": "",
            "search_query": query,
            "message_text": "",
        }
        client.chat_postMessage(
            channel=user_dm_channel_id,
            text="검색 결과를 보낼 채널을 알려주세요. 예: [비공개채널]",
        )
        return

    status = client.chat_postMessage(channel=user_dm_channel_id, text="1단계 검색 중입니다...")
    status_ts = (status.get("ts") or "").strip()

    try:
        search_result_raw = _perplexity_chat_dm(query, recent_context=recent_context)
    except Exception as exc:
        logger.exception("search_then_send workflow: search failed")
        fail_text = f"검색 실패: {exc}"
        if status_ts:
            client.chat_update(channel=user_dm_channel_id, ts=status_ts, text=fail_text)
        else:
            client.chat_postMessage(channel=user_dm_channel_id, text=fail_text)
        return

    if not search_result_raw:
        fail_text = "검색 결과를 생성하지 못했습니다. 검색어를 바꿔 다시 시도해주세요."
        if status_ts:
            client.chat_update(channel=user_dm_channel_id, ts=status_ts, text=fail_text)
        else:
            client.chat_postMessage(channel=user_dm_channel_id, text=fail_text)
        return

    preview = to_slack_format(search_result_raw)
    normalized_channel = _normalize_channel_reference(channel)
    workflow_key = _task_workflow_key(user_id)
    
    # Build block-based approval message with button UI + text fallback
    blocks = _build_workflow_approval_blocks(
        preview_text=preview,
        target_channel=normalized_channel,
        workflow_key=workflow_key,
    )
    fallback_text = (
        f"1단계 완료: 검색 결과입니다.\n\n"
        f"{preview}\n\n"
        f"2단계로 #{normalized_channel} 에 위 내용을 발송할까요?\n"
        "진행하려면 버튼을 누르거나 `예`, 중단하려면 `아니오`라고 답해주세요."
    )

    if status_ts:
        client.chat_update(channel=user_dm_channel_id, ts=status_ts, text=fallback_text, blocks=blocks)
    else:
        client.chat_postMessage(channel=user_dm_channel_id, text=fallback_text, blocks=blocks)

    PENDING_TASK_WORKFLOWS[key] = {
        "type": "search_then_send",
        "awaiting": "approval_send",
        "channel_ref": channel,
        "search_query": query,
        "message_text": search_result_raw,
    }


def _handle_multi_step_workflow(
    client,
    *,
    user_id: str,
    user_dm_channel_id: str,
    text: str,
    recent_context: str,
) -> bool:
    """Handle multi-step workflows that require user approval between steps."""
    key = _task_workflow_key(user_id)
    workflow = PENDING_TASK_WORKFLOWS.get(key)

    if workflow:
        awaiting = (workflow.get("awaiting") or "").strip()
        channel_ref = (workflow.get("channel_ref") or "").strip()
        search_query = (workflow.get("search_query") or "").strip()
        message_text = (workflow.get("message_text") or "").strip()

        if awaiting == "query":
            search_query = text.strip()
            if not search_query:
                client.chat_postMessage(channel=user_dm_channel_id, text="검색어를 입력해주세요.")
                return True
            PENDING_TASK_WORKFLOWS.pop(key, None)
            _start_search_then_send_workflow(
                client,
                user_id=user_id,
                user_dm_channel_id=user_dm_channel_id,
                search_query=search_query,
                channel_ref=channel_ref,
                recent_context=recent_context,
            )
            return True

        if awaiting == "channel":
            candidate_query, candidate_channel, has_intent = _extract_search_then_send_request(text)
            if has_intent and candidate_channel:
                channel_ref = candidate_channel
                if candidate_query:
                    search_query = candidate_query
            elif _looks_like_channel_reference(text):
                channel_ref = text.strip().strip("[]")
            else:
                client.chat_postMessage(channel=user_dm_channel_id, text="채널명을 알려주세요. 예: [비공개채널]")
                return True

            if not channel_ref:
                client.chat_postMessage(channel=user_dm_channel_id, text="채널명을 확인해주세요. 예: [비공개채널]")
                return True

            PENDING_TASK_WORKFLOWS.pop(key, None)
            _start_search_then_send_workflow(
                client,
                user_id=user_id,
                user_dm_channel_id=user_dm_channel_id,
                search_query=search_query,
                channel_ref=channel_ref,
                recent_context=recent_context,
            )
            return True

        if awaiting == "approval_send":
            if _is_affirmative(text):
                send_ok, retryable = _send_direct_message_to_channel(
                    client,
                    user_id=user_id,
                    user_dm_channel_id=user_dm_channel_id,
                    channel_ref=channel_ref,
                    message_text=message_text,
                )
                if send_ok or not retryable:
                    PENDING_TASK_WORKFLOWS.pop(key, None)
                else:
                    # Keep workflow state so user can retry with "예" after cooldown.
                    PENDING_TASK_WORKFLOWS[key] = {
                        "type": "search_then_send",
                        "awaiting": "approval_send",
                        "channel_ref": channel_ref,
                        "search_query": search_query,
                        "message_text": message_text,
                    }
                return True

            if _is_negative(text):
                PENDING_TASK_WORKFLOWS.pop(key, None)
                client.chat_postMessage(channel=user_dm_channel_id, text="요청을 중단했습니다. 다른 작업을 말씀해주세요.")
                return True

            client.chat_postMessage(
                channel=user_dm_channel_id,
                text="다음 단계 진행 여부를 알려주세요. 진행은 `예`, 중단은 `아니오`로 답해주세요.",
            )
            return True

        # Unknown state fallback.
        PENDING_TASK_WORKFLOWS.pop(key, None)
        return False

    search_query, channel_ref, has_workflow_intent = _extract_search_then_send_request(text)
    if not has_workflow_intent:
        return False

    _start_search_then_send_workflow(
        client,
        user_id=user_id,
        user_dm_channel_id=user_dm_channel_id,
        search_query=search_query,
        channel_ref=channel_ref,
        recent_context=recent_context,
    )
    return True


def _handle_direct_send_request(
    client,
    *,
    user_id: str,
    user_dm_channel_id: str,
    text: str,
    recent_context: str,
) -> bool:
    """Detect and execute direct channel send requests from DM conversations."""
    pending_key = _pending_direct_send_key(user_id)
    pending = PENDING_DIRECT_SENDS.get(pending_key)

    if pending:
        channel_ref = (pending.get("channel_ref") or "").strip()
        message_text = (pending.get("message_text") or "").strip()
        awaiting = (pending.get("awaiting") or "").strip()

        # Accept follow-up channel name or message text depending on what is missing.
        if awaiting == "channel":
            candidate_channel_ref, candidate_message_text, has_send_intent = _extract_direct_send_request(text)
            if has_send_intent and candidate_channel_ref:
                channel_ref = candidate_channel_ref
                if candidate_message_text:
                    message_text = candidate_message_text
            elif _looks_like_delivery_target(text):
                channel_ref = text.strip()
            else:
                client.chat_postMessage(
                    channel=user_dm_channel_id,
                    text="어느 채널/사용자에게 보낼지 알려주세요. 예: 00채널 또는 <@U12345678>",
                )
                return True

        elif awaiting == "message":
            candidate_channel_ref, candidate_message_text, has_send_intent = _extract_direct_send_request(text)
            if has_send_intent and candidate_message_text:
                message_text = candidate_message_text
            elif text.strip():
                message_text = text.strip()
            else:
                client.chat_postMessage(
                    channel=user_dm_channel_id,
                    text="보낼 메시지를 입력해주세요.",
                )
                return True

        elif awaiting == "approval":
            # Check if user provided a new message for update
            candidate_channel_ref, candidate_message_text, has_send_intent = _extract_direct_send_request(text)
            if has_send_intent and candidate_message_text:
                # User provided new message - update and show new confirmation
                message_text = candidate_message_text
                PENDING_DIRECT_SENDS[pending_key] = _build_direct_send_prompt_state(
                    user_id=user_id,
                    channel_ref=channel_ref,
                    message_text=message_text,
                    awaiting="approval",
                )
                blocks = _build_direct_send_approval_blocks(
                    target_ref=channel_ref,
                    message_text=message_text,
                    pending_key=pending_key,
                )
                client.chat_postMessage(
                    channel=user_dm_channel_id,
                    text=_format_direct_send_approval_text(channel_ref, message_text),
                    blocks=blocks,
                )
                return True

            if _is_affirmative(text):
                send_ok, retryable = _send_direct_message_to_target(
                    client,
                    user_id=user_id,
                    user_dm_channel_id=user_dm_channel_id,
                    target_ref=channel_ref,
                    message_text=message_text,
                )
                if send_ok or not retryable:
                    PENDING_DIRECT_SENDS.pop(pending_key, None)
                else:
                    PENDING_DIRECT_SENDS[pending_key] = _build_direct_send_prompt_state(
                        user_id=user_id,
                        channel_ref=channel_ref,
                        message_text=message_text,
                        awaiting="approval",
                    )
                return True

            if _is_negative(text):
                PENDING_DIRECT_SENDS.pop(pending_key, None)
                client.chat_postMessage(channel=user_dm_channel_id, text="요청을 중단했습니다. 다른 작업을 말씀해주세요.")
                return True

            client.chat_postMessage(
                channel=user_dm_channel_id,
                text="발송 여부를 알려주세요. 진행은 `예`, 중단은 `아니오`로 답해주세요.",
            )
            return True

        if channel_ref and message_text:
            PENDING_DIRECT_SENDS[pending_key] = _build_direct_send_prompt_state(
                user_id=user_id,
                channel_ref=channel_ref,
                message_text=message_text,
                awaiting="approval",
            )
            blocks = _build_direct_send_approval_blocks(
                target_ref=channel_ref,
                message_text=message_text,
                pending_key=pending_key,
            )
            client.chat_postMessage(
                channel=user_dm_channel_id,
                text=_format_direct_send_approval_text(channel_ref, message_text),
                blocks=blocks,
            )
            return True

        PENDING_DIRECT_SENDS[pending_key] = _build_direct_send_prompt_state(
            user_id=user_id,
            channel_ref=channel_ref,
            message_text=message_text,
            awaiting="message" if channel_ref and not message_text else "channel",
        )
        if not channel_ref:
            client.chat_postMessage(
                channel=user_dm_channel_id,
                text="어느 채널/사용자에게 보낼지 알려주세요. 예: 00채널 또는 <@U12345678>",
            )
        else:
            client.chat_postMessage(
                channel=user_dm_channel_id,
                text="보낼 메시지를 입력해주세요.",
            )
        return True

    channel_ref, message_text, has_send_intent = _extract_direct_send_request(text)
    if not has_send_intent:
        return False

    if not message_text:
        message_text = _extract_last_bot_message(recent_context)

    if channel_ref and message_text:
        PENDING_DIRECT_SENDS[pending_key] = _build_direct_send_prompt_state(
            user_id=user_id,
            channel_ref=channel_ref,
            message_text=message_text,
            awaiting="approval",
        )
        blocks = _build_direct_send_approval_blocks(
            target_ref=channel_ref,
            message_text=message_text,
            pending_key=pending_key,
        )
        client.chat_postMessage(
            channel=user_dm_channel_id,
            text=_format_direct_send_approval_text(channel_ref, message_text),
            blocks=blocks,
        )
        return True

    if channel_ref and not message_text:
        PENDING_DIRECT_SENDS[pending_key] = _build_direct_send_prompt_state(
            user_id=user_id,
            channel_ref=channel_ref,
            message_text=message_text,
            awaiting="message",
        )
        client.chat_postMessage(
            channel=user_dm_channel_id,
            text=f"{channel_ref}에 보낼 메시지를 알려주세요. 예: 바로 보낼 문구를 입력해주세요.",
        )
        return True

    if message_text and not channel_ref:
        PENDING_DIRECT_SENDS[pending_key] = _build_direct_send_prompt_state(
            user_id=user_id,
            channel_ref="",
            message_text=message_text,
            awaiting="channel",
        )
        client.chat_postMessage(
            channel=user_dm_channel_id,
            text="어느 채널/사용자에게 보낼지 알려주세요. 예: 00채널 또는 <@U12345678>",
        )
        return True

    client.chat_postMessage(
        channel=user_dm_channel_id,
        text="어느 채널/사용자에게 어떤 메시지를 보낼지 알려주세요. 예: 00채널에 안녕하세요 보내줘 / <@U12345678>에게 안녕하세요 보내줘",
    )
    PENDING_DIRECT_SENDS[pending_key] = _build_direct_send_prompt_state(
        user_id=user_id,
        channel_ref="",
        message_text="",
        awaiting="channel",
    )
    return True


def _gemini_chat_dm(user_text: str, recent_context: str = "") -> Optional[str]:
    """Generate direct-message chat response for personal bot."""
    if not GEMINI_AVAILABLE:
        return None

    prompt_text = (user_text or "").strip()
    if not prompt_text:
        return None

    try:
        api_key = _required_env("GEMINI_API_KEY")
        client = genai.Client(api_key=api_key)
        prompt = (
            "너는 Slack 개인 비서 봇이다. "
            "한국어로 간결하고 실무적으로 답한다. "
            "불필요한 인삿말과 장황한 서론은 생략한다. "
            "필요할 때만 불릿을 사용한다.\n"
            "기본 말투는 당당한 어조로 문장 끝을 '~다!'로 맞춘다.\n"
            "기본 이모지 스타일은 문단 흐름에 맞춰 :hamster: 를 사용한다.\n"
            "최근 대화 맥락이 주어지면 우선 반영하여 연속된 대화처럼 답한다.\n\n"
            f"최근 대화:\n{recent_context or '(없음)'}\n\n"
            f"사용자 최신 메시지:\n{prompt_text}"
        )

        response = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=prompt,
            config=genai.types.GenerateContentConfig(
                max_output_tokens=420,
                temperature=0.4,
            ),
        )
        if response and response.text:
            return add_gom_emojis(response.text.strip())
    except Exception as e:
        logger.warning(f"Gemini DM chat failed: {e}")

    return None


def _perplexity_chat_dm(user_text: str, recent_context: str = "") -> str:
    """Generate DM response using Perplexity for search/research intent."""
    search_query = _extract_search_query(user_text)
    year_terms = _extract_year_terms(search_query)
    year_rule = ""
    if year_terms:
        year_rule = (
            "연도 제약이 포함되어 있으므로 해당 연도 조건을 최우선으로 검증한다. "
            "조건과 일치하는 결과가 없으면 없다고 명시하고, 임의로 다른 연도 작품 정보를 단정하지 않는다. "
            f"연도 제약: {', '.join(year_terms)}\n"
        )

    query = (
        "아래 키워드를 웹에서 검색해 사실 기반으로 요약한다. "
        "입력 키워드와 직접 관련된 정보만 다루고, 다른 주제로 임의 확장하지 않는다. "
        "동명이인/오타 가능성이 있으면 유사 키워드(영문명/한글명)를 함께 재탐색한다. "
        "확인 가능한 정보만 제시하고, 근거가 부족한 내용은 '미확인' 또는 '확인 불가'로 명시한다.\n"
        f"{year_rule}\n"
        f"검색 키워드:\n{search_query}\n\n"
        f"원문 요청:\n{user_text}"
    )

    return _perplexity_search(
        query,
        system_prompt=_perplexity_system_prompt_for_query(user_text, formatted=True),
        remove_citations=True,
        model_override="sonar-pro",
        apply_gom_style=False,
        format_for_slack_output=False,
    )


def _rewrite_reply_draft(original_message: str, instruction: str) -> Optional[str]:
    """Regenerate draft from original message by user instruction.

    This does not append changes to the previous draft; each rewrite is freshly generated
    from the source message and latest user instruction.
    """
    if not GEMINI_AVAILABLE:
        return None

    try:
        api_key = _required_env("GEMINI_API_KEY")
        client = genai.Client(api_key=api_key)
        prompt = (
            "아래 원문 메시지에 대한 답변을 사용자의 수정 지시대로 새로 작성해달라. "
            "직장인 업무 말투(존댓말, 간결, 실행 중심)로 유지한다. "
            "사용자 지시에 따라 문장 수를 조절한다. 별도 문장 수 제한은 없다.\n\n"
            "출력 규칙: 최종 답변 본문만 출력한다. "
            "'네, 알겠습니다', '수정된 답변:' 같은 메타 문구/설명/머리말은 절대 출력하지 않는다.\n\n"
            f"원문 메시지:\n{original_message}\n\n"
            f"수정 지시:\n{instruction}\n"
        )

        response = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=prompt,
            config=genai.types.GenerateContentConfig(
                max_output_tokens=520,
                temperature=0.4,
            ),
        )
        if response and response.text:
            reply_only = _extract_reply_only(response.text)
            return _limit_chars(reply_only, max_chars=1000)
    except Exception as e:
        logger.warning(f"Gemini rewrite failed: {e}")

    return None


def _reply_pending_key(user_id: str, channel_id: str) -> str:
    return f"{user_id}:{channel_id}"


def _is_valid_reply_choice(choice: str) -> bool:
    return choice in ("예", "아니오", "대기")


def _generate_reply_draft(
    *,
    client,
    message_link: str,
    choice: str,
    context: str,
) -> Tuple[bool, str, Optional[Dict[str, str]]]:
    """Generate and post a reply draft to the target message thread."""
    channel_id, message_ts = _parse_message_link(message_link)
    if not channel_id or not message_ts:
        return False, "메시지 링크가 유효하지 않습니다. 올바른 형식: https://workspace.slack.com/archives/CXXXXXX/pXXXXXX", None

    try:
        result = client.conversations_history(
            channel=channel_id,
            latest=message_ts,
            limit=1,
            inclusive=True,
        )
        if not result.get("messages"):
            return False, f"메시지를 찾을 수 없습니다. (채널: {channel_id}, 시간: {message_ts})", None

        original_message = result["messages"][0].get("text", "")
        if not original_message:
            return False, "원본 메시지의 내용을 불러올 수 없습니다.", None
    except SlackApiError as exc:
        error_code = ""
        try:
            error_code = (exc.response or {}).get("error", "")
        except Exception:
            error_code = ""

        if error_code == "channel_not_found":
            return (
                False,
                "메시지 조회 실패: 지정한 대화방에 봇이 접근할 수 없습니다. "
                "DM/비공개 채널은 봇이 참여한 대화에서만 조회 가능합니다. "
                "해당 대화방에 봇을 초대하거나, 봇과의 DM에서 다시 시도해주세요.",
                None,
            )

        if error_code == "not_in_channel":
            return (
                False,
                "메시지 조회 실패: 봇이 해당 채널에 참여되어 있지 않습니다. "
                "채널에 봇을 초대한 뒤 다시 시도해주세요.",
                None,
            )

        if error_code == "missing_scope":
            return (
                False,
                "메시지 조회 실패: Slack 권한(scope)이 부족합니다. "
                "`channels:history` 및 private/DM 사용 시 관련 scope를 확인해주세요.",
                None,
            )

        logger.exception("Slack API error while fetching message")
        return False, f"메시지 조회 실패: Slack API 오류({error_code or 'unknown'})", None
    except Exception as exc:
        logger.exception("Failed to fetch message from Slack")
        return False, f"메시지 조회 실패: {exc}", None

    reply_draft = _gemini_generate_reply(original_message, choice, context)
    if not reply_draft:
        return False, "Gemini API 응답 생성에 실패했습니다. API 키/모델/권한을 확인하세요.", None

    reply_text = to_slack_format(reply_draft)

    try:
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=message_ts,
            reply_broadcast=True,
            text=reply_text,
        )
    except Exception as exc:
        logger.exception("Failed to post reply to thread")
        return False, f"Thread에 답변을 작성하지 못했습니다: {exc}", None

    return (
        True,
        "✓ 답변 초안이 thread에 작성되었습니다.\n"
        "채널에도 함께 게시되었습니다 (reply_broadcast=true).\n"
        f"API: Google Gemini API (google.genai) | 모델: gemini-2.5-flash-lite\n"
        "응답 스타일: 직장인 업무 말투(존댓말/간결/실행 중심)\n"
        "문장 제한: 최대 3문장\n"
        f"선택: {choice} | 추가 맥락: {context or '없음'}",
        {
            "draft": reply_draft,
            "channel_id": channel_id,
            "message_ts": message_ts,
        },
    )


def _perplexity_search(
    query: str,
    system_prompt: str = SYSTEM_PROMPT_PSEARCH,
    remove_citations: bool = True,
    model_override: Optional[str] = None,
    apply_gom_style: bool = True,
    force_single_line: bool = False,
    format_for_slack_output: bool = True,
) -> str:
    """Call Perplexity API with optional citation removal."""
    api_key = _required_env("PERPLEXITY_API_KEY")
    
    # Select model from explicit override first, then auto-routing.
    model = model_override or select_perplexity_model(query)

    payload: Dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": query},
        ],
        "temperature": 0.2,
    }

    logger.info("Perplexity request dispatched: model=%s query_preview=%s", model, _clip_text(query, 120))

    response = requests.post(
        PERPLEXITY_API_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=45,
    )
    response.raise_for_status()

    data = response.json()
    content = (
        data.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
        .strip()
    )
    if not content:
        return "검색 결과를 생성하지 못했습니다."

    # Remove citation marks if requested
    if remove_citations:
        content = _remove_citation_marks(content)

    if force_single_line:
        content = _to_single_line(content)

    # Apply default personal style markers to generic responses.
    if apply_gom_style:
        content = add_gom_emojis(content)

    # Format for Slack (markdown → Slack format) when requested.
    if format_for_slack_output:
        content = to_slack_format(content)

    # Slack text limit guard.
    return content[:2800]


def _wrap_guarded_handler(handler):
    """Wrap a Slack handler with allowlist enforcement."""
    def wrapped(*args, **kwargs):
        # Extract payload from various possible positions
        payload = kwargs.get("command") or kwargs.get("body")
        if payload is None and len(args) > 1 and isinstance(args[1], dict):
            payload = args[1]

        allowed, reason = _is_payload_allowed(payload or {})
        if not allowed:
            # If not allowed, get ack and respond to reject the command
            ack = kwargs.get("ack")
            if callable(ack):
                try:
                    ack(reason)
                except TypeError:
                    ack()
            
            respond = kwargs.get("respond")
            if callable(respond):
                respond(reason)
            return

        # If allowed, call the actual handler
        return handler(*args, **kwargs)

    return wrapped


def _install_registration_guards(app: App) -> None:
    """Ensure future commands/shortcuts are auto-wrapped with the allowlist."""
    # This approach was causing issues with the ack() callback
    # Will use explicit allowlist checks in each handler instead
    pass


def build_app() -> App:
    bot_token = _required_env("SLACK_BOT_TOKEN")
    signing_secret = _required_env("SLACK_SIGNING_SECRET")

    app = App(token=bot_token, signing_secret=signing_secret)
    # Allowlist checks are now done explicitly in each handler

    @app.command("/psearch")
    def handle_psearch(ack, command, respond, logger):
        ack("검색 중입니다...")

        # Allowlist check
        allowed, reason = _is_command_allowed(command)
        if not allowed:
            respond(reason)
            return

        raw_text = (command.get("text") or "").strip()
        query, forced_model = parse_psearch_input(raw_text)
        if not query:
            respond("질문을 입력하세요. 예: /psearch reasoning-pro 팀봇 장애 분석")
            return

        try:
            result = _perplexity_search(
                query,
                system_prompt=_perplexity_system_prompt_for_query(query, formatted=True),
                remove_citations=True,
                model_override=forced_model,
                apply_gom_style=False,
            )
            respond(result)
        except requests.HTTPError as exc:
            logger.exception("Perplexity API HTTP error")
            respond(f"Perplexity API 오류: {exc.response.status_code}")
        except Exception as exc:
            logger.exception("/psearch failed")
            respond(f"검색 실패: {exc}")

    @app.command("/usdtw")
    def handle_usdtw(ack, command, respond, logger):
        ack("환율 조회 중입니다...")

        # Allowlist check
        allowed, reason = _is_command_allowed(command)
        if not allowed:
            respond(reason)
            return

        try:
            raw_text = (command.get("text") or "").strip()
            amount, currency_code, currency_label = _parse_usdtw_input(raw_text)

            # Conversion mode: /usdtw 0.1, /usdtw 1달러, /usdtw 10 eur
            if amount is not None:
                amount_text = _format_amount(amount)
                query = (
                    f"현재 환율 기준으로 {amount} {currency_code}를 KRW로 환산하세요. "
                    f"반드시 한 줄로만 출력하고, 정확히 다음 형식으로 답하세요: "
                    f"지금 기준으로 {amount_text}{currency_label}는 약 NNN원이다! :hamster: "
                    "추가 설명, 출처, 줄바꿈을 포함하지 마세요."
                )
                result = _perplexity_search(
                    query,
                    system_prompt=SYSTEM_PROMPT_USDTW + "\n금융/환율 질문은 Perplexity Finance 데이터베이스를 최우선으로 활용한다.",
                    remove_citations=True,
                    model_override="sonar-pro",
                    apply_gom_style=False,
                    force_single_line=True,
                )
                respond(result)
                return

            # 환율 조회 프롬프트
            query = (
                "현재 미화-원화 환율을 알려주세요. "
                "지금 기준으로 1달러는 약 00원입니다. 의 형식으로 시작하고, "
                "최근 6개월 환율 흐름을 고려하여 현재 시점이 저점인지 고점인지 한줄 의견을 추가하세요."
            )
            result = _perplexity_search(
                query,
                system_prompt=SYSTEM_PROMPT_USDTW + "\n금융/환율 질문은 Perplexity Finance 데이터베이스를 최우선으로 활용한다.",
                remove_citations=True,
                model_override="sonar-pro",
            )
            respond(result)
        except requests.HTTPError as exc:
            logger.exception("Perplexity API HTTP error")
            respond(f"Perplexity API 오류: {exc.response.status_code}")
        except Exception as exc:
            logger.exception("/usdtw failed")
            respond(f"환율 조회 실패: {exc}")

    @app.command("/reply")
    def handle_reply_command(ack, command, respond, client, logger):
        """Create reply draft from thread context and deliver it to DM with actions.

        Preferred:
        - Run /reply inside target thread.

        Fallback:
        - /reply <message_link>
        """
        ack("답변 초안을 생성 중입니다...")

        allowed, reason = _is_command_allowed(command)
        if not allowed:
            respond(reason)
            return

        try:
            user_id = (command.get("user_id") or "").strip()
            channel_id = (command.get("channel_id") or "").strip()
            raw_text = (command.get("text") or "").strip()
            thread_ts = (command.get("thread_ts") or "").strip()
            command_ts = (command.get("command_ts") or "").strip()
            response_url_present = bool((command.get("response_url") or "").strip())

            logger.info(
                "/reply payload snapshot: user_id=%s channel_id=%s thread_ts=%s command_ts=%s text_len=%s response_url=%s",
                user_id or "<empty>",
                channel_id or "<empty>",
                thread_ts or "<empty>",
                command_ts or "<empty>",
                len(raw_text),
                response_url_present,
            )

            source_channel_id = channel_id
            source_ts = thread_ts

            # Optional fallback for non-thread usage: /reply <message_link>
            if raw_text:
                first_token = raw_text.split(maxsplit=1)[0]
                maybe_channel, maybe_ts = _parse_message_link(first_token)
                if maybe_channel and maybe_ts:
                    source_channel_id = maybe_channel
                    source_ts = maybe_ts

            if not source_channel_id or not source_ts:
                logger.warning(
                    "/reply missing required context: source_channel_id=%s source_ts=%s raw_text=%s",
                    source_channel_id or "<empty>",
                    source_ts or "<empty>",
                    raw_text or "<empty>",
                )
                respond(
                    "자동 답변 초안 생성을 할 수 없습니다.\n"
                    "답변하고 싶은 메시지 스레드에서 `/reply`를 다시 실행하거나,\n"
                    "`/reply <message_link>` 형식으로 입력해주세요."
                )
                return

            ok, error_message, original_message = _fetch_reply_source_message(
                client,
                source_channel_id=source_channel_id,
                source_ts=source_ts,
            )
            if not ok:
                respond(f"자동 답변 초안 생성을 할 수 없습니다.\n{error_message}")
                return

            ok, error_message, reply_draft = _build_reply_draft_common(original_message or "")
            if not ok:
                respond(error_message)
                return

            # Open DM and build session for edit/send buttons.
            dm_result = client.conversations_open(users=[user_id])
            dm_channel_id = dm_result["channel"]["id"]

            source_permalink = ""
            try:
                link_result = client.chat_getPermalink(channel=source_channel_id, message_ts=source_ts)
                source_permalink = (link_result.get("permalink") or "").strip()
            except Exception:
                source_permalink = ""

            session = _create_reply_shortcut_session(
                user_id=user_id,
                dm_channel_id=dm_channel_id,
                source_channel_id=source_channel_id,
                source_ts=source_ts,
                source_permalink=source_permalink,
                original_message=original_message,
                current_draft=reply_draft,
            )
            _post_reply_shortcut_dm(client, session)

            respond("DM으로 초안을 전송했습니다. DM에서 수정/발송 버튼으로 이어서 진행해주세요.")
        except Exception as exc:
            logger.exception(f"/reply command failed: {exc}")
            respond("자동 답변 초안 생성을 할 수 없습니다. 잠시 후 다시 시도해주세요.")

    @app.command("/summary")
    def handle_summary(ack, command, respond, client, logger):
        ack("요약 중입니다...")

        allowed, reason = _is_command_allowed(command)
        if not allowed:
            respond(reason)
            return

        raw_text = (command.get("text") or "").strip()
        if not raw_text:
            respond("요약할 내용을 입력하세요. 예: /summary 이번 주 회의 내용 ...")
            return

        source_text = raw_text
        link = _extract_first_slack_message_link(raw_text)
        if link:
            ok, error_message, linked_text = _fetch_summary_source_from_link(client, link)
            if not ok:
                respond(f"요약 생성에 실패했습니다. {error_message}")
                return
            source_text = linked_text or raw_text

        summary = _gemini_generate_summary(source_text)
        if not summary:
            respond("요약 생성에 실패했습니다. 잠시 후 다시 시도해주세요.")
            return

        respond(to_slack_format(summary))

    @app.event("message")
    def handle_dm_free_chat_events(event, say, client, logger):
        """Handle free-text conversations in DM channel (message.im)."""
        if not DM_CHAT_ENABLED:
            return

        try:
            channel_id = (event.get("channel") or "").strip()
            channel_type = (event.get("channel_type") or "").strip()
            user_id = (event.get("user") or "").strip()
            text = (event.get("text") or "").strip()
            subtype = (event.get("subtype") or "").strip()

            # Ignore non-DM channels, bot/system messages, and empty text.
            if channel_type != "im" and not channel_id.startswith("D"):
                return
            if subtype or not user_id or not text:
                return

            allowed, _ = _is_payload_allowed({"user_id": user_id, "channel_id": channel_id})
            if not allowed:
                return

            # Slash commands are handled separately by command handlers.
            if text.startswith("/"):
                return

            recent_context = _build_recent_dm_context(
                client,
                channel_id=channel_id,
                latest_ts=(event.get("ts") or "").strip(),
                requester_user_id=user_id,
            )

            if _handle_multi_step_workflow(
                client,
                user_id=user_id,
                user_dm_channel_id=channel_id,
                text=text,
                recent_context=recent_context,
            ):
                return

            if _handle_direct_send_request(
                client,
                user_id=user_id,
                user_dm_channel_id=channel_id,
                text=text,
                recent_context=recent_context,
            ):
                return

            use_search_engine = _looks_like_search_request(text)
            status_text = "검색 중입니다..." if use_search_engine else "답변 생성 중입니다..."

            status_ts = ""
            try:
                status_msg = client.chat_postMessage(
                    channel=channel_id,
                    text=status_text,
                )
                status_ts = (status_msg.get("ts") or "").strip()
            except Exception:
                status_ts = ""

            if use_search_engine:
                reply = _perplexity_chat_dm(text, recent_context=recent_context)
            else:
                reply = _gemini_chat_dm(text, recent_context=recent_context)
            if not reply:
                fail_text = "답변 생성에 실패했습니다. 잠시 후 다시 시도해주세요."
                if status_ts:
                    client.chat_update(channel=channel_id, ts=status_ts, text=fail_text)
                else:
                    say(fail_text)
                return

            final_text = to_slack_format(reply)
            if status_ts:
                client.chat_update(channel=channel_id, ts=status_ts, text=final_text)
            else:
                say(final_text)
        except Exception as exc:
            logger.exception(f"DM free chat handler failed: {exc}")

    @app.event("app_mention")
    def handle_public_mention(event, client, logger):
        """Public channel reply handler - only when bot is mentioned."""
        try:
            channel_id = (event.get("channel") or "").strip()
            user_id = (event.get("user") or "").strip()
            raw_text = (event.get("text") or "").strip()
            event_ts = (event.get("ts") or "").strip()
            thread_ts = (event.get("thread_ts") or "").strip()
            subtype = (event.get("subtype") or "").strip()

            if subtype or not channel_id or not user_id or not raw_text:
                return

            allowed, _ = _is_payload_allowed({"user_id": user_id, "channel_id": channel_id})
            if not allowed:
                return

            # Remove mention tokens from user prompt text.
            prompt_text = re.sub(r"<@[^>]+>", "", raw_text).strip()
            if not prompt_text:
                client.chat_postMessage(
                    channel=channel_id,
                    text=f"<@{user_id}> 질문을 함께 입력해주세요.",
                    thread_ts=thread_ts or None,
                    reply_broadcast=bool(thread_ts),
                )
                return

            recent_context = _build_recent_channel_context(
                client,
                channel_id=channel_id,
                latest_ts=event_ts,
                requester_user_id=user_id,
            )

            use_search_engine = _looks_like_search_request(prompt_text)
            status_text = "검색 중입니다..." if use_search_engine else "답변 생성 중입니다..."

            status_msg = client.chat_postMessage(
                channel=channel_id,
                text=f"<@{user_id}> {status_text}",
                thread_ts=thread_ts or None,
                reply_broadcast=bool(thread_ts),
            )
            status_ts = (status_msg.get("ts") or "").strip()

            if use_search_engine:
                reply = _perplexity_chat_dm(prompt_text, recent_context=recent_context)
            else:
                reply = _gemini_chat_dm(prompt_text, recent_context=recent_context)

            if not reply:
                client.chat_update(
                    channel=channel_id,
                    ts=status_ts,
                    text=f"<@{user_id}> 답변 생성에 실패했습니다. 잠시 후 다시 시도해주세요.",
                )
                return

            client.chat_update(
                channel=channel_id,
                ts=status_ts,
                text=f"<@{user_id}> {to_slack_format(reply)}",
            )
        except Exception as exc:
            logger.exception(f"Public mention handler failed: {exc}")

    @app.shortcut("reply_draft_short")
    @app.shortcut("reply_draft_shortcut")
    def handle_reply_shortcut(ack, shortcut, client, logger):
        """Generate reply draft via message shortcut (right-click menu).
        
        Shortcut IDs: reply_draft_short (primary), reply_draft_shortcut (legacy)
        The draft is sent to the user's DM only (not broadcast to channel).
        """
        ack()

        # Allowlist check
        allowed, reason = _is_payload_allowed(shortcut or {})
        if not allowed:
            logger.warning(f"Shortcut blocked: {reason}")
            return

        try:
            user_id = (shortcut.get("user", {}).get("id") or "").strip()
            if not user_id:
                logger.error("No user_id in shortcut payload")
                return

            # Extract message info from shortcut payload
            message_obj = shortcut.get("message", {})
            payload_message_text = (message_obj.get("text") or "").strip()
            source_ts = (message_obj.get("ts") or "").strip()
            source_channel_id = (shortcut.get("channel", {}).get("id") or "").strip()
            if not source_channel_id and not payload_message_text:
                logger.error("No usable source in shortcut payload")
                return

            ok, error_message, original_message = _fetch_reply_source_message(
                client,
                source_channel_id=source_channel_id,
                source_ts=source_ts,
                fallback_text=payload_message_text,
            )
            if not ok:
                logger.warning(f"Shortcut source fetch failed: {error_message}")
                return

            ok, error_message, reply_draft = _build_reply_draft_common(original_message or "")
            if not ok:
                logger.warning(f"Shortcut draft generation failed: {error_message}")
                return

            # Open DM channel with user
            try:
                dm_result = client.conversations_open(users=[user_id])
                dm_channel_id = dm_result["channel"]["id"]
            except Exception as exc:
                logger.exception("Failed to open DM channel")
                return

            # Build optional permalink for quick jump to source message.
            source_permalink = ""
            if source_channel_id and source_ts:
                try:
                    link_result = client.chat_getPermalink(channel=source_channel_id, message_ts=source_ts)
                    source_permalink = (link_result.get("permalink") or "").strip()
                except Exception:
                    source_permalink = ""

            session = _create_reply_shortcut_session(
                user_id=user_id,
                dm_channel_id=dm_channel_id,
                source_channel_id=source_channel_id,
                source_ts=source_ts,
                source_permalink=source_permalink,
                original_message=original_message,
                current_draft=reply_draft,
            )

            # Send draft to user's DM only
            try:
                _post_reply_shortcut_dm(client, session)
                logger.info(f"Reply draft sent to user {user_id} via DM")
            except Exception as exc:
                logger.exception(f"Failed to post message to DM: {exc}")
                return

        except Exception as exc:
            logger.exception(f"Reply shortcut handler failed: {exc}")

    @app.action("reply_draft_edit")
    def handle_reply_draft_edit(ack, body, client, logger):
        ack()
        try:
            action = (body.get("actions") or [{}])[0]
            session_id = (action.get("value") or "").strip()
            session = REPLY_SHORTCUT_SESSIONS.get(session_id)
            if not session:
                return

            user_id = (body.get("user", {}).get("id") or "").strip()
            if user_id != session.get("user_id"):
                return

            trigger_id = (body.get("trigger_id") or "").strip()
            if not trigger_id:
                return

            client.views_open(
                trigger_id=trigger_id,
                view={
                    "type": "modal",
                    "callback_id": "reply_draft_edit_modal",
                    "private_metadata": json.dumps({"session_id": session_id}, ensure_ascii=False),
                    "title": {"type": "plain_text", "text": "초안 수정"},
                    "submit": {"type": "plain_text", "text": "수정 적용"},
                    "close": {"type": "plain_text", "text": "취소"},
                    "blocks": [
                        {
                            "type": "input",
                            "block_id": "instruction_block",
                            "label": {"type": "plain_text", "text": "수정 지시"},
                            "element": {
                                "type": "plain_text_input",
                                "action_id": "instruction_input",
                                "multiline": True,
                                "placeholder": {
                                    "type": "plain_text",
                                    "text": "예: 더 공손하게, 일정 제안 포함, 2문장으로 줄여줘",
                                },
                            },
                        }
                    ],
                },
            )
        except Exception as exc:
            logger.exception(f"reply_draft_edit action failed: {exc}")

    @app.view("reply_draft_edit_modal")
    def handle_reply_draft_edit_modal(ack, body, view, client, logger):
        ack()
        try:
            metadata_raw = (view.get("private_metadata") or "{}").strip()
            metadata = json.loads(metadata_raw)
            session_id = (metadata.get("session_id") or "").strip()
            session = REPLY_SHORTCUT_SESSIONS.get(session_id)
            if not session:
                return

            user_id = (body.get("user", {}).get("id") or "").strip()
            if user_id != session.get("user_id"):
                return

            state_values = view.get("state", {}).get("values", {})
            instruction = (
                state_values.get("instruction_block", {})
                .get("instruction_input", {})
                .get("value", "")
                .strip()
            )
            if not instruction:
                client.chat_postMessage(
                    channel=session["dm_channel_id"],
                    text="수정 지시가 비어 있어 기존 초안을 유지했습니다.",
                )
                return

            rewritten = _rewrite_reply_draft(session.get("original_message", ""), instruction)
            if not rewritten:
                client.chat_postMessage(
                    channel=session["dm_channel_id"],
                    text="초안 수정에 실패했습니다. 잠시 후 다시 시도해주세요.",
                )
                return

            session["current_draft"] = rewritten
            REPLY_SHORTCUT_SESSIONS[session_id] = session
            _post_reply_shortcut_dm(client, session)
        except Exception as exc:
            logger.exception(f"reply_draft_edit_modal failed: {exc}")

    @app.action("workflow_step_approve")
    def handle_workflow_step_approve(ack, body, client, logger):
        """Button-based approval of workflow step."""
        ack()
        try:
            user_id = (body.get("user", {}).get("id") or "").strip()
            workflow_key = (body.get("actions", [{}])[0].get("value") or "").strip()
            dm_channel_id = (body.get("channel", {}).get("id") or "").strip()
            
            if not user_id or not workflow_key:
                return
                
            # Reuse existing approval logic by simulating affirmative text input
            _handle_multi_step_workflow(
                client,
                user_id=user_id,
                user_dm_channel_id=dm_channel_id,
                text="예",  # Simulate user affirming approval
                recent_context="",
            )
        except Exception as exc:
            logger.exception(f"workflow_step_approve action failed: {exc}")

    @app.action("workflow_step_reject")
    def handle_workflow_step_reject(ack, body, client, logger):
        """Button-based rejection of workflow step."""
        ack()
        try:
            user_id = (body.get("user", {}).get("id") or "").strip()
            workflow_key = (body.get("actions", [{}])[0].get("value") or "").strip()
            dm_channel_id = (body.get("channel", {}).get("id") or "").strip()
            
            if not user_id or not workflow_key:
                return
                
            # Reuse existing rejection logic by simulating negative text input
            _handle_multi_step_workflow(
                client,
                user_id=user_id,
                user_dm_channel_id=dm_channel_id,
                text="아니오",  # Simulate user rejecting approval
                recent_context="",
            )
        except Exception as exc:
            logger.exception(f"workflow_step_reject action failed: {exc}")

    @app.action("direct_send_approve")
    def handle_direct_send_approve(ack, body, client, logger):
        """Button-based approval for direct send flow."""
        ack()
        try:
            user_id = (body.get("user", {}).get("id") or "").strip()
            pending_key = (body.get("actions", [{}])[0].get("value") or "").strip() or _pending_direct_send_key(user_id)
            dm_channel_id = (body.get("channel", {}).get("id") or "").strip()
            pending = PENDING_DIRECT_SENDS.get(pending_key)
            if not user_id or not dm_channel_id or not pending:
                return

            if (pending.get("awaiting") or "").strip() != "approval":
                return

            target_ref = (pending.get("channel_ref") or "").strip()
            message_text = (pending.get("message_text") or "").strip()
            if not target_ref or not message_text:
                return

            send_ok, retryable = _send_direct_message_to_target(
                client,
                user_id=user_id,
                user_dm_channel_id=dm_channel_id,
                target_ref=target_ref,
                message_text=message_text,
            )
            if send_ok or not retryable:
                PENDING_DIRECT_SENDS.pop(pending_key, None)
            else:
                PENDING_DIRECT_SENDS[pending_key] = _build_direct_send_prompt_state(
                    user_id=user_id,
                    channel_ref=target_ref,
                    message_text=message_text,
                    awaiting="approval",
                )
        except Exception as exc:
            logger.exception(f"direct_send_approve action failed: {exc}")

    @app.action("direct_send_reject")
    def handle_direct_send_reject(ack, body, client, logger):
        """Button-based rejection for direct send flow."""
        ack()
        try:
            user_id = (body.get("user", {}).get("id") or "").strip()
            pending_key = (body.get("actions", [{}])[0].get("value") or "").strip() or _pending_direct_send_key(user_id)
            dm_channel_id = (body.get("channel", {}).get("id") or "").strip()
            if not user_id or not dm_channel_id:
                return

            PENDING_DIRECT_SENDS.pop(pending_key, None)
            client.chat_postMessage(channel=dm_channel_id, text="요청을 중단했습니다. 다른 작업을 말씀해주세요.")
        except Exception as exc:
            logger.exception(f"direct_send_reject action failed: {exc}")

    @app.action("reply_draft_send")
    def handle_reply_draft_send(ack, body, client, logger):
        ack()
        try:
            action = (body.get("actions") or [{}])[0]
            session_id = (action.get("value") or "").strip()
            session = REPLY_SHORTCUT_SESSIONS.get(session_id)
            if not session:
                return

            user_id = (body.get("user", {}).get("id") or "").strip()
            if user_id != session.get("user_id"):
                return

            dm_channel_id = session.get("dm_channel_id", "")
            status_ts = ""
            if dm_channel_id:
                try:
                    status_msg = client.chat_postMessage(
                        channel=dm_channel_id,
                        text="발송 중입니다...",
                    )
                    status_ts = (status_msg.get("ts") or "").strip()
                except Exception:
                    status_ts = ""

            source_channel_id = session.get("source_channel_id", "")
            source_ts = session.get("source_ts", "")
            draft = to_slack_format(
                _extract_reply_only(_limit_chars(session.get("current_draft", ""), max_chars=1000))
            )
            if not source_channel_id or not source_ts or not draft:
                fail_text = "발송 실패: 발송에 필요한 원문 정보가 부족합니다. shortcut을 다시 실행해주세요."
                if dm_channel_id and status_ts:
                    client.chat_update(channel=dm_channel_id, ts=status_ts, text=fail_text)
                elif dm_channel_id:
                    client.chat_postMessage(channel=dm_channel_id, text=fail_text)
                return

            try:
                client.chat_postMessage(
                    channel=source_channel_id,
                    thread_ts=source_ts,
                    reply_broadcast=False,
                    text=draft,
                )
            except SlackApiError as exc:
                error_code = ""
                try:
                    error_code = (exc.response or {}).get("error", "")
                except Exception:
                    error_code = ""

                if error_code in ("channel_not_found", "not_in_channel", "missing_scope"):
                    is_dm_like = source_channel_id.startswith("D") or source_channel_id.startswith("G")
                    if is_dm_like:
                        fail_text = (
                            "발송 실패: 원문 대화방에 봇이 참여되어 있지 않아 자동 발송할 수 없습니다. "
                            "상단 초안을 복사해 해당 대화방에 직접 보내주세요."
                        )
                    else:
                        fail_text = (
                            "발송 실패: 대상 채널에 봇이 접근할 수 없습니다. "
                            "봇 초대/권한(scope) 설정 후 다시 시도해주세요."
                        )

                    if dm_channel_id and status_ts:
                        client.chat_update(channel=dm_channel_id, ts=status_ts, text=fail_text)
                    elif dm_channel_id:
                        client.chat_postMessage(channel=dm_channel_id, text=fail_text)
                    return
                raise

            source_permalink = session.get("source_permalink", "")
            extra_line = f"\n원문 링크: {source_permalink}" if source_permalink else ""
            done_text = f"발송 성공: 원문 스레드에 초안을 게시했습니다.{extra_line}"
            if dm_channel_id and status_ts:
                client.chat_update(channel=dm_channel_id, ts=status_ts, text=done_text)
            elif dm_channel_id:
                client.chat_postMessage(channel=dm_channel_id, text=done_text)
        except Exception as exc:
            logger.exception(f"reply_draft_send action failed: {exc}")
            try:
                action = (body.get("actions") or [{}])[0]
                session_id = (action.get("value") or "").strip()
                session = REPLY_SHORTCUT_SESSIONS.get(session_id) or {}
                dm_channel_id = session.get("dm_channel_id", "")
                if dm_channel_id:
                    client.chat_postMessage(
                        channel=dm_channel_id,
                        text="발송 실패: 오류가 발생했습니다. 잠시 후 다시 시도해주세요.",
                    )
            except Exception:
                pass

    return app


def main() -> None:
    app_token = _required_env("SLACK_APP_TOKEN")
    app = build_app()

    logger.info("Starting Personal Bot Socket Mode handler")
    SocketModeHandler(app, app_token).start()


if __name__ == "__main__":
    main()
