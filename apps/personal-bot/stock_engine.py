"""Korean stock info engine for personal-bot.

KRX open API via k-skill-proxy (`/v1/korean-stock/search|base-info|trade-info`).
Routes: Korean listed stocks only. 미국/암호화폐/환율/금리 등은 상위에서 제외.

SKILL.md: ~/.agents/skills/korean-stock-search/SKILL.md
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

_DEFAULT_PROXY = "https://k-skill-proxy.nomadamas.org"
_REQUEST_TIMEOUT = 10
_MARKETS_ORDER = ("KOSPI", "KOSDAQ", "KONEX")

# 한국식 별칭·축약형 → KRX 색인 정식명 매핑. 모호한 이름은 넣지 않는다
# (예: "포스코" 는 홀딩스/퓨처엠/인터내셔널 여럿이라 의도적으로 제외).
_NAME_ALIASES: Dict[str, str] = {
    "삼전": "삼성전자",
    "삼바": "삼성바이오로직스",
    "엘지전자": "LG전자",
    "엘지화학": "LG화학",
    "엘지에너지솔루션": "LG에너지솔루션",
    "엘지이노텍": "LG이노텍",
    "엘지디스플레이": "LG디스플레이",
    "네이버": "NAVER",
    "현차": "현대차",
    "카뱅": "카카오뱅크",
    "카페이": "카카오페이",
    "셀젠": "셀트리온",
    "하닉": "SK하이닉스",
    "포홀": "POSCO홀딩스",
}

# 한국 주식 intent 직접 신호
_STOCK_MARKET_TOKENS = ("코스피", "코스닥", "코넥스", "kospi", "kosdaq", "konex", "krx")
# "삼성전자 주가" 같은 형식에서 후행 키워드
_STOCK_TAIL_KEYWORDS = (
    "주가", "주식", "종목", "시세", "종가", "상한가", "하한가",
    "기본정보", "종목정보", "종목코드", "상장주식",
)
# 해외/비주식 자산은 제외 (Perplexity Finance 로 넘김)
_EXCLUDE_KEYWORDS = (
    "환율", "원달러", "달러", "usd", "krw", "엔", "jpy", "유로", "eur", "위안", "cny",
    "코인", "비트코인", "이더리움", "도지", "솔라나", "xrp", "리플",
    "금리", "국채", "채권", "금값", "유가", "원유",
    "나스닥", "다우", "s&p", "sp500", "wti", "brent", "hangseng", "항셍", "니케이",
    "애플", "테슬라", "엔비디아", "nvidia", "msft", "googl", "amzn", "tsla", "meta",
)

# 6자리 종목코드
_CODE_PATTERN = re.compile(r"(?<!\d)(\d{6})(?!\d)")
# 회사명 후보 (한글/영문/숫자 1~15자) + 공백 + 후행 키워드
_NAME_PATTERN = re.compile(
    r"([가-힣A-Za-z0-9&]{1,15}?)\s*(?:은|는|이|가|의|을|를)?\s*(?:"
    + "|".join(map(re.escape, _STOCK_TAIL_KEYWORDS))
    + r")"
)


def _proxy_base() -> str:
    return (os.getenv("KSKILL_PROXY_BASE_URL", "").strip() or _DEFAULT_PROXY).rstrip("/")


def _apply_alias(name: str) -> str:
    """Map Korean informal/shortened names to the KRX canonical name."""
    if not name:
        return name
    key = name.strip().lower()
    for k, v in _NAME_ALIASES.items():
        if k.lower() == key:
            return v
    return name


def _lower(text: str) -> str:
    return (text or "").strip().lower()


def _has_exclusion(text: str) -> bool:
    low = _lower(text)
    return any(kw in low for kw in _EXCLUDE_KEYWORDS)


def is_korean_stock_query(text: str) -> bool:
    """Decide whether the DM is a Korean equity lookup we should route to KRX."""
    if not text:
        return False
    if _has_exclusion(text):
        return False

    low = _lower(text)
    if any(tok in low for tok in _STOCK_MARKET_TOKENS):
        return True
    if _CODE_PATTERN.search(text) and any(kw in text for kw in _STOCK_TAIL_KEYWORDS):
        return True
    # 종목명 + 주가/시세/종가 패턴
    if _NAME_PATTERN.search(text):
        return True
    return False


def _bas_dd_default(today: Optional[datetime] = None) -> str:
    now = today or datetime.now()
    # KRX 장 종료(15:30) 이전에 당일 trade-info 가 안 쌓여있을 수 있음 → 전일 기본.
    cutoff = now.replace(hour=16, minute=0, second=0, microsecond=0)
    use = now if now >= cutoff else now - timedelta(days=1)
    # 주말 skip
    while use.weekday() >= 5:
        use -= timedelta(days=1)
    return use.strftime("%Y%m%d")


def _get(url: str, params: Dict[str, Any]) -> Dict[str, Any]:
    try:
        resp = requests.get(
            url,
            params=params,
            headers={"Accept": "application/json", "User-Agent": "teamslack-personal-bot/0.1"},
            timeout=_REQUEST_TIMEOUT,
        )
        if resp.status_code == 404:
            return {"__status": 404}
        if resp.status_code >= 400:
            return {"__error": f"http_{resp.status_code}"}
        try:
            data = resp.json()
        except Exception:
            return {"__error": "invalid_json"}
        if isinstance(data, dict):
            return data
        return {"__error": "unexpected_shape"}
    except Exception as exc:
        logger.warning("stock fetch failed %s %s: %s", url, params, exc)
        return {"__error": str(exc)}


def _search(q: str, bas_dd: str, limit: int = 5) -> Dict[str, Any]:
    return _get(
        f"{_proxy_base()}/v1/korean-stock/search",
        {"q": q, "bas_dd": bas_dd, "limit": limit},
    )


def _trade_info(market: str, code: str, bas_dd: str) -> Dict[str, Any]:
    return _get(
        f"{_proxy_base()}/v1/korean-stock/trade-info",
        {"market": market, "code": code, "bas_dd": bas_dd},
    )


def _base_info(market: str, code: str, bas_dd: str) -> Dict[str, Any]:
    return _get(
        f"{_proxy_base()}/v1/korean-stock/base-info",
        {"market": market, "code": code, "bas_dd": bas_dd},
    )


def _extract_hints(text: str) -> Tuple[Optional[str], Optional[str]]:
    """Return (code_or_None, name_or_None). code takes precedence."""
    if not text:
        return (None, None)
    m_code = _CODE_PATTERN.search(text)
    code = m_code.group(1) if m_code else None
    name = None
    m_name = _NAME_PATTERN.search(text)
    if m_name:
        cand = m_name.group(1).strip()
        # tail keyword 자체는 버림 (본래 pattern 이 tail 을 non-capturing 하지만 혹시 모를 케이스)
        if cand and cand not in _STOCK_TAIL_KEYWORDS:
            name = cand
    return (code, name)


def _try_trade_info(code: str, bas_dd: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Try each KRX market until we get a hit. Returns (item, market) or (None, None)."""
    for mkt in _MARKETS_ORDER:
        data = _trade_info(mkt, code, bas_dd)
        if data.get("__status") == 404:
            continue
        if data.get("__error"):
            continue
        item = data.get("item")
        if isinstance(item, dict):
            return (item, mkt)
    return (None, None)


