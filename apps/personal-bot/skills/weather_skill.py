"""Weather skill — 한국 기상청 단기예보 + 에어코리아 미세먼지 (k-skill-proxy 경유).

원본은 `socket_mode_runner.py` 에 인라인되어 있던 `# === Weather + fine-dust ===` 블록.
통합 경로·엔드포인트·폴백 체인은 [weather_skill.md](weather_skill.md) 참조.

런너 의존성 (`_perplexity_search`, `_record_llm_cost_tokens` 등) 은 순환 import 방지
목적으로 함수 내부 지연 import 로 접근한다.
"""

import json
import logging
import os
import re
import time
from datetime import date, timedelta
from typing import Any, Dict, Optional

import requests

try:
    from google import genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

from ._base import SkillBase, SkillContext

logger = logging.getLogger(__name__)


# =============== 상수 ===============

_WEATHER_KEYWORDS: tuple[str, ...] = (
    "날씨", "기온", "온도",
    "비와", "비 와", "비 옴", "비옴", "눈와", "눈 와", "소나기",
    "춥", "추워", "추운", "추위",
    "덥", "더워", "더운", "더위",
    "맑", "흐림", "흐려", "폭염", "한파", "미세먼지", "황사",
)

_YONGSAN_DEFAULT: Dict[str, Any] = {
    "place": "서울 용산구",
    "lat": 37.5326,
    "lon": 126.9905,
    "region_hint": "용산구",
}

_GEOCODE_SCHEMA: Dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "status": {
            "type": "STRING",
            "enum": ["ok", "non_korea", "missing", "ambiguous"],
        },
        "place": {"type": "STRING"},
        "lat": {"type": "NUMBER"},
        "lon": {"type": "NUMBER"},
        "region_hint": {"type": "STRING"},
        "reason": {"type": "STRING"},
    },
    "required": ["status"],
}

_GEOCODE_SYSTEM = (
    "사용자의 날씨 질문에서 지명을 추출해 WGS84 lat/lon 과 에어코리아 측정소 힌트를 반환한다. "
    "status 4가지 중 하나:\n"
    "- 'ok': 한국 내 구체 지명 확정. place/lat/lon/region_hint 전부 채움.\n"
    "- 'non_korea': 한국 외 지역. place 만.\n"
    "- 'missing': 지명 전혀 없음.\n"
    "- 'ambiguous': 지명 있으나 너무 광범위.\n"
    "region_hint 규칙 (status=ok 일 때만):\n"
    "  - 에어코리아 측정소명에 가장 가까운 한국 행정구역 표기.\n"
    "  - 서울 안: 해당 '구' 이름 (예: '강남구', '용산구', '종로구').\n"
    "  - 서울 외 광역시/도내 '구': 해당 '구' 이름.\n"
    "  - 경기/강원 중소도시: 도시명 (예: '수원', '성남', '강릉'). 매칭 실패 가능성 있음.\n"
    "  - 광역시도만 있으면: 광역명 (예: '부산', '제주').\n"
    "  - 판교/여의도 등 특정 지구: 가장 가까운 구/시 (예: 판교→'성남', 여의도→'영등포구').\n"
    "좌표 규칙: lat 33~39, lon 124~132. 소수점 4자리. 확신 낮으면 'ambiguous'."
)

_PERPLEXITY_WEATHER_SYSTEM = (
    "한국 외 지역 날씨 질문에 답한다. "
    "정확히 4줄로만 출력한다. 서론·출처([1],[2] 등)·추가 설명 금지. 볼드는 **로 감싼 마크다운을 사용한다.\n"
    "1번째 줄: '**{지명}** 지금 **N°C**, {하늘상태}!' — '이다/다' 같은 서술어미 금지, 하늘상태 뒤는 바로 '!'.\n"
    "2번째 줄: '• 습도 **N%** · 풍속 **N m/s** · 강수확률 **N%**'\n"
    "3번째 줄: '• 대기질지수 AQI **N ({등급})**' — 최신 AQI 수치와 등급(좋음/보통/나쁨/매우나쁨).\n"
    "4번째 줄: '`현지 기상 기관 {기관명} 최신 발표`' (백틱으로 감싼 inline code 형식)."
)

