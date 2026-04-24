"""Korean real-estate actual transaction / rent lookup via k-skill-proxy.

Upstream: 국토교통부(MOLIT) 실거래가. Endpoints:
- `/v1/real-estate/region-code?q=<지역명>` → lawd_cd 5자리
- `/v1/real-estate/<asset>/<deal>?lawd_cd=&deal_ymd=`

SKILL.md: ~/.agents/skills/real-estate-search/SKILL.md
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

_DEFAULT_PROXY = "https://k-skill-proxy.nomadamas.org"
_REQUEST_TIMEOUT = 12

_ASSET_KEYWORDS: List[Tuple[str, str]] = [
    ("오피스텔", "officetel"),
    ("빌라", "villa"),
    ("연립", "villa"),
    ("다세대", "villa"),
    ("다가구", "single-house"),
    ("단독주택", "single-house"),
    ("단독", "single-house"),
    ("상가", "commercial"),
    ("상업업무", "commercial"),
    ("상업", "commercial"),
    ("아파트", "apartment"),
]
_RENT_KEYWORDS = ("전세", "월세", "전월세", "임대차", "임대")
_TRADE_KEYWORDS = ("매매", "실거래", "실거래가", "매수", "매도")

# 실거래 intent
_RE_INTENT_KEYWORDS = ("실거래", "실거래가", "부동산", "매매가", "전월세", "전세", "월세")
_RE_REGION_PATTERN = re.compile(r"([가-힣]{2,6}(?:구|시|군|동|읍|면))")
_RE_YYYYMM_PATTERN = re.compile(
    r"(?:(\d{4})\s*년\s*)?(\d{1,2})\s*월"
)
_RE_NUMERIC_YM = re.compile(r"\b(20\d{2})[\-./]?(\d{1,2})\b")

_EXCLUDE = ("해외", "뉴욕", "도쿄", "런던", "청약", "분양")


def _proxy_base() -> str:
    return (os.getenv("KSKILL_PROXY_BASE_URL", "").strip() or _DEFAULT_PROXY).rstrip("/")


def _get(url: str, params: Dict[str, Any]) -> Dict[str, Any]:
    try:
        resp = requests.get(
            url,
            params=params,
            headers={"Accept": "application/json", "User-Agent": "teamslack-personal-bot/0.1"},
            timeout=_REQUEST_TIMEOUT,
        )
        if resp.status_code >= 400:
            return {"__error": f"http_{resp.status_code}"}
        try:
            return resp.json() or {}
        except Exception:
            return {"__error": "invalid_json"}
    except Exception as exc:
        logger.warning("real-estate fetch failed %s %s: %s", url, params, exc)
        return {"__error": str(exc)}


def is_real_estate_query(text: str) -> bool:
    if not text:
        return False
    low = text.lower()
    if any(x in text for x in _EXCLUDE):
        return False
    # 핵심 키워드
    if any(kw in text for kw in _RE_INTENT_KEYWORDS):
        return True
    # 자산타입 + (가격|시세|거래|매매) 조합은 실거래가로 해석
    if any(ak in text for ak, _ in _ASSET_KEYWORDS) and any(
        k in text for k in ("매매", "거래", "가격", "시세")
    ):
        return True
    _ = low
    return False


def _detect_asset(text: str) -> str:
    for kw, asset in _ASSET_KEYWORDS:
        if kw in text:
            return asset
    return "apartment"


def _detect_deal(text: str) -> str:
    if any(k in text for k in _RENT_KEYWORDS):
        return "rent"
    if any(k in text for k in _TRADE_KEYWORDS):
        return "trade"
    return "trade"


def _detect_region(text: str) -> Optional[str]:
    m = _RE_REGION_PATTERN.search(text)
    return m.group(1) if m else None


def _detect_deal_ymd(text: str, now: Optional[datetime] = None) -> str:
    now = now or datetime.now()
    # "2024년 3월" / "24년 3월"
    m = _RE_YYYYMM_PATTERN.search(text)
    if m:
        yr = m.group(1)
        mo = int(m.group(2))
        if yr:
            y = int(yr)
        else:
            y = now.year
        return f"{y:04d}{mo:02d}"
    # "2024-03" / "202403"
    m2 = _RE_NUMERIC_YM.search(text)
    if m2:
        return f"{int(m2.group(1)):04d}{int(m2.group(2)):02d}"
    # default: 전월 (MOLIT 신고 lag 고려)
    year = now.year
    month = now.month - 1
    if month == 0:
        year -= 1
        month = 12
    return f"{year:04d}{month:02d}"


def _lookup_lawd(region: str) -> Optional[Dict[str, Any]]:
    data = _get(f"{_proxy_base()}/v1/real-estate/region-code", {"q": region})
    if data.get("__error"):
        return None
    results = data.get("results") or []
    if not results:
        return None
    # 여러 매칭이면 첫번째 (가장 구체적 매치 가능성 높음). 필요 시 개선.
    return results[0] if isinstance(results[0], dict) else None


def _fetch_transactions(asset: str, deal: str, lawd_cd: str, deal_ymd: str) -> Dict[str, Any]:
    url = f"{_proxy_base()}/v1/real-estate/{asset}/{deal}"
    return _get(url, {"lawd_cd": lawd_cd, "deal_ymd": deal_ymd, "num_of_rows": 100})


def _fmt_10k(n: Optional[float]) -> str:
    if n is None:
        return "?"
    try:
        v = int(n)
    except (TypeError, ValueError):
        return "?"
    eok = v // 10_000
    man = v % 10_000
    if eok and man:
        return f"{eok:,}억 {man:,}만"
    if eok:
        return f"{eok:,}억"
    return f"{man:,}만"


def _fmt_area(m2: Optional[float]) -> str:
    if m2 is None:
        return "?㎡"
    try:
        return f"{float(m2):.2f}㎡"
    except (TypeError, ValueError):
        return "?㎡"


def _asset_label_ko(asset: str) -> str:
    return {
        "apartment": "아파트",
        "officetel": "오피스텔",
        "villa": "연립/다세대",
        "single-house": "단독/다가구",
        "commercial": "상업업무용",
    }.get(asset, asset)


def _deal_label_ko(deal: str) -> str:
    return "매매" if deal == "trade" else "전월세"


def _render(
    region_label: str,
    asset: str,
    deal: str,
    deal_ymd: str,
    data: Dict[str, Any],
) -> str:
    if data.get("__error"):
        return f"부동산 실거래 조회 실패! `{data['__error']}`"
    items: List[Dict[str, Any]] = list(data.get("items") or [])
    summary: Dict[str, Any] = data.get("summary") or {}
    ymd_label = f"{deal_ymd[:4]}-{deal_ymd[4:6]}"
    head = f"**🏢 {region_label} {_asset_label_ko(asset)} {_deal_label_ko(deal)} · {ymd_label}**"
    if not items:
        return (
            f"{head}\n"
            "해당 지역/월 실거래 데이터가 없다! 다른 월로 다시 물어달라!"
        )

    lines: List[str] = [head]
    n = summary.get("sample_count") or len(items)
    if deal == "trade":
        med = summary.get("median_price_10k")
        lo = summary.get("min_price_10k")
        hi = summary.get("max_price_10k")
        lines.append(
            f"• 거래 {n}건 · 중위 {_fmt_10k(med)} / 최저 {_fmt_10k(lo)} / 최고 {_fmt_10k(hi)}"
        )
    else:
        med_d = summary.get("median_deposit_10k")
        avg_m = summary.get("monthly_rent_avg_10k")
        lines.append(
            f"• 계약 {n}건 · 보증금 중위 {_fmt_10k(med_d)} / 월세 평균 {_fmt_10k(avg_m)}"
        )

    for it in items[:3]:
        name = it.get("name") or "?"
        district = it.get("district") or ""
        area = _fmt_area(it.get("area_m2"))
        floor = it.get("floor")
        date = it.get("deal_date") or ""
        if deal == "trade":
            price = _fmt_10k(it.get("price_10k"))
            floor_s = f" {floor}층" if floor else ""
            dist_s = f" · {district}" if district else ""
            lines.append(f"  - {name}{dist_s} {area}{floor_s} {price} ({date})")
        else:
            dep = _fmt_10k(it.get("deposit_10k"))
            monthly = it.get("monthly_rent_10k")
            monthly_s = f"/{_fmt_10k(monthly)}" if monthly else ""
            floor_s = f" {floor}층" if floor else ""
            dist_s = f" · {district}" if district else ""
            lines.append(f"  - {name}{dist_s} {area}{floor_s} {dep}{monthly_s} ({date})")

    lines.append("")
    lines.append("`국토교통부 실거래가 신고 기준`")
    return "\n".join(lines)


def build_real_estate_reply(user_text: str) -> str:
    if not user_text:
        return "지역명(구/시/동)과 자산 타입(아파트/오피스텔/빌라)을 알려달라!"
    region = _detect_region(user_text)
    if not region:
        return (
            "지역명을 인식하지 못했다!\n"
            "• 예: `강남구 아파트 매매 실거래`, `마포구 오피스텔 전세`\n"
        )
    asset = _detect_asset(user_text)
    deal = _detect_deal(user_text)
    deal_ymd = _detect_deal_ymd(user_text)
    lawd = _lookup_lawd(region)
    if not lawd or not lawd.get("lawd_cd"):
        return f"'{region}' 법정동 코드를 찾지 못했다! 표기를 확인해달라!"
    data = _fetch_transactions(asset, deal, lawd["lawd_cd"], deal_ymd)
    return _render(lawd.get("name") or region, asset, deal, deal_ymd, data)
