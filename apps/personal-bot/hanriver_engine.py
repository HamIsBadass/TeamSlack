"""Han River water-level lookup via k-skill-proxy.

Upstream: 한강홍수통제소(HRFCO). Endpoint:
- `/v1/han-river/water-level?stationName=<교량/관측소명>` 또는 `stationCode=<코드>`

SKILL.md: ~/.agents/skills/han-river-water-level/SKILL.md
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

_DEFAULT_PROXY = "https://k-skill-proxy.nomadamas.org"
_REQUEST_TIMEOUT = 12

# intent 판정 핵심 키워드
_HR_CORE_KEYWORDS = ("수위", "유량", "홍수", "방류")
# 한강권 교량/관측소 대표 명칭. 판정 신호로만 사용 — upstream 은 stationName 그대로 받음.
_HR_STATION_NAMES = (
    "한강대교", "잠수교", "반포대교", "원효대교", "마포대교", "서강대교",
    "양화대교", "성산대교", "가양대교", "행주대교", "방화대교", "일산대교",
    "김포대교", "성수대교", "영동대교", "청담대교", "잠실대교", "잠실철교",
    "올림픽대교", "천호대교", "팔당대교", "미사대교", "강동대교", "암사대교",
    "구리대교", "광진교", "동작대교", "한남대교", "동호대교",
    "팔당댐", "팔당", "청평댐", "소양강", "충주댐", "의암댐", "춘천댐",
)
_HR_STATION_CODE = re.compile(r"\b(\d{7})\b")
_HR_RIVER_HINT = ("한강", "북한강", "남한강", "경안천", "왕숙천", "중랑천", "탄천", "양재천")


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
            try:
                body = resp.json()
            except Exception:
                body = None
            if isinstance(body, dict):
                body["__status"] = resp.status_code
                return body
            return {"__error": f"http_{resp.status_code}"}
        try:
            return resp.json() or {}
        except Exception:
            return {"__error": "invalid_json"}
    except Exception as exc:
        logger.warning("han-river fetch failed %s %s: %s", url, params, exc)
        return {"__error": str(exc)}


def is_han_river_query(text: str) -> bool:
    if not text:
        return False
    # 관측소 코드 7자리 + 수위/유량 키워드 조합
    if _HR_STATION_CODE.search(text) and any(k in text for k in _HR_CORE_KEYWORDS):
        return True
    # 명시적 교량/관측소명 단독으로도 OK (예: "한강대교 수위")
    if any(st in text for st in _HR_STATION_NAMES) and any(k in text for k in _HR_CORE_KEYWORDS):
        return True
    # "한강 수위" 류
    if any(r in text for r in _HR_RIVER_HINT) and any(k in text for k in _HR_CORE_KEYWORDS):
        return True
    return False


def _detect_station(text: str) -> Dict[str, str]:
    """우선 7자리 관측소코드를 찾고, 없으면 알려진 교량/관측소명을 추출.

    아무것도 못 뽑으면 기본값 `한강대교` 로 조회한다.
    """
    m = _HR_STATION_CODE.search(text)
    if m:
        return {"stationCode": m.group(1)}
    for st in _HR_STATION_NAMES:
        if st in text:
            return {"stationName": st}
    return {"stationName": "한강대교"}


def _fmt_num(v: Any, unit: str = "", digits: int = 2) -> str:
    if v is None or v == "":
        return "-"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v) + unit
    return f"{f:.{digits}f}{unit}"


def _measure(v: Any, key: str) -> Any:
    """dict 형태 `{value_m: 0.57, unit: 'm'}` 혹은 스칼라에서 숫자 추출."""
    if isinstance(v, dict):
        return v.get(key)
    return v


def _fmt_observed_at(raw: str) -> str:
    """ISO8601 `2026-04-23T10:30:00+09:00` / raw `202604231030` → `2026-04-23 10:30`."""
    if not raw:
        return ""
    s = str(raw).strip()
    # 1) ISO8601 — T 기준 split, 초/오프셋 제거
    if "T" in s:
        date_part, _, time_part = s.partition("T")
        # time_part 에서 초/오프셋 제거: 10:30:00+09:00 → 10:30
        time_part = time_part.split("+")[0].split("-")[0].split("Z")[0]
        time_clean = ":".join(time_part.split(":")[:2])
        return f"{date_part} {time_clean}" if time_clean else date_part
    # 2) raw YYYYMMDDHHMM
    if s.isdigit() and len(s) == 12:
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]} {s[8:10]}:{s[10:12]}"
    return s


def _render(data: Dict[str, Any]) -> str:
    if data.get("__error"):
        return f"한강 수위 조회 실패! `{data['__error']}`"

    err = data.get("error")
    # ambiguous_station: candidate_stations 는 문자열 배열
    if err == "ambiguous_station":
        cands = list(data.get("candidate_stations") or [])
        head = "**🌊 관측소가 여러 곳 잡혔다!**"
        lines = [head, "구체적인 교량/관측소명이나 7자리 관측소코드로 다시 물어달라!", ""]
        for c in cands[:10]:
            if isinstance(c, dict):
                name = c.get("name") or c.get("stationName") or "?"
                code = c.get("code") or c.get("stationCode") or ""
                code_s = f" ({code})" if code else ""
                lines.append(f"• {name}{code_s}")
            else:
                lines.append(f"• {c}")
        return "\n".join(lines)

    if err == "measurement_not_found":
        return "해당 관측소의 최신 수위 자료가 없다! 잠시 후 다시 물어달라!"

    # 상위 HTTP 에러
    if data.get("__status"):
        msg = data.get("message") or err or f"http_{data['__status']}"
        return f"한강 수위 조회 실패! `{msg}`"

    # 성공 응답 — 필드는 top-level (snake_case)
    name = data.get("station_name") or data.get("stationName") or "?"
    code = data.get("station_code") or data.get("stationCode") or ""
    observed_at = (
        data.get("observed_at") or data.get("observedAt") or data.get("obs_time") or ""
    )
    water_m = _measure(data.get("water_level") or data.get("waterLevel"), "value_m")
    flow_cms = _measure(data.get("flow_rate") or data.get("flow"), "value_cms")

    head_code = f" · {code}" if code else ""
    head = f"**🌊 {name}{head_code}**"
    lines = [head]
    if observed_at:
        lines.append(f"• 관측 시각: {_fmt_observed_at(observed_at)}")
    lines.append(f"• 현재 수위: {_fmt_num(water_m, 'm')}")
    lines.append(f"• 현재 유량: {_fmt_num(flow_cms, 'm³/s')}")

    # 기준 수위
    th = data.get("thresholds") or {}
    thresholds = [
        ("관심", th.get("interest_level_m")),
        ("주의", th.get("warning_level_m")),
        ("경보", th.get("alarm_level_m")),
        ("심각", th.get("serious_level_m")),
    ]
    present = [(k, v) for k, v in thresholds if v not in (None, "", 0)]
    if present:
        parts = [f"{k} {_fmt_num(v, 'm')}" for k, v in present]
        lines.append("• 기준 수위: " + " / ".join(parts))

    lines.append("")
    lines.append("`한강홍수통제소 실시간 관측값 기준`")
    return "\n".join(lines)


def _fetch(params: Dict[str, str]) -> Dict[str, Any]:
    url = f"{_proxy_base()}/v1/han-river/water-level"
    return _get(url, params)


def build_han_river_reply(user_text: str) -> str:
    params = _detect_station(user_text or "")
    data = _fetch(params)
    return _render(data)
