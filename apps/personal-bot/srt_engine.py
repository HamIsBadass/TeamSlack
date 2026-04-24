"""SRT 열차 조회 (search only) via `SRTrain` 라이브러리.

예약/취소는 side effect 가 있고 결제까지 자동화하지 않는다는 k-skill 규칙에 따라
현재 엔진은 **좌석 조회 전용**. 예약이 필요하면 사용자가 SRT 앱에서 직접 수행.

credentials: `KSKILL_SRT_ID`, `KSKILL_SRT_PASSWORD` (secrets.env 경유)
SKILL.md: ~/.agents/skills/srt-booking/SKILL.md
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# 주요 SRT 역 (upstream 인식 명칭). 사용자가 흔히 쓰는 축약 → 공식명 매핑.
_STATION_ALIASES = {
    "수서": "수서", "서울": "수서",  # SRT 는 서울역 미정차 — 수서로 normalize
    "동탄": "동탄", "평택": "평택지제", "평택지제": "평택지제",
    "천안아산": "천안아산", "아산": "천안아산", "천안": "천안아산",
    "오송": "오송",
    "대전": "대전",
    "김천구미": "김천구미", "김천": "김천구미", "구미": "김천구미",
    "동대구": "동대구", "대구": "동대구",
    "신경주": "신경주", "경주": "신경주",
    "울산": "울산", "통도사": "울산",
    "부산": "부산",
    "익산": "익산",
    "정읍": "정읍",
    "광주송정": "광주송정", "광주": "광주송정", "송정리": "광주송정",
    "목포": "목포",
    "공주": "공주",
}

# 공식 역명 정렬 (긴 이름 우선 — "천안아산" 이 "천안"보다 먼저 매칭되도록)
_STATION_CANON_ORDER = sorted(
    set(_STATION_ALIASES.values()) | set(_STATION_ALIASES.keys()),
    key=lambda s: (-len(s), s),
)

_SRT_KEYWORDS = ("SRT", "srt", "ＳＲＴ", "에스알티")
# SRT 전용역(코레일 미운행). generic "기차"/"열차" 쿼리에서 SRT로 라우팅할 트리거.
_SRT_ONLY_STATIONS = ("수서", "동탄")
_GENERIC_TRAIN_KEYWORDS = ("기차", "열차")

_RE_YYYYMMDD = re.compile(r"\b(20\d{2})[\-./]?(\d{1,2})[\-./]?(\d{1,2})\b")
_RE_MMDD = re.compile(r"\b(\d{1,2})\s*월\s*(\d{1,2})\s*일\b")
_RE_HHMM = re.compile(r"\b(\d{1,2})\s*:\s*(\d{2})\b|\b오?전?후?\s*(\d{1,2})\s*시(?!간)(?:\s*(\d{1,2})\s*분)?")


def is_srt_query(text: str) -> bool:
    if not text:
        return False
    if any(k in text for k in _SRT_KEYWORDS):
        return True
    # generic 기차/열차 는 SRT 전용역(수서/동탄)이 포함됐을 때만 SRT 로 판정.
    # 그래야 "용산 예산 9시 기차" 같은 Korail-only 쿼리가 KTX 엔진으로 간다.
    if any(k in text for k in _GENERIC_TRAIN_KEYWORDS):
        return any(s in text for s in _SRT_ONLY_STATIONS)
    return False


def _detect_stations(text: str) -> Tuple[Optional[str], Optional[str]]:
    """사용자 텍스트에서 (출발역, 도착역) 추출. SRT 축약/서울→수서 포함."""
    hits: List[Tuple[int, str]] = []
    seen: set = set()
    lower_text = text
    for cand in _STATION_CANON_ORDER:
        idx = 0
        while True:
            pos = lower_text.find(cand, idx)
            if pos < 0:
                break
            canon = _STATION_ALIASES.get(cand, cand)
            if canon not in seen:
                hits.append((pos, canon))
                seen.add(canon)
            idx = pos + len(cand)
    hits.sort(key=lambda x: x[0])
    if len(hits) >= 2:
        return hits[0][1], hits[1][1]
    if len(hits) == 1:
        return hits[0][1], None
    return None, None


def _detect_date(text: str, now: Optional[datetime] = None) -> str:
    """YYYYMMDD. 자연어(오늘/내일/모레/글피/N일 뒤) 및 숫자 표기 지원."""
    now = now or datetime.now()
    if "모레" in text:
        d = now + timedelta(days=2)
        return d.strftime("%Y%m%d")
    if "내일" in text:
        d = now + timedelta(days=1)
        return d.strftime("%Y%m%d")
    if "글피" in text:
        d = now + timedelta(days=3)
        return d.strftime("%Y%m%d")
    m = _RE_YYYYMMDD.search(text)
    if m:
        return f"{int(m.group(1)):04d}{int(m.group(2)):02d}{int(m.group(3)):02d}"
    m2 = _RE_MMDD.search(text)
    if m2:
        mo, dy = int(m2.group(1)), int(m2.group(2))
        yr = now.year
        # 지나간 날짜면 내년으로 roll
        cand = datetime(yr, mo, dy)
        if cand.date() < now.date():
            yr += 1
        return f"{yr:04d}{mo:02d}{dy:02d}"
    return now.strftime("%Y%m%d")


def _detect_time(text: str) -> str:
    """HHMMSS. '오후 N시' 는 +12 처리. 미지정 시 `000000` (당일 전체 조회)."""
    # HH:MM 우선
    m = _RE_HHMM.search(text)
    if m:
        if m.group(1) and m.group(2):
            h, mi = int(m.group(1)), int(m.group(2))
        else:
            h = int(m.group(3) or 0)
            mi = int(m.group(4) or 0)
            if "오후" in text and 1 <= h <= 11:
                h += 12
        return f"{h:02d}{mi:02d}00"
    return "000000"


def _station_guess_available() -> bool:
    return bool(os.getenv("KSKILL_SRT_ID") and os.getenv("KSKILL_SRT_PASSWORD"))


def _fmt_price(won: int) -> str:
    try:
        return f"{int(won):,}원"
    except (TypeError, ValueError):
        return str(won)


def _render_trains(dep: str, arr: str, date: str, trains: list) -> str:
    ymd = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
    head = f"**🚄 SRT {dep} → {arr} · {ymd}**"
    if not trains:
        return f"{head}\n조건에 맞는 SRT 가 없어!"
    lines = [head, f"• {len(trains)}편 조회 (상위 5편)"]
    for t in trains[:5]:
        # SRTrain.SRTTrain: dep_time / arr_time / train_number / general_seat_state / special_seat_state
        tno = getattr(t, "train_number", "")
        dtime = getattr(t, "dep_time", "")
        atime = getattr(t, "arr_time", "")
        gen = getattr(t, "general_seat_state", "")
        sp = getattr(t, "special_seat_state", "")
        seat_bits = []
        if gen:
            seat_bits.append(f"일반 {gen}")
        if sp:
            seat_bits.append(f"특실 {sp}")
        seats = " · ".join(seat_bits) if seat_bits else "좌석정보 없음"
        # dep_time 은 보통 "HHMMSS"
        def _fmt_hm(s: str) -> str:
            if isinstance(s, str) and len(s) >= 4 and s.isdigit():
                return f"{s[:2]}:{s[2:4]}"
            return str(s)
        lines.append(f"  - {tno}편 · {_fmt_hm(dtime)} → {_fmt_hm(atime)} · {seats}")
    lines.append("")
    lines.append("`실결제는 SRT 앱에서 직접 — 조회 전용`")
    return "\n".join(lines)


def build_srt_reply(user_text: str) -> str:
    if not _station_guess_available():
        return (
            "SRT 계정 정보가 설정되지 않았어!\n"
            "`~/.config/k-skill/secrets.env` 의 `KSKILL_SRT_ID`/`KSKILL_SRT_PASSWORD` 를 채워달라!"
        )

    dep, arr = _detect_stations(user_text)
    if not dep or not arr:
        return (
            "출발역/도착역을 인식하지 못했다!\n"
            "• 예: `SRT 수서 부산 내일 9시`, `SRT 수서에서 동대구 오늘 오전 10시`"
        )

    date = _detect_date(user_text)
    time = _detect_time(user_text)

    try:
        from SRT import SRT
    except ImportError:
        return "SRT 라이브러리가 설치되지 않았어! `pip install SRTrain` 먼저 실행해달라!"

    try:
        srt = SRT(os.environ["KSKILL_SRT_ID"], os.environ["KSKILL_SRT_PASSWORD"])
    except Exception as exc:
        logger.warning("SRT login failed: %s", exc)
        return f"SRT 로그인 실패! `{exc}`"

    try:
        trains = srt.search_train(dep, arr, date, time, available_only=False)
    except Exception as exc:
        logger.warning("SRT search failed: %s", exc)
        return f"SRT 조회 실패! `{exc}`"

    return _render_trains(dep, arr, date, list(trains or []))
