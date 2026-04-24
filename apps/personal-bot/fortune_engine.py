"""Fortune-telling engine for personal-bot.

- Profile registry (fortune_profiles.json) resolves name → profile
- Compute today's 일진 (Heavenly Stem + Earthly Branch) via JDN formula
  (Reference: 1984-02-02 = 甲子日 — the triple-jiazi Spring Festival)
- Map 오행 relationship between user's 일간 and today's 일진
- Build Gemini structured-output prompt, parse JSON response
- Render to Slack markdown
"""

import hashlib
import json
import logging
import os
import re
import time
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from google import genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

logger = logging.getLogger(__name__)

_GAN_KO = "갑을병정무기경신임계"
_JI_KO = "자축인묘진사오미신유술해"
_GAN_HANJA = "甲乙丙丁戊己庚辛壬癸"
_JI_HANJA = "子丑寅卯辰巳午未申酉戌亥"

_GAN_KO_FROM_HANJA = dict(zip(_GAN_HANJA, _GAN_KO))

_GAN_OHENG = {
    "갑": "木", "을": "木",
    "병": "火", "정": "火",
    "무": "土", "기": "土",
    "경": "金", "신": "金",
    "임": "水", "계": "水",
}
_JI_OHENG = {
    "자": "水", "축": "土", "인": "木", "묘": "木", "진": "土",
    "사": "火", "오": "火", "미": "土", "신": "金", "유": "金",
    "술": "土", "해": "水",
}

_OHENG_KO = {"木": "목", "火": "화", "土": "토", "金": "금", "水": "수"}

_OHENG_COLORS = {
    "木": ["녹색", "청록색", "연두색"],
    "火": ["적색", "주홍색", "진홍색"],
    "土": ["황색", "갈색", "베이지"],
    "金": ["백색", "은색", "황금색"],
    "水": ["청색", "남색", "흑색"],
}
# 河圖 오행별 숫자
_OHENG_NUMBERS = {
    "木": [3, 8],
    "火": [2, 7],
    "土": [5, 10],
    "金": [4, 9],
    "水": [1, 6],
}
# 상생·상극
_SHENG = {"木": "火", "火": "土", "土": "金", "金": "水", "水": "木"}
_KE = {"木": "土", "土": "水", "水": "火", "火": "金", "金": "木"}

_WEEKDAY_RULER = {
    0: "달", 1: "화성", 2: "수성", 3: "목성",
    4: "금성", 5: "토성", 6: "태양",
}

_PROFILES_FILE = Path(__file__).with_name("fortune_profiles.json")
_profiles_cache: Optional[Dict[str, Any]] = None

_FORTUNE_KEYWORDS = ("운세", "사주", "오늘의 점", "오늘 점괘", "점괘")
_KO_PARTICLES = ("은", "는", "이", "가", "의", "을", "를", "아", "야")


def is_fortune_query(text: str) -> bool:
    if not text:
        return False
    return any(kw in text for kw in _FORTUNE_KEYWORDS)


