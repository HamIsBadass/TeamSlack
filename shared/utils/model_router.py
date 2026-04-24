"""Model routing helpers for Perplexity/Gemini selection."""

from __future__ import annotations

from typing import Optional, Tuple


REASONING_PRO_KEYWORDS = [
    "아키텍처",
    "설계 검토",
    "장애 분석",
    "트레이드오프",
]

REASONING_KEYWORDS = [
    "단계별",
    "원인",
    "비교",
    "코드 리뷰",
    "디버깅",
    "분석",
    "설계",
]

PRO_KEYWORDS = [
    "최신",
    "뉴스",
    "동향",
    "정책",
    "법령",
    "출처",
    "경쟁사",
    "시장",
    "공식",
    "주식",
    "주가",
    "환율",
    "코인",
    "비트코인",
    "이더리움",
    "금리",
    "국채",
    "달러",
    "코스피",
    "코스닥",
]

PREFIX_TO_MODEL = {
    "reasoning-pro": "sonar-reasoning-pro",
    "reasoning": "sonar-reasoning",
    "pro": "sonar-pro",
    "sonar": "sonar",
}


def select_perplexity_model(query: str) -> str:
    """Auto-select Perplexity model from query intent."""
    text = (query or "").strip().lower()

    if any(keyword in text for keyword in REASONING_PRO_KEYWORDS):
        return "sonar-reasoning-pro"
    if any(keyword in text for keyword in REASONING_KEYWORDS):
        return "sonar-reasoning"
    if any(keyword in text for keyword in PRO_KEYWORDS):
        return "sonar-pro"
    return "sonar"


GEMINI_HEAVY_TASKS = {"review", "code_review", "long_summary", "architecture"}
GEMINI_MID_TASKS = {"summary", "reply_rewrite", "analyze"}


def select_gemini_model(task_type: str = "", doc_length: int = 0) -> str:
    """Select Gemini model by workload complexity.

    Tier policy (2026-04-21):
    - gemini-2.5-pro: heavy reasoning (code review, architecture, long docs >3000 chars)
    - gemini-2.5-flash: mid-weight tasks (summary, rewrite with long context >800 chars)
    - gemini-2.5-flash-lite: default short-turn drafts/chat (cheapest, fastest)
    """
    if task_type in GEMINI_HEAVY_TASKS or doc_length > 3000:
        return "gemini-2.5-pro"
    if task_type in GEMINI_MID_TASKS or doc_length > 800:
        return "gemini-2.5-flash"
    return "gemini-2.5-flash-lite"


def parse_psearch_input(text: str) -> Tuple[str, Optional[str]]:
    """Parse optional model prefix from /psearch input.

    Examples:
    - "pro 한국 법령" -> ("한국 법령", "sonar-pro")
    - "reasoning-pro 장애 분석" -> ("장애 분석", "sonar-reasoning-pro")
    - "일반 질문" -> ("일반 질문", None)
    """
    raw = (text or "").strip()
    if not raw:
        return "", None

    parts = raw.split(maxsplit=1)
    prefix = parts[0].lower()

    if prefix in PREFIX_TO_MODEL:
        query = parts[1].strip() if len(parts) > 1 else ""
        return query, PREFIX_TO_MODEL[prefix]

    return raw, None
