"""Forward-request review engine for the orchestrator bot (임곰).

personal-bot 등 하위 봇이 오케스트레이션 채널로 넘긴 "메시지 전달 요청" 을 자동으로
판정한다. 규칙은 결정론적(regex + 인메모리 rate limit + JSON blocklist) — LLM 호출
없음.

결과 타입:
    - "block"      : HARD_BLOCK 룰 매칭. 즉시 거부, 발송 금지. sender 에게 피드백만.
    - "escalate"   : 의심 패턴. owner 에게 승인/거부 버튼 DM. 판정 유보.
    - "pass"       : 문제 없음. 자동 발송.
    - "blocked_by_recipient" : target 이 전달 수신 거부 상태. 발송 금지.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_BLOCKLIST_FILE = Path(__file__).with_name("forward_blocklist.json")

# ============ HARD BLOCK rules ============
# 토큰/비밀번호/API 키 — 이런 게 섞여 있으면 owner 가 봐도 위험하니 즉시 차단.
_HARD_BLOCK_PATTERNS: List[Tuple[str, re.Pattern[str]]] = [
    ("password/token 키워드", re.compile(
        r"(?i)(password|passwd|token|secret|api[-_ ]?key|apikey)\s*[:=]"
    )),
    ("OpenAI sk- 토큰", re.compile(r"sk-[A-Za-z0-9]{20,}")),
    ("Slack xox 토큰", re.compile(r"xox[baprs]-[A-Za-z0-9-]{20,}")),
    ("Google API 키", re.compile(r"AIza[0-9A-Za-z_-]{35}")),
    ("GitHub PAT", re.compile(r"ghp_[A-Za-z0-9]{30,}")),
    ("base64 덩어리 >40자", re.compile(r"[A-Za-z0-9+/]{40,}={0,2}")),
    ("hex 덩어리 >40자", re.compile(r"\b[0-9a-fA-F]{40,}\b")),
]

# ============ ESCALATION rules ============
# 즉시 차단하기엔 오탐 가능성이 있어 owner 에게 판정 위임.
_ESCALATE_PATTERNS: List[Tuple[str, re.Pattern[str]]] = [
    ("이메일 주소", re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")),
    ("한국 전화번호", re.compile(r"\b01[016-9][-. ]?\d{3,4}[-. ]?\d{4}\b")),
]


@dataclass
class ReviewResult:
    verdict: str  # "block" | "escalate" | "pass" | "blocked_by_recipient"
    reasons: List[str]

    @property
    def is_pass(self) -> bool:
        return self.verdict == "pass"


# ============ Rate limiter (in-memory) ============
# key = (sender_user_id, target_user_id) → list[epoch_sec], 5분 window
_RATE_WINDOW_SEC = 5 * 60
_RATE_LIMIT_COUNT = 3
_rate_log: Dict[Tuple[str, str], List[float]] = {}


def _rate_check_and_record(sender: str, target: str) -> bool:
    """5분 내 3회째 이상이면 True(초과). 호출 시 타임스탬프 기록."""
    now = time.time()
    key = (sender, target)
    window = _rate_log.setdefault(key, [])
    # prune
    window[:] = [t for t in window if now - t < _RATE_WINDOW_SEC]
    window.append(now)
    return len(window) >= _RATE_LIMIT_COUNT


# ============ Blocklist (target opt-out) ============

def _load_blocklist() -> Dict[str, Dict[str, Any]]:
    if not _BLOCKLIST_FILE.exists():
        return {}
    try:
        return json.loads(_BLOCKLIST_FILE.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        logger.warning(f"forward blocklist parse failed: {exc}")
        return {}


def _save_blocklist(data: Dict[str, Dict[str, Any]]) -> None:
    try:
        _BLOCKLIST_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.exception(f"forward blocklist save failed: {exc}")


def is_recipient_blocked(target_user_id: str) -> bool:
    if not target_user_id:
        return False
    return target_user_id in _load_blocklist()


def add_to_blocklist(user_id: str, *, reason: Optional[str] = None) -> None:
    data = _load_blocklist()
    data[user_id] = {
        "blocked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "reason": reason,
    }
    _save_blocklist(data)


def remove_from_blocklist(user_id: str) -> bool:
    data = _load_blocklist()
    if user_id not in data:
        return False
    data.pop(user_id, None)
    _save_blocklist(data)
    return True


# ============ Main review entry ============

def review(
    *,
    sender_user_id: str,
    target_user_id: str,
    content: str,
) -> ReviewResult:
    """전달 요청 자동 검토. 외부 부작용: rate limiter 에 sender/target 기록."""
    if is_recipient_blocked(target_user_id):
        return ReviewResult(
            verdict="blocked_by_recipient",
            reasons=[f"<@{target_user_id}> 이 전달 수신을 차단함"],
        )

    block_reasons: List[str] = []
    for label, pat in _HARD_BLOCK_PATTERNS:
        if pat.search(content):
            block_reasons.append(label)
    if block_reasons:
        return ReviewResult(verdict="block", reasons=block_reasons)

    escalate_reasons: List[str] = []
    for label, pat in _ESCALATE_PATTERNS:
        if pat.search(content):
            escalate_reasons.append(label)
    if _rate_check_and_record(sender_user_id, target_user_id):
        escalate_reasons.append(
            f"rate limit: {sender_user_id}→{target_user_id} 5분 내 {_RATE_LIMIT_COUNT}회 이상"
        )
    if escalate_reasons:
        return ReviewResult(verdict="escalate", reasons=escalate_reasons)

    return ReviewResult(verdict="pass", reasons=[])


# ============ Opt-out intent detection ============
_BLOCK_KEYWORDS = ("전달 금지", "전달 차단", "포워드 금지", "forward off", "forward block")
_UNBLOCK_KEYWORDS = ("전달 허용", "전달 해제", "포워드 허용", "forward on", "forward unblock")


def is_blocklist_add_request(text: str) -> bool:
    if not text:
        return False
    lowered = text.lower()
    return any(kw in lowered for kw in _BLOCK_KEYWORDS) or any(
        kw in text for kw in _BLOCK_KEYWORDS
    )


def is_blocklist_remove_request(text: str) -> bool:
    if not text:
        return False
    lowered = text.lower()
    return any(kw in lowered for kw in _UNBLOCK_KEYWORDS) or any(
        kw in text for kw in _UNBLOCK_KEYWORDS
    )
