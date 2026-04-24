"""Seoul subway real-time arrival engine for personal-bot.

- Intent detection via keyword set
- 역명 추출 (한글 2~5자 + '역' 접미)
- k-skill-proxy `/v1/seoul-subway/arrival` 조회 (startIndex/endIndex 명시 필수)
- 호선/방향별 그룹핑 후 최상단 열차 요약 렌더
- SKILL.md: ~/.agents/skills/seoul-subway-arrival/SKILL.md
"""

import logging
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

_SUBWAY_KEYWORDS = ("지하철", "도착정보", "열차")
# "몇 분 뒤", "곧 들어와" 류는 역명 힌트가 동반될 때만 intent 로 인정
_ARRIVAL_PATTERN = re.compile(r"(?:도착|몇\s*분|곧\s*들어)")
# "강남역", "홍대입구역" 등. 붙는 조사 전까지.
_STATION_PATTERN = re.compile(r"([가-힣]{1,6}역)(?=[^가-힣]|$)")
# 특정 시각 표기: "6시 20분", "18시", "18:20". "시간"(duration)과 구분.
_TIME_SPECIFIC_PATTERN = re.compile(
    r"\d{1,2}\s*시(?!간)(?:\s*\d{1,2}\s*분)?|\b\d{1,2}:\d{2}\b"
)

# 서울 Open API subwayId → 노선명
_LINE_NAME = {
    "1001": "1호선", "1002": "2호선", "1003": "3호선", "1004": "4호선",
    "1005": "5호선", "1006": "6호선", "1007": "7호선", "1008": "8호선",
    "1009": "9호선",
    "1061": "중앙선", "1063": "경의중앙", "1065": "공항철도",
    "1067": "경춘선", "1075": "수인분당", "1077": "신분당",
    "1092": "우이신설", "1093": "서해선", "1081": "경강선",
    "1032": "GTX-A",
}

# 응답의 arvlMsg2 가 "3분 20초 후", "전역 출발", "도착" 등으로 들어옴.
# 그대로 쓰되, 빈 문자열이면 barvlDt(초) 로 보조.
_DEFAULT_PROXY = "https://k-skill-proxy.nomadamas.org"
_REQUEST_TIMEOUT = 10


def _proxy_base() -> str:
    return (os.getenv("KSKILL_PROXY_BASE_URL", "").strip() or _DEFAULT_PROXY).rstrip("/")


_DIRECTION_PATTERN = re.compile(r"(하행|상행|외선|내선)")


def is_subway_query(text: str) -> bool:
    if not text:
        return False
    if any(kw in text for kw in _SUBWAY_KEYWORDS):
        return True
    # 역명 + (도착·몇분 | 방향 | 특정시각) 조합이어야 intent. "강남역 날씨" 같은 비지하철 문장 걸러냄.
    if _STATION_PATTERN.search(text) and (
        _ARRIVAL_PATTERN.search(text)
        or _DIRECTION_PATTERN.search(text)
        or _TIME_SPECIFIC_PATTERN.search(text)
    ):
        return True
    return False


def _has_specific_time(text: str) -> bool:
    """User asked about a fixed clock time (not 'now'). We only serve real-time."""
    if not text:
        return False
    return bool(_TIME_SPECIFIC_PATTERN.search(text))


def extract_station_name(text: str) -> Optional[str]:
    """Capture '...역' first hit. Returns None if no match."""
    if not text:
        return None
    m = _STATION_PATTERN.search(text)
    if not m:
        return None
    return m.group(1)


def _fetch_arrivals(station_name: str) -> Dict[str, Any]:
    """Raw API call. startIndex/endIndex 필수 (upstream 요구).
    upstream 은 '사당' 처럼 역 접미 제외한 이름을 기대한다.
    """
    base = _proxy_base()
    url = f"{base}/v1/seoul-subway/arrival"
    bare = station_name[:-1] if station_name.endswith("역") and len(station_name) > 1 else station_name
    params = {
        "stationName": bare,
        "startIndex": 1,
        "endIndex": 20,
    }
    try:
        resp = requests.get(
            url,
            params=params,
            headers={
                "Accept": "application/json",
                "User-Agent": "teamslack-personal-bot/0.1",
            },
            timeout=_REQUEST_TIMEOUT,
        )
        if resp.status_code >= 400:
            return {"error": f"http_{resp.status_code}"}
        return resp.json()
    except Exception as exc:
        logger.warning("subway fetch failed for %s: %s", station_name, exc)
        return {"error": str(exc)}


