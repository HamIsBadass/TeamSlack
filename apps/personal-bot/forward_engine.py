"""Forward-request intent detection + pending queue for personal-bot.

사용자가 "방금 내용을 <@U123>에게 전달해줘" 같은 요청을 하면 personal-bot 이
본인 확인(ephemeral preview + [요청/수정/취소] 버튼)을 거쳐 orchestrator 채널로
넘기는 1차 게이트. 실제 발송/검토는 임곰(slack-bot) 쪽 핸들러가 담당한다.

Lifecycle:
    1. DM 텍스트가 is_forward_request() 매칭 → extract_target() 으로 대상 user_id 추출
    2. DM 최근 bot 응답을 수집해 queue_forward() 로 등록 (in-memory, TTL 10분)
    3. preview 메시지 + 3개 버튼 표시 → 사용자 "요청" 클릭 시 pop_forward() 하여 페이로드
       fetch, 임곰 채널로 post
    4. "취소" 클릭 시 drop, "수정" 클릭 시 별도 수정 플로우(현재는 안내만)

이 모듈은 규칙성 파싱과 in-memory state 만 관리. Slack I/O 는 호출자가 한다.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Dict, Optional, Tuple
from uuid import uuid4

logger = logging.getLogger(__name__)


# ============ In-memory pending queue ============
# request_id -> {sender_user_id, target_user_id, content, created_at, dm_channel_id,
#                preview_ts}
_PENDING_FORWARDS: Dict[str, Dict[str, Any]] = {}
_PENDING_TTL_SEC = 10 * 60  # 10분 TTL — fortune(1주일) 대비 짧게


def _prune() -> None:
    now = time.time()
    expired = [
        rid for rid, state in _PENDING_FORWARDS.items()
        if now - float(state.get("created_at") or 0) > _PENDING_TTL_SEC
    ]
    for rid in expired:
        _PENDING_FORWARDS.pop(rid, None)


def queue_forward(
    *,
    sender_user_id: str,
    target_type: str,
    target_ref: str,
    target_display: str,
    content_text: str,
    content_blocks: Optional[list[dict[str, Any]]] = None,
    dm_channel_id: str,
) -> str:
    """새 전달 요청 등록. target_type ∈ {user, channel_id, channel_name}.
    target_ref 는 발송 시 resolution 에 쓰는 원본 참조(<@U...>, C.., 채널명).
    target_display 는 preview 에 보이는 사람 친화 라벨 (예: '<@U..>' or '#팀').
    """
    _prune()
    rid = uuid4().hex[:12]
    _PENDING_FORWARDS[rid] = {
        "sender_user_id": sender_user_id,
        "target_type": target_type,
        "target_ref": target_ref,
        "target_display": target_display,
        "content_text": content_text,
        "content_blocks": content_blocks or [],
        "dm_channel_id": dm_channel_id,
        "created_at": time.time(),
        "preview_ts": None,
    }
    return rid


def get_forward(request_id: str) -> Optional[Dict[str, Any]]:
    _prune()
    return _PENDING_FORWARDS.get(request_id)


def pop_forward(request_id: str) -> Optional[Dict[str, Any]]:
    _prune()
    return _PENDING_FORWARDS.pop(request_id, None)


def set_preview_ts(request_id: str, ts: str) -> None:
    state = _PENDING_FORWARDS.get(request_id)
    if state is not None:
        state["preview_ts"] = ts


# ============ Intent detection ============

_FORWARD_VERBS = ("전달", "전송", "보내", "공유", "포워드", "forward")
_CONTENT_REFS = ("방금", "위 내용", "위에 내용", "이 내용", "앞서", "아까", "직전", "이거", "이걸")
_TRANSMISSION_PARTICLES = ("에게", "한테", " 앞", "앞으로")

# 다양한 target 형식 매칭
_RE_USER_MENTION = re.compile(r"<@([UW][A-Z0-9]{6,})(?:\|[^>]+)?>")
_RE_CHANNEL_MENTION = re.compile(r"<#([CG][A-Z0-9]{6,})(?:\|([^>]+))?>")
_RE_BRACKETED = re.compile(r"\[([^\[\]]{1,80})\]")
_RE_HASH_CHANNEL = re.compile(r"(?<![\w])#([\w\-가-힣]{2,80})")


def _has_any_target(text: str) -> bool:
    """사용자 멘션/채널 멘션/대괄호/해시 중 하나라도 있는지."""
    if not text:
        return False
    return bool(
        _RE_USER_MENTION.search(text)
        or _RE_CHANNEL_MENTION.search(text)
        or _RE_BRACKETED.search(text)
        or _RE_HASH_CHANNEL.search(text)
    )


def is_forward_request(text: str) -> bool:
    """`<@X> 전달` / `<#C> 보내` / `[채널] 발송` 류 요청 감지.

    발송 동사 + target(사용자/채널/대괄호/#해시) 하나 이상 있으면 매칭. 짧은
    imperative(`<@U> 전달`)도 허용. 사용자 확인 버튼을 거치므로 소폭 오탐은 피해 제한.
    """
    if not text:
        return False
    lowered = text.lower()
    has_verb = any(v in lowered for v in _FORWARD_VERBS)
    return has_verb and _has_any_target(text)


def extract_target(text: str) -> Optional[Tuple[str, str, str]]:
    """텍스트에서 첫 번째 target 을 (type, ref, display) 로 추출.

    반환 타입:
      ("user",        "<@Uxxx>", "<@Uxxx>")
      ("channel_id",  "Cxxx",     "<#Cxxx>")
      ("channel_name", "팀-공지", "#팀-공지")
    """
    if not text:
        return None
    m = _RE_USER_MENTION.search(text)
    if m:
        uid = m.group(1)
        return ("user", f"<@{uid}>", f"<@{uid}>")
    m = _RE_CHANNEL_MENTION.search(text)
    if m:
        cid = m.group(1)
        return ("channel_id", cid, f"<#{cid}>")
    m = _RE_BRACKETED.search(text)
    if m:
        name = m.group(1).strip()
        return ("channel_name", name, f"#{name}")
    m = _RE_HASH_CHANNEL.search(text)
    if m:
        name = m.group(1).strip()
        return ("channel_name", name, f"#{name}")
    return None


# ============ Last bot message capture ============

def capture_last_bot_message(
    messages: list[dict[str, Any]],
    *,
    requester_user_id: str,
    bot_user_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Slack conversations_history(newest-first) 에서 직전 bot 응답을 반환.

    `{"text": str, "blocks": list}` 형태로 원본 blocks 를 함께 돌려준다. blocks 를 그대로
    재사용하면 포맷(볼드/이탤릭/리스트 등)이 원문과 동일하게 round-trip 된다.
    """
    # 시스템 이벤트(조인/나감/토픽 변경 등)만 스킵. 'bot_message' subtype 은 봇 자신의
    # 게시에 붙을 수 있으므로 허용해야 fortune 같은 봇 응답을 놓치지 않는다.
    _SKIP_SUBTYPES = {
        "channel_join", "channel_leave", "channel_topic", "channel_purpose",
        "channel_name", "channel_archive", "channel_unarchive",
        "group_join", "group_leave", "group_topic", "group_purpose",
        "message_changed", "message_deleted", "message_replied",
        "file_comment",
    }
    for msg in messages:
        subtype = (msg.get("subtype") or "").strip()
        if subtype in _SKIP_SUBTYPES:
            continue
        msg_user = (msg.get("user") or "").strip()
        bot_id = (msg.get("bot_id") or "").strip()
        # 봇 메시지(bot_message 서브타입이거나 bot_id 만 있는 경우)는 user 가 비어
        # 있을 수 있으므로 bot_id 로도 식별 가능하게 한다.
        if not msg_user and not bot_id:
            continue
        if msg_user and msg_user == requester_user_id:
            continue
        if bot_user_id and msg_user and msg_user != bot_user_id:
            continue
        text = (msg.get("text") or "").strip()
        blocks = msg.get("blocks") or []
        if not (text or blocks):
            continue
        return {"text": text, "blocks": list(blocks)}
    return None


def clip_preview(text: str, max_len: int = 300) -> str:
    """미리보기용 클리핑. 줄바꿈 보존, 끝에 … 표시."""
    if not text:
        return ""
    if len(text) <= max_len:
        return text
    return text[:max_len].rstrip() + "…"


# ============ Preview blocks ============

# Slack section block mrkdwn text 는 3000자 제한. 여유 있게 2500자에서 자른다.
_SECTION_TEXT_MAX = 2500


def _safe_section(text: str) -> dict[str, Any]:
    """Section block 은 mrkdwn text 3000자 제한이 있어 긴 내용은 잘라내야 한다."""
    clipped = (text or "(내용 없음)")
    if len(clipped) > _SECTION_TEXT_MAX:
        clipped = clipped[:_SECTION_TEXT_MAX].rstrip() + "\n… (미리보기 생략, 실제 발송은 원문 전체)"
    return {"type": "section", "text": {"type": "mrkdwn", "text": clipped}}


def build_preview_blocks(
    *,
    request_id: str,
    target_display: str,
    content_text: str,
    content_blocks: Optional[list[dict[str, Any]]] = None,
) -> list[dict[str, Any]]:
    """전달 확인 preview. content 는 안전하게 잘라낸 section 으로 렌더해 Slack block
    size 초과로 메시지 전체가 drop 되는 걸 방지.
    content_blocks 인자는 호환성 유지용으로만 받고 사용하지 않는다 — Slack 이 자동
    생성한 rich_text blocks 는 재전송 시 포맷이 깨지는 케이스가 있어 text= 기반으로
    통일한다.
    """
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*발송 확인*\n다음 내용을 {target_display} 에 발송할까요?",
            },
        },
        {"type": "divider"},
        _safe_section(content_text),
        {"type": "divider"},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "발송"},
                    "action_id": "forward_confirm",
                    "value": request_id,
                    "style": "primary",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "취소"},
                    "action_id": "forward_cancel",
                    "value": request_id,
                    "style": "danger",
                },
            ],
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"요청 ID: `{request_id}` · 10분 내 미처리 시 자동 만료",
                }
            ],
        },
    ]


def build_delivery_text(*, sender_user_id: str, content_text: str) -> str:
    """target 에게 발송할 메시지는 `text=` 로만 보내 Slack 이 mrkdwn 을 그대로 렌더하게
    한다. Blocks 는 쓰지 않아 포맷 왜곡/크기 초과 문제를 원천 차단."""
    body = content_text or "(내용 없음)"
    return (
        f"📨 <@{sender_user_id}> 님이 쥐피티를 통해 다음을 전달했다!\n"
        "\n"
        f"{body}\n"
        "\n"
        "_출처: 쥐피티🐹 DM 전달_"
    )