_WEATHER_GEOCODE_CACHE: Dict[str, Dict[str, Any]] = {}
_WEATHER_CACHE_MAX = 64

_SKY_MAP = {"1": "맑음", "3": "구름많음", "4": "흐림"}
_PTY_MAP = {"0": "", "1": "비", "2": "비/눈", "3": "눈", "4": "소나기"}

_WEATHER_DATE_KEYWORDS: Dict[str, int] = {
    "그저께": -2, "그제": -2,
    "어제": -1,
    "오늘": 0,
    "내일": 1,
    "모레": 2,
    "글피": 3,
    "그글피": 4,
}

_OFFSET_WORD_MAP = {-2: "그제", -1: "어제", 0: "지금", 1: "내일", 2: "모레"}


# =============== 런너 의존성 (지연 import) ===============

def _call_runner(fn_name: str, *args, **kwargs):
    """런너 모듈의 함수를 지연 호출. 순환 import 회피."""
    import socket_mode_runner
    return getattr(socket_mode_runner, fn_name)(*args, **kwargs)


# =============== 공용 유틸 ===============

def _kskill_proxy_base() -> str:
    return os.getenv("KSKILL_PROXY_BASE_URL", "").strip().rstrip("/")


def _ko_has_batchim(word: str) -> bool:
    if not word:
        return False
    last = word.strip()[-1]
    code = ord(last)
    if 0xAC00 <= code <= 0xD7A3:
        return (code - 0xAC00) % 28 != 0
    return False


def _ko_eun_neun(word: str) -> str:
    if not word:
        return "는"
    return "은" if _ko_has_batchim(word) else "는"


# =============== intent ===============

def _is_weather_query(user_text: str) -> bool:
    text = (user_text or "").lower()
    if not text:
        return False
    return any(kw in text for kw in _WEATHER_KEYWORDS)


# =============== geocode (Gemini structured output) ===============

def _geocode_korean_place(user_text: str) -> Dict[str, Any]:
    if not GEMINI_AVAILABLE:
        return {"status": "ambiguous", "reason": "Gemini 미구성"}

    cache_key = (user_text or "").strip()
    cached = _WEATHER_GEOCODE_CACHE.get(cache_key)
    if cached is not None:
        return cached

    try:
        api_key = _call_runner("_required_env", "GEMINI_API_KEY")
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=f"사용자 문장: {user_text}",
            config=genai.types.GenerateContentConfig(
                system_instruction=_GEOCODE_SYSTEM,
                response_mime_type="application/json",
                response_schema=_GEOCODE_SCHEMA,
                temperature=0.0,
                max_output_tokens=150,
            ),
        )
        _call_runner(
            "_record_llm_cost_tokens",
            _call_runner("_gemini_api_name", "gemini-2.5-flash-lite"),
            tokens=_call_runner("_extract_gemini_tokens", response),
            metadata={"feature": "weather_geocode"},
        )
        raw = (response.text or "").strip()
    except Exception as exc:
        logger.warning(f"Weather geocode failed: {exc}")
        return {"status": "ambiguous", "reason": f"geocode exception: {exc}"}

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"status": "ambiguous", "reason": f"JSON parse fail: {raw[:80]}"}

    status = data.get("status") or "ambiguous"
    if status == "ok":
        try:
            lat = float(data["lat"])
            lon = float(data["lon"])
        except (KeyError, TypeError, ValueError):
            return {"status": "ambiguous", "reason": "lat/lon 누락"}
        if not (33.0 <= lat <= 39.5 and 124.0 <= lon <= 132.0):
            return {"status": "ambiguous", "reason": f"좌표 범위 벗어남 ({lat},{lon})"}
        result: Dict[str, Any] = {
            "status": "ok",
            "place": data.get("place") or "",
            "lat": lat,
            "lon": lon,
            "region_hint": data.get("region_hint") or "",
        }
    else:
        result = {
            "status": status,
            "place": data.get("place") or "",
            "reason": data.get("reason") or "",
        }

    if len(_WEATHER_GEOCODE_CACHE) < _WEATHER_CACHE_MAX:
        _WEATHER_GEOCODE_CACHE[cache_key] = result
    return result


# =============== proxy fetch ===============