def _load_profiles() -> Dict[str, Any]:
    global _profiles_cache
    if _profiles_cache is None:
        if _PROFILES_FILE.exists():
            try:
                _profiles_cache = json.loads(_PROFILES_FILE.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning("fortune profiles parse failed: %s", exc)
                _profiles_cache = {}
        else:
            _profiles_cache = {}
    return _profiles_cache


def reload_profiles() -> None:
    global _profiles_cache
    _profiles_cache = None


def _save_profile(name: str, profile: Dict[str, Any]) -> None:
    """Persist a single profile entry and invalidate the cache."""
    profiles = dict(_load_profiles())
    profiles[name] = profile
    _PROFILES_FILE.write_text(
        json.dumps(profiles, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    reload_profiles()


_JI_ANIMAL = {
    "자": "쥐", "축": "소", "인": "호랑이", "묘": "토끼",
    "진": "용", "사": "뱀", "오": "말", "미": "양",
    "신": "원숭이", "유": "닭", "술": "개", "해": "돼지",
}


def year_to_ganji(year: int) -> Tuple[str, str]:
    """Return (천간, 지지) for the lunar-year sexagenary cycle.
    Reference: 1984 = 甲子년 (triple-jiazi Spring Festival)."""
    delta = (year - 1984) % 60
    return (_GAN_KO[delta % 10], _JI_KO[delta % 12])


def year_to_korean_zodiac(year: int) -> str:
    gan, ji = year_to_ganji(year)
    return f"{_JI_ANIMAL[ji]}띠({gan}{ji}생)"


# 별자리 경계 (양력 기준). 오름차순 정렬.
_ZODIAC_TABLE: List[Tuple[int, int, str]] = [
    (1, 1, "염소자리"),
    (1, 20, "물병자리"),
    (2, 19, "물고기자리"),
    (3, 21, "양자리"),
    (4, 20, "황소자리"),
    (5, 21, "쌍둥이자리"),
    (6, 22, "게자리"),
    (7, 23, "사자자리"),
    (8, 23, "처녀자리"),
    (9, 23, "천칭자리"),
    (10, 23, "전갈자리"),
    (11, 23, "사수자리"),
    (12, 22, "염소자리"),
]


def date_to_western_zodiac(d: date) -> str:
    m, day = d.month, d.day
    current = _ZODIAC_TABLE[0][2]
    for (sm, sd, name) in _ZODIAC_TABLE:
        if (m, day) >= (sm, sd):
            current = name
        else:
            break
    return current


_PENDING_REGISTRATIONS: Dict[str, Dict[str, Any]] = {}
_PENDING_TTL_SEC = 600  # 10분

# 소유자(default 사용자) 승인 대기 큐. approval_id → state dict
_PENDING_APPROVALS: Dict[str, Dict[str, Any]] = {}
_APPROVAL_TTL_SEC = 7 * 24 * 3600  # 1주일

_UPDATE_KEYWORDS = (
    "프로필 업데이트", "프로필 수정", "프로필 등록", "프로필 추가",
    "운세 프로필",
)
_LIST_KEYWORDS = ("프로필 목록", "프로필 리스트", "프로필 전체", "프로필 현황")
_DELETE_KEYWORDS = ("프로필 삭제", "프로필 제거")
_APPROVAL_LIST_KEYWORDS = ("프로필 승인 대기", "승인 대기 목록", "승인 대기")
_RENAME_KEYWORDS = ("이름", "표시명", "display_name", "display name")


def _prune_pending() -> None:
    now = time.time()
    stale = [uid for uid, s in _PENDING_REGISTRATIONS.items()
             if now - s.get("started_at", 0) > _PENDING_TTL_SEC]
    for uid in stale:
        _PENDING_REGISTRATIONS.pop(uid, None)


def has_pending_registration(user_id: str) -> bool:
    _prune_pending()
    return bool(user_id) and user_id in _PENDING_REGISTRATIONS


def cancel_registration(user_id: str) -> bool:
    return _PENDING_REGISTRATIONS.pop(user_id, None) is not None


def _prune_approvals() -> None:
    now = time.time()
    stale = [aid for aid, s in _PENDING_APPROVALS.items()
             if now - s.get("created_at", 0) > _APPROVAL_TTL_SEC]
    for aid in stale:
        _PENDING_APPROVALS.pop(aid, None)


def queue_approval(
    *,
    requester_user_id: str,
    target_name: str,
    profile: Dict[str, Any],
    mode: str,
) -> str:
    """Queue a profile write for owner approval. Returns opaque approval_id."""
    _prune_approvals()
    payload = f"{requester_user_id}:{target_name}:{time.time()}".encode("utf-8")
    approval_id = hashlib.sha256(payload).hexdigest()[:12]
    _PENDING_APPROVALS[approval_id] = {
        "requester_user_id": requester_user_id,
        "target_name": target_name,
        "profile": profile,
        "mode": mode,
        "created_at": time.time(),
    }
    return approval_id


def get_pending_approval(approval_id: str) -> Optional[Dict[str, Any]]:
    _prune_approvals()
    return _PENDING_APPROVALS.get(approval_id)


def approve_pending(approval_id: str) -> Optional[Dict[str, Any]]:
    """Persist the queued profile and return the approval state (or None if gone)."""
    _prune_approvals()
    state = _PENDING_APPROVALS.pop(approval_id, None)
    if not state:
        return None
    _save_profile(state["target_name"], state["profile"])
    date_tag = date.today().isoformat()
    _FORTUNE_CACHE.pop(f"{state['target_name']}:{date_tag}", None)
    return state


def reject_pending(approval_id: str) -> Optional[Dict[str, Any]]:
    _prune_approvals()
    return _PENDING_APPROVALS.pop(approval_id, None)


def is_profile_update_request(text: str) -> bool:
    if not text:
        return False
    return any(kw in text for kw in _UPDATE_KEYWORDS)


def is_profile_list_request(text: str) -> bool:
    if not text:
        return False
    return any(kw in text for kw in _LIST_KEYWORDS)


def is_profile_delete_request(text: str) -> bool:
    if not text:
        return False
    return any(kw in text for kw in _DELETE_KEYWORDS)


def is_approval_list_request(text: str) -> bool:
    if not text:
        return False
    return any(kw in text for kw in _APPROVAL_LIST_KEYWORDS)


def extract_profile_delete_target(text: str) -> Optional[str]:
    m = re.search(
        r'([가-힣]{2,4})\s*(?:의)?\s*프로필\s*(?:삭제|제거)',
        text,
    )
    if m:
        name = m.group(1)
        if name in _TIME_WORD_FILTERS:
            return None
        return name
    return None


def list_profiles() -> Dict[str, Any]:
    """캐시 우회 없이 현재 레지스트리 snapshot 반환 (copy)."""
    return dict(_load_profiles())


def delete_profile(name: str) -> Optional[Dict[str, Any]]:
    """레지스트리에서 한 entry 제거, 삭제된 profile 반환 (없으면 None)."""
    profiles = dict(_load_profiles())
    removed = profiles.pop(name, None)
    if removed is None:
        return None
    _PROFILES_FILE.write_text(
        json.dumps(profiles, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    reload_profiles()
    date_tag = date.today().isoformat()
    _FORTUNE_CACHE.pop(f"{name}:{date_tag}", None)
    return removed


_RE_DISPLAY_NAME_UPDATE = re.compile(
    r'([a-zA-Z0-9_가-힣]{2,20})\s*'
    r'(?:(?:의|사용자|프로필)\s*)*'
    r'(?:표시명|display[_\s]?name|이름)\s*(?:을|를)?\s*'
    r'([가-힣a-zA-Z0-9_]+?)\s*'
    r'(?:으?로)?\s*'
    r'(?:수정|변경|바꿔|바꿔줘|업데이트)',
    re.IGNORECASE,
)


def is_display_name_update_request(text: str) -> bool:
    if not text:
        return False
    if not any(kw in text for kw in _RENAME_KEYWORDS):
        return False
    return _RE_DISPLAY_NAME_UPDATE.search(text) is not None


def extract_display_name_update(text: str) -> Optional[Tuple[str, str]]:
    """Return (target_key, new_display_name) or None.

    "default 이름을 이지인으로 수정" / "이유송 표시명 유송이로 변경" 같은
    문구에서 대상 키와 새 표시명을 뽑는다.
    """
    if not text:
        return None
    m = _RE_DISPLAY_NAME_UPDATE.search(text)
    if not m:
        return None
    target_raw = m.group(1)
    new_name = m.group(2)
    if not target_raw or not new_name:
        return None
    # 대상과 새 이름이 겹치거나 금칙어면 거부
    if target_raw == new_name:
        return None
    if target_raw in _TIME_WORD_FILTERS or new_name in _TIME_WORD_FILTERS:
        return None
    return target_raw, new_name


def rename_display_name(target_key: str, new_display_name: str) -> Optional[Dict[str, Any]]:
    """`target_key` 프로필의 display_name 만 변경. 없으면 None 반환."""
    profiles = dict(_load_profiles())
    profile = profiles.get(target_key)
    if profile is None:
        return None
    profile = dict(profile)
    profile["display_name"] = new_display_name
    _PROFILES_FILE.write_text(
        json.dumps({**profiles, target_key: profile}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    reload_profiles()
    date_tag = date.today().isoformat()
    _FORTUNE_CACHE.pop(f"{target_key}:{date_tag}", None)
    return profile


def list_pending_approvals() -> List[Tuple[str, Dict[str, Any]]]:
    _prune_approvals()
    items = list(_PENDING_APPROVALS.items())
    items.sort(key=lambda kv: kv[1].get("created_at", 0))
    return items


def extract_profile_update_target(text: str) -> Optional[str]:
    m = re.search(
        r'([가-힣]{2,4})\s*(?:의)?\s*프로필\s*(?:업데이트|수정|등록|추가)',
        text,
    )
    if m:
        name = m.group(1)
        if name in _TIME_WORD_FILTERS:
            return None
        return name
    return None


def canonicalize_target(target: Optional[str]) -> str:
    """Return the canonical registry key for a captured name, or a clean new name.

    - If the target resolves (directly or via alias/particle-strip), returns the
      canonical key from `fortune_profiles.json`.
    - Otherwise strips a single trailing Korean particle so a new registration
      uses a clean form (e.g., `신지은의` → `신지은`).
    """
    if not target:
        return ""
    key, profile = resolve_profile(target)
    if profile is not None and key and key != "default":
        return key
    if len(target) >= 3 and target[-1] in _KO_PARTICLES:
        return target[:-1]
    return target


def _generate_aliases(name: str) -> List[str]:
    if not name or len(name) < 3:
        return []
    if not re.fullmatch(r'[가-힣]+', name):
        return []
    nickname = name[-2:]
    profiles = _load_profiles()
    if nickname in profiles:
        return []
    for key, p in profiles.items():
        if key == name:
            continue
        if nickname in (p.get("aliases") or []):
            return []
    return [nickname]


def start_registration(user_id: str, target_name: str, *, mode: str = "create") -> str:
    """Enter pending state. Returns the prompt to send back to the user."""
    _PENDING_REGISTRATIONS[user_id] = {
        "target": target_name,
        "mode": mode,
        "started_at": time.time(),
    }
    existing = _load_profiles().get(target_name)
    if mode == "update" and existing:
        current_line = (
            f"현재: 생년 {existing.get('birth_year') or '미등록'}, "
            f"일간 {existing.get('ilgan') or '미등록'}"
        )
        return (
            f"'**{target_name}**' 프로필 업데이트. 바꿀 항목만 보내도 돼!\n"
            f"• `생년월일 일간` (예: `1997-10-15 경`)\n"
            f"• 생년월일만: `1997-10-15`\n"
            f"• 일간만: `일간 경` 또는 `경`\n"
            f"• 일간은 甲乙丙丁戊己庚辛壬癸 중 하나, 모르면 `모름`\n"
            f"• 취소는 `취소`\n"
            f"{current_line}"
        )
    return (
        f"'**{target_name}**' 프로필 신규 등록. 아래 형식으로 한 번에 보내줘!\n"
        f"• `생년월일 일간` (예: `1997-10-15 경`)\n"
        f"• 일간은 甲乙丙丁戊己庚辛壬癸 중 하나 (모르면 `모름`)\n"
        f"• 띠·별자리는 생년월일에서 자동 계산\n"
        f"• 취소는 `취소`"
    )


def _parse_birth_date(t: str) -> Optional[date]:
    for pat in (
        r'(\d{4})[-./](\d{1,2})[-./](\d{1,2})',
        r'(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일?',
        r'(\d{4})(\d{2})(\d{2})',
    ):
        m = re.search(pat, t)
        if m:
            try:
                return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except (ValueError, OverflowError):
                continue
    return None


def _parse_ilgan(t: str, *, date_match_end: int = 0) -> Tuple[Optional[str], bool]:
    """Parse ilgan from text AFTER the date portion.
    Returns (ilgan_hanja, explicit_unknown_flag).
    - (None, True): user explicitly said 모름/없음
    - (Hanja, False): valid 천간 character found
    - (None, False): no ilgan info supplied
    """
    rest = t[date_match_end:] if date_match_end else t
    rest_stripped = rest.strip()
    if re.search(r'(모름|미등록|없음|unknown|\?)', rest_stripped):
        return (None, True)
    for ch in rest_stripped:
        if ch in _GAN_OHENG:
            idx = _GAN_KO.index(ch)
            return (_GAN_HANJA[idx], False)
        if ch in _GAN_KO_FROM_HANJA:
            return (ch, False)
    return (None, False)


def handle_registration_response(
    user_id: str,
    text: str,
    *,
    auto_save: bool = True,
) -> Dict[str, Any]:
    """Consume a follow-up message while registration is pending.

    `auto_save=False` → returns status="pending_approval" with the built
    profile dict but without persisting. 호출측이 소유자 승인 경유로 저장.
    """
    state = _PENDING_REGISTRATIONS.get(user_id)
    if not state:
        return {"status": "no_pending"}

    target = state["target"]
    mode = state.get("mode", "create")
    t = (text or "").strip()

    if re.fullmatch(r'(취소|cancel|abort|그만)', t, flags=re.IGNORECASE):
        _PENDING_REGISTRATIONS.pop(user_id, None)
        return {"status": "cancelled", "message": f"'{target}' 등록 취소됨!"}

    birth_date = _parse_birth_date(t)
    # Find date match end to parse ilgan after it (if present)
    date_end = 0
    for pat in (
        r'(\d{4})[-./](\d{1,2})[-./](\d{1,2})',
        r'(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일?',
        r'(\d{4})(\d{2})(\d{2})',
    ):
        m = re.search(pat, t)
        if m:
            date_end = m.end()
            break
    ilgan_hanja, explicit_unknown = _parse_ilgan(t, date_match_end=date_end)

    profiles = _load_profiles()
    existing = profiles.get(target)

    if mode == "create":
        if not birth_date:
            return {
                "status": "incomplete",
                "prompt": (
                    f"생년월일 인식 실패. 다시 보내줘!\n"
                    f"• 예: `1997-10-15 경`\n"
                    f"• 일간 모르면 `1997-10-15 모름`\n"
                    f"• 취소는 `취소`"
                ),
            }
        if ilgan_hanja is None and not explicit_unknown:
            return {
                "status": "incomplete",
                "prompt": (
                    f"일간이 빠졌다. 생년월일 뒤에 일간을 붙여줘!\n"
                    f"• 예: `{birth_date.isoformat()} 경`\n"
                    f"• 모르면 `{birth_date.isoformat()} 모름`\n"
                    f"• 취소는 `취소`"
                ),
            }
        profile = {
            "display_name": target,
            "aliases": _generate_aliases(target),
            "birth_year": birth_date.year,
            "birth_date": birth_date.isoformat(),
            "zodiac_ko": year_to_korean_zodiac(birth_date.year),
            "zodiac_western": date_to_western_zodiac(birth_date),
            "ilgan": ilgan_hanja,
        }
    else:
        # update — must provide at least one of birth_date / ilgan (or 모름)
        if birth_date is None and ilgan_hanja is None and not explicit_unknown:
            return {
                "status": "incomplete",
                "prompt": (
                    f"업데이트할 항목을 인식 못 했다. 아래 중 하나로 보내줘!\n"
                    f"• 생년월일+일간: `1997-10-15 경`\n"
                    f"• 생년월일만: `1997-10-15`\n"
                    f"• 일간만: `일간 경`\n"
                    f"• 취소는 `취소`"
                ),
            }
        profile = dict(existing) if existing else {"display_name": target}
        profile.setdefault("display_name", target)
        if not profile.get("aliases"):
            profile["aliases"] = _generate_aliases(target)
        if birth_date is not None:
            profile["birth_year"] = birth_date.year
            profile["birth_date"] = birth_date.isoformat()
            profile["zodiac_ko"] = year_to_korean_zodiac(birth_date.year)
            profile["zodiac_western"] = date_to_western_zodiac(birth_date)
        if ilgan_hanja is not None:
            profile["ilgan"] = ilgan_hanja
            profile.pop("ilgan_note", None)
        elif explicit_unknown:
            profile["ilgan"] = None
            profile.pop("ilgan_note", None)

    _PENDING_REGISTRATIONS.pop(user_id, None)
    if auto_save:
        _save_profile(target, profile)
        date_tag = date.today().isoformat()
        _FORTUNE_CACHE.pop(f"{target}:{date_tag}", None)
        return {
            "status": "complete",
            "mode": mode,
            "name": target,
            "profile": profile,
        }
    # 승인 대기 — 호출측에서 queue_approval 로 저장 후 소유자에게 전달
    return {
        "status": "pending_approval",
        "mode": mode,
        "name": target,
        "profile": profile,
    }


_TIME_WORD_FILTERS = {
    "오늘", "오늘의", "내일", "내일의", "이번", "이번주", "이번주의",
    "모레", "어제", "그제", "요즘", "지금",
}

# 사주 용어 — "경금일간 사주" 같은 일반 질문이 프로필 이름으로 잘못 추출되는 것 방지
_SAJU_TERM_SUFFIXES = ("일간", "일주", "월주", "년주", "시주", "오행")
_SAJU_TERM_EXACT = {
    "갑목", "을목", "병화", "정화", "무토",
    "기토", "경금", "신금", "임수", "계수",
    "일간", "일주", "월주", "년주", "시주",
    "천간", "지지", "오행", "상생", "상극",
}


def _is_saju_term(name: str) -> bool:
    if name in _SAJU_TERM_EXACT:
        return True
    return any(name.endswith(suf) for suf in _SAJU_TERM_SUFFIXES)


def extract_fortune_target(text: str) -> Optional[str]:
    """Capture name preceding '운세' / '사주' / '점괘'. Returns None for default user."""
    if not text:
        return None
    m = re.search(
        r'([가-힣]{2,4})\s*'
        r'(?:은|는|이|가|의|아|야)?\s*'
        r'(?:오늘의?|내일의?|이번주의?|이번\s*주의?)?\s*'
        r'(?:운세|사주|점괘)',
        text,
    )
    if not m:
        return None
    name = m.group(1)
    if name in _TIME_WORD_FILTERS:
        return None
    if _is_saju_term(name):
        return None
    return name


def resolve_profile(target: Optional[str]) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    profiles = _load_profiles()
    if not target:
        return ("default", profiles.get("default"))
    if target in profiles:
        return (target, profiles[target])
    for key, p in profiles.items():
        if key == "default":
            continue
        if target in (p.get("aliases") or []):
            return (key, p)
    if len(target) >= 3 and target[-1] in _KO_PARTICLES:
        return resolve_profile(target[:-1])
    return (None, None)


def resolve_profile_for_slack_name(
    slack_display_name: Optional[str],
) -> Tuple[Optional[str], Optional[Dict[str, Any]], bool]:
    """Match a Slack display name to a profile via 3-char 한글 풀네임 substring.

    Aliases/2-char nicknames are NOT used here — 팀명·직급이 바뀌어도
    `...이유송...` 같은 성+이름 트리플은 안정적이라 이것만 신뢰.

    Returns (key, profile, ambiguous):
    - unique match → (key, profile, False)
    - 2+ matches  → (None, None, True)  # 호출측에서 모호성 안내
    - no match    → (None, None, False)
    """
    if not slack_display_name:
        return (None, None, False)
    profiles = _load_profiles()
    matches: List[Tuple[str, Dict[str, Any]]] = []
    for key, p in profiles.items():
        if key == "default":
            continue
        name = (p.get("display_name") or "").strip()
        if len(name) != 3 or not re.fullmatch(r'[가-힣]+', name):
            continue
        if name in slack_display_name:
            matches.append((key, p))
    if len(matches) == 1:
        return (matches[0][0], matches[0][1], False)
    if len(matches) > 1:
        return (None, None, True)
    return (None, None, False)


def _jdn(y: int, m: int, d: int) -> int:
    a = (14 - m) // 12
    yy = y + 4800 - a
    mm = m + 12 * a - 3
    return d + (153 * mm + 2) // 5 + 365 * yy + yy // 4 - yy // 100 + yy // 400 - 32045


def compute_ilji(d: date) -> Dict[str, str]:
    # Reference: 2000-01-01 = 戊午일 (Korean 만세력)
    # JDN(2000-01-01) = 2451545 → (2451545+9)%10 = 4 (戊), (2451545+1)%12 = 6 (午)
    jdn = _jdn(d.year, d.month, d.day)
    gan_idx = (jdn + 9) % 10
    ji_idx = (jdn + 1) % 12
    gan_ko = _GAN_KO[gan_idx]
    ji_ko = _JI_KO[ji_idx]
    return {
        "gan_ko": gan_ko,
        "ji_ko": ji_ko,
        "ko": f"{gan_ko}{ji_ko}",
        "hanja": f"{_GAN_HANJA[gan_idx]}{_JI_HANJA[ji_idx]}",
        "gan_oheng": _GAN_OHENG[gan_ko],
        "ji_oheng": _JI_OHENG[ji_ko],
    }


def _normalize_ilgan_key(ilgan: Optional[str]) -> Optional[str]:
    if not ilgan:
        return None
    s = ilgan.strip()
    if s in _GAN_OHENG:
        return s
    if s in _GAN_KO_FROM_HANJA:
        return _GAN_KO_FROM_HANJA[s]
    return None


def _seeded_picks(seed: str, pool: List[Any], n: int) -> List[Any]:
    if n <= 0 or not pool:
        return []
    h = hashlib.sha256(seed.encode("utf-8")).digest()
    picks: List[Any] = []
    used = set()
    i = 0
    while len(picks) < n and i < 256:
        idx = h[i % len(h)] % len(pool)
        val = pool[idx]
        if val not in used:
            picks.append(val)
            used.add(val)
        i += 1
    while len(picks) < n:
        picks.append(pool[len(picks) % len(pool)])
    return picks


def _build_palettes(ilji: Dict[str, str], ilgan_ko: Optional[str], seed: str) -> Dict[str, Any]:
    gan_oheng = ilji["gan_oheng"]
    color_pool: List[str] = list(_OHENG_COLORS[gan_oheng])
    num_pool: List[int] = list(_OHENG_NUMBERS[gan_oheng])
    if ilgan_ko:
        ilgan_oh = _GAN_OHENG[ilgan_ko]
        if ilgan_oh != gan_oheng:
            color_pool.extend(_OHENG_COLORS[ilgan_oh])
            num_pool.extend(_OHENG_NUMBERS[ilgan_oh])

    # Add seed-variable numbers for more range
    h = hashlib.sha256((seed + "/num").encode()).digest()
    for i in range(6):
        num_pool.append((h[i] % 31) + 1)

    return {
        "colors": _seeded_picks(seed + "/color", color_pool, 2),
        "numbers": _seeded_picks(seed + "/num2", num_pool, 2),
    }


def _relation_hint(ilgan_oh: str, day_gan_oh: str) -> str:
    if day_gan_oh == ilgan_oh:
        return "비겁(안정·결단)"
    if _SHENG[ilgan_oh] == day_gan_oh:
        return "식상(표현·창의)"
    if _SHENG[day_gan_oh] == ilgan_oh:
        return "인성(보호·학습)"
    if _KE[ilgan_oh] == day_gan_oh:
        return "재성(재물·이성)"
    if _KE[day_gan_oh] == ilgan_oh:
        return "관성(압박·기회)"
    return ""


_FORTUNE_SCHEMA: Dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "overall_stars":  {"type": "INTEGER"},
        "overall_line":   {"type": "STRING"},
        "love_stars":     {"type": "INTEGER"},
        "love_line":      {"type": "STRING"},
        "wealth_stars":   {"type": "INTEGER"},
        "wealth_line":    {"type": "STRING"},
        "work_stars":     {"type": "INTEGER"},
        "work_line":      {"type": "STRING"},
        "health_stars":   {"type": "INTEGER"},
        "health_line":    {"type": "STRING"},
        "one_line":       {"type": "STRING"},
    },
    "required": [
        "overall_stars", "overall_line",
        "love_stars", "love_line",
        "wealth_stars", "wealth_line",
        "work_stars", "work_line",
        "health_stars", "health_line",
        "one_line",
    ],
}

_FORTUNE_SYSTEM = (
    "한국어 오늘의 운세 생성기. 동서양 점괘 지식을 활용:\n"
    "- 동양: 일간과 오늘 일진의 오행 관계(비겁·식상·재성·관성·인성), 일진 지지에 해당하는 주역 괘 지혜.\n"
    "- 서양: 요일 지배 행성, 사용자 별자리의 일일 상성.\n"
    "각 운세(총운·애정·재물·업무·건강): stars(1~5 정수) + line(한 문장, 공백 포함 18자 이내).\n"
    "one_line: 동양·서양 근거가 자연스럽게 녹아든 한 문장(공백 포함 45자 이내). "
    "장황한 설명·출처 표기·주석 금지. 명사로 끝나는 단정조.\n"
    "별표 의미: 5=최고, 4=좋음, 3=보통, 2=주의, 1=조심. 하루 특성에 맞춰 변주.\n"
    "운세는 재미 기반 조언. 절대적 단정 금지."
)


def _get_gemini_response(
    system: str,
    contents: str,
    schema: Dict[str, Any],
    *,
    max_tokens: int = 700,
) -> Optional[Dict[str, Any]]:
    if not GEMINI_AVAILABLE:
        logger.warning("Fortune: Gemini SDK not available")
        return None
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        logger.warning("Fortune: GEMINI_API_KEY missing")
        return None
    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=contents,
            config=genai.types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
                response_schema=schema,
                temperature=0.9,
                max_output_tokens=max_tokens,
            ),
        )
        raw = (response.text or "").strip()
        if not raw:
            return None
        return json.loads(raw)
    except Exception as exc:
        logger.warning("Fortune Gemini call failed: %s", exc)
        return None


_FORTUNE_CACHE: Dict[str, str] = {}
_FORTUNE_CACHE_MAX = 32


def _stars(n: Any) -> str:
    try:
        k = int(n)
    except (TypeError, ValueError):
        k = 3
    k = max(1, min(5, k))
    return "★" * k + "☆" * (5 - k)


def _birth_year_short(year: Optional[int]) -> str:
    if not year:
        return "??년"
    return f"{year % 100:02d}년"


def _profile_subline(profile: Dict[str, Any]) -> str:
    parts: List[str] = []
    name = profile.get("display_name") or ""
    if name and name != "기본":
        parts.append(name)
    yr = _birth_year_short(profile.get("birth_year"))
    zko = profile.get("zodiac_ko") or "띠 미등록"
    parts.append(f"{yr} {zko}")
    parts.append(profile.get("zodiac_western") or "별자리 미등록")

    ilgan_raw = profile.get("ilgan")
    ilgan_key = _normalize_ilgan_key(ilgan_raw)
    if ilgan_key:
        oh = _GAN_OHENG[ilgan_key]
        idx = _GAN_KO.index(ilgan_key)
        parts.append(f"일간 {ilgan_key}{_OHENG_KO[oh]}({_GAN_HANJA[idx]})")
    elif ilgan_raw:
        parts.append(f"일간 {ilgan_raw}(확인필요)")
    else:
        parts.append("일간 미등록")
    return " · ".join(parts)


def _render_fortune(
    today: date,
    profile: Dict[str, Any],
    palettes: Dict[str, Any],
    data: Dict[str, Any],
) -> str:
    weekday_ko = "월화수목금토일"[today.weekday()]
    header = f"**🔮 {today.isoformat()} {weekday_ko}요일 오늘의 운세**"
    subline = "`" + _profile_subline(profile) + "`"

    lines = [header, subline, ""]
    lines.append(f"• **총운** {_stars(data.get('overall_stars'))} — {(data.get('overall_line') or '').strip()}")
    lines.append(f"• **애정운** {_stars(data.get('love_stars'))} — {(data.get('love_line') or '').strip()}")
    lines.append(f"• **재물운** {_stars(data.get('wealth_stars'))} — {(data.get('wealth_line') or '').strip()}")
    lines.append(f"• **업무운** {_stars(data.get('work_stars'))} — {(data.get('work_line') or '').strip()}")
    lines.append(f"• **건강운** {_stars(data.get('health_stars'))} — {(data.get('health_line') or '').strip()}")
    lines.append("")
    lines.append("**🎨 행운의 색** " + " · ".join(palettes["colors"]))
    lines.append("**🔢 행운의 숫자** " + " · ".join(str(n) for n in palettes["numbers"]))
    lines.append("")
    lines.append(f"**📜 한마디** {(data.get('one_line') or '').strip()}")
    return "\n".join(lines)


def build_fortune_reply(
    user_text: str,
    *,
    today: Optional[date] = None,
    target_override: Optional[str] = None,
) -> str:
    today = today or date.today()
    target = target_override if target_override else extract_fortune_target(user_text)
    key, profile = resolve_profile(target)

    if profile is None:
        return (
            f"'**{target}**' 운세 프로필이 등록되지 않았어!\n"
            f"• 생년·띠(60갑자)·서양별자리·일간 정보를 받아서 "
            f"`apps/personal-bot/fortune_profiles.json` 에 추가해달라!"
        )

    cache_key = f"{key}:{today.isoformat()}"
    cached = _FORTUNE_CACHE.get(cache_key)
    if cached is not None:
        return cached

    ilji = compute_ilji(today)
    ilgan_ko = _normalize_ilgan_key(profile.get("ilgan"))
    seed = f"{key}:{today.isoformat()}"
    palettes = _build_palettes(ilji, ilgan_ko, seed)

    weekday_ko = "월화수목금토일"[today.weekday()]
    ruler = _WEEKDAY_RULER[today.weekday()]

    lines_in = [
        f"오늘 날짜: {today.isoformat()} ({weekday_ko}요일)",
        f"오늘 일진: {ilji['ko']}({ilji['hanja']}) — "
        f"천간 오행 {_OHENG_KO[ilji['gan_oheng']]}, 지지 오행 {_OHENG_KO[ilji['ji_oheng']]}",
        f"요일 지배 행성: {ruler}",
    ]
    if profile.get("display_name") and profile["display_name"] != "기본":
        lines_in.append(f"대상자: {profile['display_name']}")
    if profile.get("birth_year"):
        lines_in.append(f"생년: {profile['birth_year']}")
    if profile.get("zodiac_ko"):
        lines_in.append(f"동양 띠: {profile['zodiac_ko']}")
    if profile.get("zodiac_western"):
        lines_in.append(f"서양 별자리: {profile['zodiac_western']}")
    if ilgan_ko:
        oh = _GAN_OHENG[ilgan_ko]
        lines_in.append(f"일간: {ilgan_ko}({_OHENG_KO[oh]})")
        rel = _relation_hint(oh, ilji["gan_oheng"])
        if rel:
            lines_in.append(f"일간↔일진 천간 관계: {rel}")

    contents = "\n".join(lines_in)
    data = _get_gemini_response(_FORTUNE_SYSTEM, contents, _FORTUNE_SCHEMA)
    if not data:
        return "운세 생성 실패! 잠시 후 다시 시도해달라!"

    rendered = _render_fortune(today, profile, palettes, data)
    if len(_FORTUNE_CACHE) < _FORTUNE_CACHE_MAX:
        _FORTUNE_CACHE[cache_key] = rendered
    return rendered