def _fmt_won(n: Optional[int]) -> str:
    if n is None:
        return "?"
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "?"
    return f"{n:,}원"


def _fmt_market_cap(n: Optional[int]) -> str:
    if n is None:
        return "?"
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "?"
    trillions = n // 1_000_000_000_000
    billions = (n % 1_000_000_000_000) // 100_000_000
    if trillions and billions:
        return f"{trillions:,}조 {billions:,}억원"
    if trillions:
        return f"{trillions:,}조원"
    if billions:
        return f"{billions:,}억원"
    return f"{n:,}원"


def _fmt_date(bas_dd: str) -> str:
    if not bas_dd or len(bas_dd) != 8:
        return bas_dd or "?"
    return f"{bas_dd[:4]}-{bas_dd[4:6]}-{bas_dd[6:]}"


def _render_trade(item: Dict[str, Any], market: str) -> str:
    name = item.get("name") or item.get("short_name") or "?"
    code = item.get("code") or "?"
    bas = _fmt_date(item.get("base_date") or "")
    close = item.get("close_price")
    chg_pct = item.get("fluctuation_rate")
    chg = item.get("change_price")
    vol = item.get("trading_volume")
    cap = item.get("market_cap")

    sign = ""
    try:
        if chg is not None and int(chg) > 0:
            sign = "+"
        elif chg is not None and int(chg) < 0:
            sign = ""  # minus already in number
    except (TypeError, ValueError):
        sign = ""
    chg_str = f"{sign}{chg:,}원" if isinstance(chg, (int, float)) else "?"
    pct_str = f"{chg_pct:+.2f}%" if isinstance(chg_pct, (int, float)) else "?"

    lines = [
        f"**📈 {name} ({market} · {code})** · 기준 {bas}",
        f"• 종가: {_fmt_won(close)} ({pct_str}, {chg_str})",
    ]
    open_p = item.get("open_price")
    high = item.get("high_price")
    low = item.get("low_price")
    if any(x is not None for x in (open_p, high, low)):
        lines.append(f"• 시/고/저: {_fmt_won(open_p)} / {_fmt_won(high)} / {_fmt_won(low)}")
    if vol is not None:
        try:
            lines.append(f"• 거래량: {int(vol):,}주")
        except (TypeError, ValueError):
            pass
    if cap is not None:
        lines.append(f"• 시가총액: {_fmt_market_cap(cap)}")
    lines.append("")
    lines.append("`KRX 공식 데이터 기준 · 투자 조언 아님`")
    return "\n".join(lines)


