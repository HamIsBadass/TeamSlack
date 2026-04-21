"""Socket Mode Slack bot runner for /psearch, /usdtw, and reply shortcut flows."""

import os
import sys
import re
import json
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

# Load .env from repository root.
load_dotenv(REPO_ROOT / ".env")

PERPLEXITY_API_URL = "https://api.perplexity.ai/chat/completions"

# 기본 지침
SYSTEM_PROMPT_BASE = (
    "불필요한 수식어 금지: 인삿말, 과도한 리액션, 칭찬, 스몰토크 없이 본론만 답변한다.\n"
    "맥락 격리: 질문 주제와 무관한 개인 취향이나 사적 맥락은 언급하지 않는다.\n"
    "효율적 구조: 질문의 핵심에 즉시 답하며 군더더기 서론/결론을 생략한다.\n"
    "담백한 어조: 정확성과 효율성 중심의 전문적이고 드라이한 어조를 유지한다.\n"
    "자기 지칭 규칙: 봇이 자신을 가리킬 때는 반드시 '짐'을 사용한다. 예: '짐이 요청을 수락했다곰.'\n"
    "마침내 형식: 모든 문장을 '~다', '~하다' 형태로 끝내고, AI 봇용 특수 형식 '~곰'을 사용한다."
)

# /psearch 지침
SYSTEM_PROMPT_PSEARCH = SYSTEM_PROMPT_BASE + (
    "\n\n금융/경제 질문: Perplexity Finance 데이터베이스를 우선 활용하여 최신 시장 데이터 기반 답변을 제공한다."
)

# /usdtw 지침
SYSTEM_PROMPT_USDTW = (
    "미화-원화 환율 함수: USD→KRW 환율을 제공한다.\n"
    "첫 문장 필수 형식: '지금 기준으로 1달러는 약 00원이다곰.'\n"
    "판단 포함: 최근 6개월 환율 흐름을 고려하여 현재가 저점/고점인지 한 줄 의견 제시. 문장을 '~곰.'으로 끝낸다.\n"
    "출처 생략: 참고 문헌이나 출처표시 [1][2] 등은 제공하지 않는다."
)


def _required_env(name: str) -> str:
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


def _sanitize_search_query(text: str) -> str:
    """Normalize free-form search text to core keyword query."""
    query = (text or "").strip()
    if not query:
        return ""

    query = re.sub(r"\s*(검색|찾기|조회|리서치|조사)\s*$", "", query, flags=re.IGNORECASE).strip()
    query = re.sub(r"^[/#@\-\s]+", "", query).strip()
    return query or (text or "").strip()


def _extract_year_terms(text: str) -> list[str]:
    """Extract explicit year-like constraints such as '26년' or '2026'."""
    raw = (text or "").strip()
    if not raw:
        return []

    seen: set[str] = set()
    years: list[str] = []

    patterns = [
        r"\b(19\d{2}|20\d{2})\b",
        r"\b(\d{2})년\b",
        r"\b(19\d{2}|20\d{2})년\b",
    ]
    for pattern in patterns:
        for match in re.findall(pattern, raw):
            token = f"{match}년" if pattern.endswith("년\\b") else str(match)
            if token not in seen:
                seen.add(token)
                years.append(token)

    return years