def _fetch_korea_weather(lat: float, lon: float) -> Optional[Dict[str, Any]]:
    """KMA 단기예보 via k-skill-proxy `/v1/korea-weather/forecast`. 1회 재시도."""
    base = _kskill_proxy_base()
    if not base:
        return None
    qs = f"lat={lat:.4f}&lon={lon:.4f}"
    url = f"{base}/v1/korea-weather/forecast?{qs}"
    headers = {
        "Accept": "application/json",
        "User-Agent": "teamslack-personal-bot/0.1",
    }
    for attempt in (1, 2):
        try:
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            if attempt == 2:
                logger.warning(f"Korea weather fetch failed (attempt {attempt}): {exc}")
                return None
            time.sleep(0.8)
    return None


def _fetch_fine_dust(region_hint: str) -> Optional[Dict[str, Any]]:
    """에어코리아 측정소 조회 via k-skill-proxy `/v1/fine-dust/report`."""
    base = _kskill_proxy_base()
    if not base or not region_hint:
        return None
    url = f"{base}/v1/fine-dust/report?regionHint={requests.utils.quote(region_hint)}"
    try:
        response = requests.get(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "teamslack-personal-bot/0.1",
            },
            timeout=12,
        )
        if response.status_code >= 400:
            return None
        return response.json()
    except Exception:
        return None


# =============== 렌더링 ===============

def _dust_line(dust: Optional[Dict[str, Any]]) -> str:
    if not dust:
        return ""
    pm10 = dust.get("pm10") or {}
    pm25 = dust.get("pm25") or {}
    pm10_val = pm10.get("value") or "?"
    pm25_val = pm25.get("value") or "?"
    if pm10_val == "?" and pm25_val == "?":
        return ""
    pm10_grade = pm10.get("grade") or ""
    pm25_grade = pm25.get("grade") or ""
    khai = dust.get("khai_grade") or ""

    pm10_inner = f"{pm10_val} ({pm10_grade})" if pm10_grade else pm10_val
    pm25_inner = f"{pm25_val} ({pm25_grade})" if pm25_grade else pm25_val
    parts = [f"PM10 **{pm10_inner}**", f"PM2.5 **{pm25_inner}**"]
    if khai:
        parts.append(f"통합 **{khai}**")
    return "• 미세먼지 " + " / ".join(parts)


def _summarize_korea_weather(
    payload: Dict[str, Any],
    *,
    place: str,
    dust: Optional[Dict[str, Any]],
    target_date: Optional[str] = None,
    offset_word: str = "지금",
) -> str:
    items = (payload.get("response") or {}).get("body", {}).get("items", {}).get("item") or []
    if not items:
        return f"**{place}** 예보 데이터가 비었다! 발표 시각이 아직 안 됐을 수 있다!"

    base_date = items[0].get("baseDate", "")
    base_time = items[0].get("baseTime", "")

    if target_date:
        filtered = [it for it in items if it.get("fcstDate") == target_date]
        if not filtered:
            return f"**{place}** {offset_word} 예보 데이터가 비었다!"
        times = sorted({it.get("fcstTime") for it in filtered if it.get("fcstTime")})
        if not times:
            return f"**{place}** {offset_word} 예보 데이터가 비었다!"
        target_time = min(times, key=lambda t: abs(int(t) - 1200))
        slot = [it for it in filtered if it.get("fcstTime") == target_time]
        fields: Dict[str, str] = {}
        for it in slot:
            fields[it.get("category", "")] = str(it.get("fcstValue", ""))
        tmn = next(
            (str(it.get("fcstValue")) for it in filtered if it.get("category") == "TMN"),
            None,
        )
        tmx = next(
            (str(it.get("fcstValue")) for it in filtered if it.get("category") == "TMX"),
            None,
        )
        sky = _SKY_MAP.get(fields.get("SKY", ""), fields.get("SKY", ""))
        pty = _PTY_MAP.get(fields.get("PTY", ""), "")
        sky_text = pty if pty else sky

        if tmn and tmx:
            header = f"**{place}** {offset_word} 최저 **{tmn}°C** / 최고 **{tmx}°C**, {sky_text}!"
        else:
            tmp = fields.get("TMP", "?")
            header = f"**{place}** {offset_word} **{tmp}°C**, {sky_text}!"
        pop = fields.get("POP", "?")
        reh = fields.get("REH", "?")
        wsd = fields.get("WSD", "?")
        metrics = f"• 습도 **{reh}%** · 풍속 **{wsd}m/s** · 강수확률 **{pop}%**"
        lines = [header, metrics]
        lines.append("`" + f"KMA 단기예보 {base_date} {base_time}".strip() + "`")
        return "\n".join(lines)

    first_slot_time = items[0].get("fcstTime")
    first_slot = [it for it in items if it.get("fcstTime") == first_slot_time]

    fields = {}
    for it in first_slot:
        fields[it.get("category", "")] = str(it.get("fcstValue", ""))

    sky = _SKY_MAP.get(fields.get("SKY", ""), fields.get("SKY", ""))
    pty = _PTY_MAP.get(fields.get("PTY", ""), "")
    sky_text = pty if pty else sky

    tmp = fields.get("TMP", "?")
    pop = fields.get("POP", "?")
    reh = fields.get("REH", "?")
    wsd = fields.get("WSD", "?")

    header = f"**{place}** 지금 **{tmp}°C**, {sky_text}!"
    metrics = f"• 습도 **{reh}%** · 풍속 **{wsd}m/s** · 강수확률 **{pop}%**"
    lines = [header, metrics]

    dust_text = _dust_line(dust)
    if dust_text:
        lines.append(dust_text)

    source_parts = [f"KMA 단기예보 {base_date} {base_time}".strip()]
    if dust:
        station = (dust.get("station_name") or "").strip()
        if station and dust_text:
            source_parts.append(f"에어코리아 {station}")
    lines.append("`" + " · ".join(source_parts) + "`")
    return "\n".join(lines)