def _pick_primary(items: List[Dict[str, Any]], q: str) -> Optional[Dict[str, Any]]:
    """Choose the single 'canonical' candidate for q, or None if truly ambiguous.

    우선순위:
    1. name == q 정확 일치
    2. short_name == q (공백 제거 후)
    3. name == q + "보통주"
    4. 후보 중 "보통주" 접미를 가진 항목이 정확히 하나
    5. 단일 후보
    """
    if not items:
        return None
    qn = (q or "").strip()
    if not qn:
        return items[0] if len(items) == 1 else None

    def _name(it: Dict[str, Any]) -> str:
        return (it.get("name") or "").strip()

    def _short(it: Dict[str, Any]) -> str:
        return (it.get("short_name") or "").strip()

    for it in items:
        if _name(it) == qn:
            return it
    for it in items:
        if _short(it) == qn:
            return it
    for it in items:
        if _name(it) == f"{qn}보통주":
            return it
    if len(items) == 1:
        return items[0]
    return None


def _render_candidates(items: List[Dict[str, Any]], q: str) -> str:
    head = f"**🔎 '{q}' 검색 결과**"
    rows: List[str] = [head]
    for it in items[:5]:
        rows.append(
            f"• {it.get('name','?')} ({it.get('market','?')} · {it.get('code','?')})"
        )
    rows.append("")
    rows.append("구체적으로 종목명 또는 6자리 종목코드로 다시 물어달라!")
    return "\n".join(rows)


def build_korean_stock_reply(user_text: str) -> str:
    code, name = _extract_hints(user_text)
    bas_dd = _bas_dd_default()

    # 1) 6자리 코드 직행
    if code:
        item, mkt = _try_trade_info(code, bas_dd)
        if item and mkt:
            return _render_trade(item, mkt)
        # 전일도 실패하면 하루 더 거슬러 재시도
        prev = (datetime.strptime(bas_dd, "%Y%m%d") - timedelta(days=1)).strftime("%Y%m%d")
        item2, mkt2 = _try_trade_info(code, prev)
        if item2 and mkt2:
            return _render_trade(item2, mkt2)
        return (
            f"종목코드 **{code}** 로 시세를 찾지 못했다!\n"
            "휴장일이거나 KRX 상장 종목이 아닐 수 있다."
        )

    # 2) 종목명 검색
    q = name or user_text.strip()
    if not q:
        return "종목명 또는 6자리 종목코드를 알려달라!"
    q = _apply_alias(q)
    data = _search(q, bas_dd, limit=5)
    if data.get("__error"):
        return f"주식 검색 실패! `{data['__error']}`"
    items = [it for it in (data.get("items") or []) if isinstance(it, dict)]
    if not items:
        return (
            f"'**{q}**' 로 상장 종목을 찾지 못했다!\n"
            "표기를 확인하거나 6자리 종목코드로 다시 물어달라!"
        )

    # 정확 일치 또는 "보통주" 변형 자동 선택. KRX 이름은 "삼성전자보통주" 형태로
    # 들어오는 경우가 많아서 short_name/프리픽스 매칭도 함께 사용.
    chosen = _pick_primary(items, q)
    if chosen:
        mkt = chosen.get("market") or "KOSPI"
        c = chosen.get("code") or ""
        if not c:
            return _render_candidates(items, q)
        data2 = _trade_info(mkt, c, bas_dd)
        item = data2.get("item") if isinstance(data2, dict) else None
        if isinstance(item, dict):
            return _render_trade(item, mkt)
        # fallback — 전일 재시도
        prev = (datetime.strptime(bas_dd, "%Y%m%d") - timedelta(days=1)).strftime("%Y%m%d")
        data3 = _trade_info(mkt, c, prev)
        item3 = data3.get("item") if isinstance(data3, dict) else None
        if isinstance(item3, dict):
            return _render_trade(item3, mkt)
        return (
            f"**{chosen.get('name','?')} ({mkt} · {c})** 시세를 받아오지 못했다!\n"
            "장 마감 전이거나 휴장일일 수 있다."
        )

    # 후보 여러 건
    return _render_candidates(items, q)