def _build_grounded_search_query(original_query: str) -> str:
    """Build a grounded prompt for Perplexity search requests."""
    search_query = _sanitize_search_query(original_query)
    year_terms = _extract_year_terms(search_query)

    year_rule = ""
    if year_terms:
        year_rule = (
            "연도 제약이 포함되어 있으므로 해당 연도 조건을 최우선으로 검증한다. "
            "조건과 일치하는 결과가 없으면 없다고 명시하고, 임의로 다른 연도 작품 정보를 단정하지 않는다. "
            f"연도 제약: {', '.join(year_terms)}\n"
        )

    return (
        "아래 키워드를 웹에서 검색해 사실 확인 가능한 정보만 요약한다. "
        "동명이인/오타 가능성이 있으면 유사 키워드(영문명/한글명)를 함께 재탐색한다. "
        "감독/출연/개봉연도는 확인되지 않으면 '미확인'으로 표기한다.\n"
        f"{year_rule}\n"
        f"검색 키워드:\n{search_query}\n\n"
        f"원문 요청:\n{original_query}"
    )


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
    markers = ["수정된 답변:", "최종 답변:", "답변:", "수정본:"]
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
        if "수정된 답변" in line or "최종 답변" in line:
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
    """Add 곰 and emojis to first and last sentences in bot responses.
    
    Format:
    - First sentence ends with: "~곰.🐻‍❄️"
    - Last sentence ends with: "~곰. :king_gom:"
    
    Avoids duplicate "곰" if already present in API response.
    """
    if not text or len(text.strip()) == 0:
        return text
    
    # 첫 번째 마침표 찾기
    first_period = text.find('.')
    last_period = text.rfind('.')
    has_multiple_sentences = (first_period != last_period)
    
    if first_period != -1:
        # "." 앞 문자가 "곰"이 아닐 경우에만 추가
        if first_period > 0 and text[first_period - 1] != '곰':
            # 첫 문장 처리: "." 앞에 "곰" 추가, 뒤의 공백 제거 후 이모티콘 추가
            text = text[:first_period] + "곰.🐻‍❄️ " + text[first_period+1:].lstrip()
        else:
            # 이미 "곰"이 있으면 "곰." 뒤에 이모티콘만 추가
            text = text[:first_period+1] + "🐻‍❄️ " + text[first_period+1:].lstrip()
    
    # 마지막 마침표 처리 (여러 문장인 경우만)
    if has_multiple_sentences:
        last_period = text.rfind('.')  # 수정된 텍스트에서 다시 찾기
        if last_period != -1:
            # "." 앞 문자가 "곰"이 아닐 경우에만 추가
            if last_period > 0 and text[last_period - 1] != '곰':
                # 마지막 문장 처리: "." 앞에 "곰" 추가, :king_gom: 추가
                text = text[:last_period] + "곰. :king_gom:"
            else:
                # 이미 "곰"이 있으면 "곰. " 뒤에 :king_gom:만 추가
                text = text[:last_period+1] + " :king_gom:"
    else:
        # 한 문장인 경우, 이미 첫 이모티콘이 추가되었으므로 마지막 이모티콘만 추가
        last_period = text.rfind('.')
        if last_period != -1:
            # 이모티콘 뒤에 :king_gom: 추가 (기존 emoji 다음)
            if "🐻‍❄️" in text:
                # emoji 뒤에 추가
                emoji_pos = text.rfind("🐻‍❄️")
                text = text[:emoji_pos + len("🐻‍❄️")] + " :king_gom:"
            else:
                # emoji가 없으면 마지막 마침표 뒤에 추가
                text = text[:last_period+1] + " :king_gom:"
    
    return text


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

    # Add 곰 emojis to bot response (first and last sentence)
    if apply_gom_style:
        content = add_gom_emojis(content)

    # Format for Slack (markdown → Slack format)
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

        grounded_query = _build_grounded_search_query(query)

        try:
            result = _perplexity_search(
                grounded_query,
                system_prompt=SYSTEM_PROMPT_PSEARCH,
                remove_citations=True,
                model_override=forced_model,
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
                    f"지금 기준으로 {amount_text}{currency_label}는 약 NNN원이다곰.:polar_bear: "
                    "추가 설명, 출처, 줄바꿈을 포함하지 마세요."
                )
                result = _perplexity_search(
                    query,
                    system_prompt=SYSTEM_PROMPT_USDTW,
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
                system_prompt=SYSTEM_PROMPT_USDTW,
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

            # Fetch source message text
            try:
                history = client.conversations_history(
                    channel=source_channel_id,
                    latest=source_ts,
                    limit=1,
                    inclusive=True,
                )
                messages = history.get("messages") or []
                original_message = (messages[0].get("text") if messages else "") or ""
            except SlackApiError as exc:
                error_code = ""
                try:
                    error_code = (exc.response or {}).get("error", "")
                except Exception:
                    error_code = ""
                if error_code in ("channel_not_found", "not_in_channel", "missing_scope"):
                    respond(
                        "자동 답변 초안 생성을 할 수 없습니다.\n"
                        "봇이 해당 대화방에 접근할 수 없거나 권한이 부족합니다.\n"
                        "공개 채널/봇 참여 채널에서 다시 시도하거나, shortcut을 사용해주세요."
                    )
                    return
                raise

            if not original_message.strip():
                respond(
                    "자동 답변 초안 생성을 할 수 없습니다.\n"
                    "원문 메시지를 찾지 못했습니다. 스레드에서 다시 시도하거나 메시지 링크를 입력해주세요."
                )
                return

            reply_draft = _gemini_generate_reply(original_message, "대기", "")
            if not reply_draft:
                respond("자동 답변 초안 생성을 할 수 없습니다. 잠시 후 다시 시도해주세요.")
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
            original_message = (message_obj.get("text") or "").strip()
            source_ts = (message_obj.get("ts") or "").strip()
            source_channel_id = (shortcut.get("channel", {}).get("id") or "").strip()
            if not original_message:
                logger.error("No message text in shortcut")
                return

            # Generate reply draft using default choice "대기"
            reply_draft = _gemini_generate_reply(original_message, "대기", "")
            if not reply_draft:
                logger.error("Gemini API failed to generate draft")
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

    logger.info("Starting Socket Mode handler for /psearch")
    SocketModeHandler(app, app_token).start()


if __name__ == "__main__":
    main()
