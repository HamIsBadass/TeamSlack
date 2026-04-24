"""KTX/Korail 열차 조회 (search only) via `korail2` 라이브러리.

예약/취소는 side effect 가 있고 결제 자동화 불가이므로 v1 엔진은 **조회 전용**.
Korail anti-bot(Dynapath) 규칙 변경 시 upstream `korail2` 0.4.0 만으로도
`MACRO ERROR` 가능 — 발생 시 사용자에게 재시도를 안내한다.

credentials: `KSKILL_KTX_ID`, `KSKILL_KTX_PASSWORD` (secrets.env 경유)
SKILL.md: ~/.agents/skills/ktx-booking/SKILL.md
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# 주요 Korail 역. KTX 고속선 + 장항선/중앙선/경전선/태백선 등 일반열차 주요역 포함.
# generic "기차"/"열차" 쿼리에서 TrainType.ALL 로 조회 시 무궁화/새마을/ITX 도 커버.
_STATION_ALIASES = {
    # 경부선 고속
    "서울": "서울", "용산": "용산", "영등포": "영등포", "광명": "광명",
    "수원": "수원", "평택": "평택",
    "천안아산": "천안아산", "아산": "천안아산", "천안": "천안아산",
    "오송": "오송",
    "대전": "대전", "서대전": "서대전",
    "김천구미": "김천구미", "김천": "김천구미", "구미": "김천구미",
    "동대구": "동대구", "대구": "동대구",
    "신경주": "신경주", "경주": "신경주",
    "울산": "울산", "통도사": "울산",
    "밀양": "밀양", "구포": "구포",
    "부산": "부산", "부전": "부전",
    # 호남/전라선
    "익산": "익산",
    "정읍": "정읍",
    "광주송정": "광주송정", "광주": "광주송정", "송정리": "광주송정",
    "나주": "나주",
    "목포": "목포",
    "여수엑스포": "여수엑스포", "여수": "여수엑스포",
    "순천": "순천",
    "전주": "전주",
    "남원": "남원",
    # 강원/경강선
    "강릉": "강릉", "평창": "평창", "진부": "진부",
    "춘천": "춘천",
    # 중앙선
    "청량리": "청량리", "양평": "양평", "용문": "용문",
    "원주": "원주", "제천": "제천", "단양": "단양",
    "풍기": "풍기", "영주": "영주", "안동": "안동",
    "의성": "의성", "영천": "영천",
    # 태백/영동선
    "영월": "영월", "태백": "태백", "동해": "동해", "삼척": "삼척",
    # 장항선
    "신창": "신창", "온양온천": "온양온천", "도고온천": "도고온천",
    "예산": "예산", "홍성": "홍성", "광천": "광천",
    "대천": "대천", "웅천": "웅천", "판교": "판교",
    "서천": "서천", "장항": "장항", "군산": "군산",
    # 경전선/중부내륙선
    "마산": "마산", "창원": "창원", "창원중앙": "창원중앙",
    "진주": "진주",
    "충주": "충주", "문경": "문경",
}

_STATION_CANON_ORDER = sorted(
    set(_STATION_ALIASES.values()) | set(_STATION_ALIASES.keys()),
    key=lambda s: (-len(s), s),
)

_KTX_KEYWORDS = ("KTX", "ktx", "케이티엑스", "코레일", "무궁화", "새마을", "ITX")
_GENERIC_TRAIN_KEYWORDS = ("기차", "열차")
_KTX_SPECIFIC_KEYWORDS = ("KTX", "ktx", "케이티엑스", "코레일")

_RE_YYYYMMDD = re.compile(r"\b(20\d{2})[\-./]?(\d{1,2})[\-./]?(\d{1,2})\b")
_RE_MMDD = re.compile(r"\b(\d{1,2})\s*월\s*(\d{1,2})\s*일\b")
_RE_HHMM = re.compile(r"\b(\d{1,2})\s*:\s*(\d{2})\b|\b오?전?후?\s*(\d{1,2})\s*시(?!간)(?:\s*(\d{1,2})\s*분)?")


def is_ktx_query(text: str) -> bool:
    if not text:
        return False
    if any(k in text for k in _KTX_KEYWORDS):
        return True
    # generic "기차"/"열차" 도 수락. SRT 엔진이 수서/동탄 포함 여부로 먼저 가로채므로
    # 여기까지 흘러온 generic 쿼리는 Korail(KTX 포함 전 차종) 로 조회해야 한다.
    if any(k in text for k in _GENERIC_TRAIN_KEYWORDS):
        return True
    return False


def _detect_stations(text: str) -> Tuple[Optional[str], Optional[str]]:
    hits: List[Tuple[int, str]] = []
    seen: set = set()
    for cand in _STATION_CANON_ORDER:
        idx = 0
        while True:
            pos = text.find(cand, idx)
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
    now = now or datetime.now()
    if "모레" in text:
        return (now + timedelta(days=2)).strftime("%Y%m%d")
    if "내일" in text:
        return (now + timedelta(days=1)).strftime("%Y%m%d")
    if "글피" in text:
        return (now + timedelta(days=3)).strftime("%Y%m%d")
    m = _RE_YYYYMMDD.search(text)
    if m:
        return f"{int(m.group(1)):04d}{int(m.group(2)):02d}{int(m.group(3)):02d}"
    m2 = _RE_MMDD.search(text)
    if m2:
        mo, dy = int(m2.group(1)), int(m2.group(2))
        yr = now.year
        if datetime(yr, mo, dy).date() < now.date():
            yr += 1
        return f"{yr:04d}{mo:02d}{dy:02d}"
    return now.strftime("%Y%m%d")


def _detect_time(text: str) -> str:
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


def _creds_available() -> bool:
    return bool(os.getenv("KSKILL_KTX_ID") and os.getenv("KSKILL_KTX_PASSWORD"))


def _detect_train_type(text: str):
    """요청 텍스트 기반 TrainType 선택.

    - 무궁화/새마을/ITX 명시 → 해당 타입
    - KTX/ktx/코레일 명시 → KTX 계열
    - generic 기차/열차 만 있음 → TrainType.ALL (전 차종)
    - 아무것도 없음 (호출자가 keyword 없이 진입한 경우) → KTX
    """
    from korail2 import TrainType
    if "무궁화" in text:
        return TrainType.MUGUNGHWA
    if "새마을" in text:
        return TrainType.SAEMAEUL
    if "ITX" in text or "itx" in text:
        return TrainType.ITX_SAEMAEUL
    has_ktx_specific = any(k in text for k in _KTX_SPECIFIC_KEYWORDS)
    has_generic = any(k in text for k in _GENERIC_TRAIN_KEYWORDS)
    if has_generic and not has_ktx_specific:
        return TrainType.ALL
    return TrainType.KTX


def _train_type_label(train_type, text: str) -> str:
    """헤더에 붙일 사람-친화 라벨."""
    from korail2 import TrainType
    if train_type == TrainType.MUGUNGHWA:
        return "무궁화"
    if train_type == TrainType.SAEMAEUL:
        return "새마을"
    if train_type == TrainType.ITX_SAEMAEUL:
        return "ITX"
    if train_type == TrainType.ALL:
        return "기차"
    return "KTX"


def _fmt_hm(s: str) -> str:
    if isinstance(s, str) and len(s) >= 4 and s.isdigit():
        return f"{s[:2]}:{s[2:4]}"
    return str(s)


def _render_trains(dep: str, arr: str, date: str, trains: list, label: str = "KTX") -> str:
    ymd = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
    head = f"**🚆 {label} {dep} → {arr} · {ymd}**"
    if not trains:
        return f"{head}\n조건에 맞는 열차가 없어!"
    lines = [head, f"• {len(trains)}편 조회 (상위 5편)"]
    for t in trains[:5]:
        tno = getattr(t, "train_no", "")
        ttype = getattr(t, "train_type_name", "")
        dtime = getattr(t, "dep_time", "")
        atime = getattr(t, "arr_time", "")
        has_general = bool(getattr(t, "has_general_seat", False))
        has_special = bool(getattr(t, "has_special_seat", False))
        has_wait = bool(getattr(t, "has_waiting_list", False))
        seat_bits = []
        if has_general:
            seat_bits.append("일반 O")
        if has_special:
            seat_bits.append("특실 O")
        if not (has_general or has_special):
            if has_wait:
                seat_bits.append("매진(대기가능)")
            else:
                seat_bits.append("매진")
        seats = " · ".join(seat_bits)
        lines.append(
            f"  - {ttype} {tno}편 · {_fmt_hm(dtime)} → {_fmt_hm(atime)} · {seats}"
        )
    lines.append("")
    lines.append("`실결제는 코레일톡/레츠코레일에서 직접 — 조회 전용`")
    return "\n".join(lines)


def build_ktx_reply(user_text: str) -> str:
    if not _creds_available():
        return (
            "KTX(코레일) 계정 정보가 설정되지 않았어!\n"
            "`~/.config/k-skill/secrets.env` 의 `KSKILL_KTX_ID`/`KSKILL_KTX_PASSWORD` 를 채워달라!"
        )

    dep, arr = _detect_stations(user_text)
    if not dep or not arr:
        return (
            "출발역/도착역을 인식하지 못했다!\n"
            "• 예: `KTX 서울 부산 내일 9시`, `KTX 용산에서 광주송정 오늘 오전 10시`"
        )

    date = _detect_date(user_text)
    time = _detect_time(user_text)

    try:
        from ktx_booking_vendor import PatchedKorail
        from korail2 import NoResultsError
    except ImportError:
        return "korail2/pycryptodome 이 설치되지 않았어! `pip install korail2 pycryptodome` 먼저 실행해달라!"

    try:
        korail = PatchedKorail(os.environ["KSKILL_KTX_ID"], os.environ["KSKILL_KTX_PASSWORD"])
    except Exception as exc:
        logger.warning("Korail login failed: %s", exc)
        return f"KTX 로그인 실패! `{exc}`"

    train_type = _detect_train_type(user_text)
    label = _train_type_label(train_type, user_text)
    try:
        trains = korail.search_train(
            dep, arr, date, time_value=time,
            train_type=train_type,
            include_no_seats=True,
            include_waiting_list=True,
        )
    except NoResultsError:
        trains = []
    except Exception as exc:
        logger.warning("Korail search failed: %s", exc)
        msg = str(exc)
        if "MACRO" in msg.upper():
            return (
                "코레일 anti-bot(Dynapath) 검사에 걸렸어! "
                "잠시 후 다시 시도해달라. 반복되면 코레일톡 앱 접속 후 재시도하면 풀릴 수 있다."
            )
        return f"{label} 조회 실패! `{exc}`"

    return _render_trains(dep, arr, date, list(trains or []), label=label)