def _line_label(subway_id: Optional[str]) -> str:
    if not subway_id:
        return "?호선"
    return _LINE_NAME.get(subway_id, f"id:{subway_id}")


def _format_seconds(barvl_dt: Optional[str]) -> str:
    try:
        s = int(barvl_dt or 0)
    except ValueError:
        return ""
    if s <= 0:
        return ""
    m, sec = divmod(s, 60)
    if m and sec:
        return f"{m}분 {sec}초 후"
    if m:
        return f"{m}분 후"
    return f"{sec}초 후"


def _arrival_message(item: Dict[str, Any]) -> str:
    """arvlMsg2 우선, 비면 barvlDt 초 단위 폴백."""
    msg = (item.get("arvlMsg2") or "").strip()
    if msg:
        return msg
    secs = _format_seconds(item.get("barvlDt"))
    return secs or "정보없음"


def _group_key(item: Dict[str, Any]) -> tuple:
    return (
        item.get("subwayId") or "",
        (item.get("updnLine") or "").strip(),
    )


def _build_reply(station_name: str, data: Dict[str, Any]) -> str:
    if not isinstance(data, dict):
        return f"**{station_name}** 도착 정보 응답이 비정상이다!"
    if data.get("error"):
        return (
            f"**{station_name}** 도착 정보 조회 실패!\n"
            f"`{data['error']}`"
        )
    # 프록시가 상위 에러를 그대로 돌려주는 케이스 (status!=200)
    err_msg = data.get("errorMessage")
    if err_msg and err_msg.get("code") and err_msg.get("code") != "INFO-000":
        return (
            f"**{station_name}** 도착 정보 없음!\n"
            f"`{err_msg.get('message') or err_msg.get('code')}`"
        )
    if data.get("code") == "INFO-200" or data.get("total") == 0:
        return (
            f"**{station_name}** 실시간 도착 정보가 비어 있다!\n"
            "역명 표기 확인해보거나 잠시 후 다시 시도해달라!"
        )

    items: List[Dict[str, Any]] = list(data.get("realtimeArrivalList") or [])
    if not items:
        return f"**{station_name}** 도착 예정 열차가 없다!"

    groups: Dict[tuple, List[Dict[str, Any]]] = {}
    for it in items:
        groups.setdefault(_group_key(it), []).append(it)

    now_kst = datetime.now().strftime("%H:%M")
    statn_nm = (items[0].get("statnNm") or station_name.replace("역", "")).strip()
    lines: List[str] = [f"**🚇 {statn_nm}역 실시간 도착** · 기준 {now_kst}"]

    sorted_keys = sorted(groups.keys(), key=lambda k: (k[0], k[1]))
    for key in sorted_keys:
        subway_id, updn = key
        label = _line_label(subway_id)
        direction = updn or "?"
        top = groups[key][:2]
        header = f"• **{label} {direction}**"
        sub_lines: List[str] = []
        for it in top:
            dest = (it.get("bstatnNm") or "").strip()
            msg = _arrival_message(it)
            pos = (it.get("arvlMsg3") or "").strip()
            pos_part = f" (현재 {pos})" if pos and pos != statn_nm else ""
            dest_part = f"{dest}행" if dest else ""
            right = f"{dest_part}: {msg}{pos_part}" if dest_part else f"{msg}{pos_part}"
            sub_lines.append(f"  - {right}")
        lines.append(header)
        lines.extend(sub_lines)

    lines.append("")
    lines.append("`실시간 데이터라 수초 단위로 변경될 수 있다`")
    return "\n".join(lines)


def build_subway_reply(user_text: str, *, station_override: Optional[str] = None) -> str:
    if _has_specific_time(user_text):
        return (
            "특정 시각의 시간표 조회는 지원하지 않아!\n"
            "실시간 도착 정보만 제공한다.\n"
            "• 예: `용산역 도착 정보`, `강남역 지하철`\n"
        )
    station_name = station_override or extract_station_name(user_text)
    if not station_name:
        return (
            "어느 역인지 알려달라!\n"
            "• 예: `강남역 도착 정보`, `서울역 지하철`\n"
        )
    data = _fetch_arrivals(station_name)
    return _build_reply(station_name, data)