# =============== Perplexity 폴백 (해외·과거) ===============

def _weather_perplexity_non_korea(user_text: str) -> str:
    try:
        return _call_runner(
            "_perplexity_search",
            user_text,
            system_prompt=_PERPLEXITY_WEATHER_SYSTEM,
            remove_citations=True,
            apply_gom_style=False,
            format_for_slack_output=False,
        )
    except Exception as exc:
        logger.warning(f"Weather Perplexity fallback failed: {exc}")
        return "해외 날씨 조회 실패! 잠시 후 다시 시도해달라!"


def _parse_weather_date_offset(text: str) -> int:
    t = text or ""
    for kw in sorted(_WEATHER_DATE_KEYWORDS, key=len, reverse=True):
        if kw in t:
            return _WEATHER_DATE_KEYWORDS[kw]
    m = re.search(r'(\d+)\s*일\s*(?:후|뒤)', t)
    if m:
        return int(m.group(1))
    m = re.search(r'(\d+)\s*일\s*(?:전|앞)', t)
    if m:
        return -int(m.group(1))
    return 0


def _offset_word(offset: int) -> str:
    if offset in _OFFSET_WORD_MAP:
        return _OFFSET_WORD_MAP[offset]
    if offset < 0:
        return f"{abs(offset)}일 전"
    return f"{offset}일 뒤"


def _past_weather_system(target: date, offset_word: str) -> str:
    iso = target.isoformat()
    return (
        f"대상 날짜: {iso} ({offset_word}). 한국 지역 과거 관측 기상·대기질 답변.\n"
        "출처는 기상청 ASOS/AWS 관측자료, 에어코리아 과거자료를 우선 참조. "
        "부족 시 네이버/Google 날씨 기록 보완.\n"
        "정확히 4줄. 서론·출처번호([1] 등)·추가 설명 금지. 볼드는 ** 마크다운.\n"
        "1번째: '**<지명>** " + offset_word + " 최저 **N°C** / 최고 **N°C**, <하늘상태>!'\n"
        "2번째: '• 강수량 **Nmm** · 평균습도 **N%** · 평균풍속 **N m/s**'\n"
        "3번째: '• 미세먼지 PM10 **N (등급)** / PM2.5 **N (등급)** / 통합 **등급**'\n"
        "4번째: '`기상청 ASOS 관측자료 · 에어코리아 과거자료 " + iso + "`' (백틱 inline code)."
    )


def _weather_past_perplexity(user_text: str, *, offset: int) -> str:
    target = date.today() + timedelta(days=offset)
    off_word = _offset_word(offset)
    system = _past_weather_system(target, off_word)
    query = f"{user_text} (대상 날짜: {target.isoformat()})"
    try:
        return _call_runner(
            "_perplexity_search",
            query,
            system_prompt=system,
            remove_citations=True,
            apply_gom_style=False,
            format_for_slack_output=False,
        )
    except Exception as exc:
        logger.warning("Weather past Perplexity failed: %s", exc)
        return "과거 날씨 조회 실패! 잠시 후 다시 시도해달라!"


def _unsupported_future_weather_reply(place: str, offset: int) -> str:
    off_word = _offset_word(offset)
    place_disp = place or _YONGSAN_DEFAULT["place"]
    return (
        f"**{place_disp}** {off_word} 예보는 지원하지 않아!\n"
        f"• 기상청 단기예보는 오늘/내일/모레만 제공해!\n"
        f"`k-skill-proxy /v1/korea-weather/forecast 지원 범위 초과`"
    )


# =============== 메인 분기 ===============

def _build_weather_reply(user_text: str) -> Optional[str]:
    if not _kskill_proxy_base():
        logger.info("KSKILL_PROXY_BASE_URL not set — weather flow skipped")
        return None

    offset = _parse_weather_date_offset(user_text)

    if offset < 0:
        return _weather_past_perplexity(user_text, offset=offset)

    geo = _geocode_korean_place(user_text)
    status = geo.get("status")

    if offset >= 3:
        place = ""
        if status in ("ok", "ambiguous"):
            place = geo.get("place") or ""
        return _unsupported_future_weather_reply(place, offset)

    today = date.today()
    target_date_str: Optional[str] = None
    off_word = "지금"
    if offset > 0:
        target_date_str = (today + timedelta(days=offset)).strftime("%Y%m%d")
        off_word = _offset_word(offset)

    if status == "ok":
        payload = _fetch_korea_weather(geo["lat"], geo["lon"])
        if not payload:
            return f"**{geo.get('place') or '해당 지역'}** 날씨 데이터를 못 가져왔다! 잠시 후 다시 시도해달라!"
        dust = _fetch_fine_dust(geo.get("region_hint") or "") if offset == 0 else None
        return _summarize_korea_weather(
            payload,
            place=geo.get("place") or "",
            dust=dust,
            target_date=target_date_str,
            offset_word=off_word,
        )

    if status == "non_korea":
        if offset == 0:
            return _weather_perplexity_non_korea(user_text)
        target = today + timedelta(days=offset)
        return _weather_perplexity_non_korea(
            f"{user_text} (대상 날짜: {target.isoformat()}, {off_word})"
        )

    if status == "missing":
        payload = _fetch_korea_weather(_YONGSAN_DEFAULT["lat"], _YONGSAN_DEFAULT["lon"])
        if not payload:
            return "기본 위치(**서울 용산구**) 날씨 조회 실패! 지명을 직접 알려달라!"
        dust = _fetch_fine_dust(_YONGSAN_DEFAULT["region_hint"]) if offset == 0 else None
        return _summarize_korea_weather(
            payload,
            place=_YONGSAN_DEFAULT["place"],
            dust=dust,
            target_date=target_date_str,
            offset_word=off_word,
        )

    if status == "ambiguous":
        hint = geo.get("place") or "입력된 위치"
        josa = _ko_eun_neun(hint)
        return f"'**{hint}**'{josa} 너무 광범위하다! 구체적인 시/구/동이나 랜드마크로 다시 알려달라!"

    return "지명을 판정하지 못했다! 어느 지역 날씨인지 다시 알려달라!"


# =============== SkillBase wrapper ===============

class WeatherSkill(SkillBase):
    name = "weather"
    status_message = "날씨 확인 중입니다..."

    def matches(self, ctx: SkillContext) -> bool:
        return _is_weather_query(ctx.text)

    def handle(self, ctx: SkillContext) -> Optional[str]:
        # None 반환 시 런너가 기본 검색/챗 라우팅으로 폴백.
        return _build_weather_reply(ctx.text)
