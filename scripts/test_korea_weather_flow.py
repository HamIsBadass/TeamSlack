"""Standalone E2E test for the proposed 쥐피티 weather flow.

Flow:
    user text  -->  Gemini geocoder (structured output)  -->  k-skill-proxy /v1/korea-weather/forecast  -->  format

Policy:
    - Gemini 가 한국 지명을 못 찾으면 안내만 한다. 서울로 기본 폴백하지 않는다.
    - 비한국 지명(도쿄 등)도 못 찾음 처리한다 (한국 기상청 API 대상이므로).

Run:
    cd <repo-root>
    .venv/Scripts/python.exe scripts/test_korea_weather_flow.py
"""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional, TypedDict

from google import genai
from google.genai import types as genai_types


REPO_ROOT = Path(__file__).resolve().parents[1]
PROXY_BASE = os.environ.get("KSKILL_PROXY_BASE_URL") or "https://k-skill-proxy.nomadamas.org"


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


_load_dotenv(REPO_ROOT / ".env")


class GeocodeResult(TypedDict, total=False):
    found: bool
    place: str
    lat: float
    lon: float
    reason: str


GEOCODE_SCHEMA = {
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

GEOCODE_SYSTEM = (
    "사용자의 날씨 질문에서 지명을 추출해 WGS84 lat/lon 과 에어코리아 측정소 힌트를 반환한다. "
    "status 4가지 중 하나:\n"
    "- 'ok': 한국 내 구체 지명 확정. place/lat/lon/region_hint 전부 채움.\n"
    "- 'non_korea': 한국 외 지역. place 만.\n"
    "- 'missing': 지명 전혀 없음.\n"
    "- 'ambiguous': 지명 있으나 너무 광범위.\n"
    "region_hint 규칙 (status=ok 일 때만):\n"
    "  - 에어코리아 측정소명에 가장 가까운 한국 행정구역 표기.\n"
    "  - 서울 안: 해당 '구' 이름 (예: '강남구', '용산구', '종로구').\n"
    "  - 서울 외 광역시/도내 '구': 해당 '구' 이름 (예: '광진구'는 그대로).\n"
    "  - 경기/강원 중소도시: 도시명 (예: '수원', '성남', '강릉'). 매칭 실패 가능성 있음.\n"
    "  - 광역시도만 있으면: 광역명 (예: '부산', '제주').\n"
    "  - 판교/여의도 등 특정 지구: 가장 가까운 구/시 (예: 판교→'성남', 여의도→'영등포구').\n"
    "좌표 규칙: lat 33~39, lon 124~132. 소수점 4자리. 확신 낮으면 'ambiguous'."
)

YONGSAN_DEFAULT = {"place": "서울 용산구", "lat": 37.5326, "lon": 126.9905, "region_hint": "용산구"}


def geocode(text: str, *, client: genai.Client) -> dict:
    response = client.models.generate_content(
        model="gemini-2.5-flash-lite",
        contents=f"사용자 문장: {text}",
        config=genai_types.GenerateContentConfig(
            system_instruction=GEOCODE_SYSTEM,
            response_mime_type="application/json",
            response_schema=GEOCODE_SCHEMA,
            temperature=0.0,
            max_output_tokens=150,
        ),
    )
    raw = (response.text or "").strip()
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
            return {"status": "ambiguous", "reason": f"좌표가 한국 범위 벗어남 ({lat},{lon})"}
        return {
            "status": "ok",
            "place": data.get("place") or "",
            "lat": lat,
            "lon": lon,
            "region_hint": data.get("region_hint") or "",
        }

    return {"status": status, "place": data.get("place") or "", "reason": data.get("reason") or ""}


def fetch_weather(lat: float, lon: float) -> Optional[dict]:
    qs = urllib.parse.urlencode({"lat": f"{lat:.4f}", "lon": f"{lon:.4f}"})
    url = f"{PROXY_BASE}/v1/korea-weather/forecast?{qs}"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "teamslack-weather/0.1 (+personal-bot)",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_fine_dust(region_hint: str) -> Optional[dict]:
    """에어코리아 측정소 검색. 실패 시 None (best-effort)."""
    if not region_hint:
        return None
    qs = urllib.parse.urlencode({"regionHint": region_hint})
    url = f"{PROXY_BASE}/v1/fine-dust/report?{qs}"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "teamslack-weather/0.1 (+personal-bot)",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def dust_line(dust: Optional[dict]) -> str:
    """에어코리아 응답을 한 줄로. 실패/빈 응답이면 빈 문자열."""
    if not dust:
        return ""
    pm10 = (dust.get("pm10") or {})
    pm25 = (dust.get("pm25") or {})
    pm10_val = pm10.get("value") or "?"
    pm10_grade = pm10.get("grade") or ""
    pm25_val = pm25.get("value") or "?"
    pm25_grade = pm25.get("grade") or ""
    khai = dust.get("khai_grade") or ""
    station = dust.get("station_name") or ""
    if pm10_val == "?" and pm25_val == "?":
        return ""
    parts = [f"미세먼지(PM10) {pm10_val} {pm10_grade}".rstrip(), f"초미세먼지(PM2.5) {pm25_val} {pm25_grade}".rstrip()]
    if khai:
        parts.append(f"통합 {khai}")
    tail = f" (기준: 에어코리아 {station})" if station else ""
    return ", ".join(parts) + "." + tail


def summarize(payload: dict, *, place: str, dust: Optional[dict] = None) -> str:
    items = (payload.get("response") or {}).get("body", {}).get("items", {}).get("item") or []
    if not items:
        return f"{place} 예보 데이터가 비었다! 발표 시각이 아직 안 됐을 수 있다곰."

    base_date = items[0].get("baseDate", "")
    base_time = items[0].get("baseTime", "")

    first_slot_time = items[0].get("fcstTime")
    first_slot = [it for it in items if it.get("fcstTime") == first_slot_time]

    fields: dict[str, str] = {}
    for it in first_slot:
        fields[it.get("category", "")] = str(it.get("fcstValue", ""))

    sky_map = {"1": "맑음", "3": "구름많음", "4": "흐림"}
    pty_map = {"0": "", "1": "비", "2": "비/눈", "3": "눈", "4": "소나기"}
    sky = sky_map.get(fields.get("SKY", ""), fields.get("SKY", ""))
    pty = pty_map.get(fields.get("PTY", ""), "")
    sky_text = pty if pty else sky

    tmp = fields.get("TMP", "?")
    pop = fields.get("POP", "?")
    reh = fields.get("REH", "?")
    wsd = fields.get("WSD", "?")

    line1 = f"{place} 지금 기온 {tmp}°C, {sky_text}, 습도 {reh}%, 풍속 {wsd}m/s다!"
    line2 = f"강수확률 {pop}%. 기준: KMA 단기예보 발표 {base_date} {base_time}."
    dust_text = dust_line(dust)
    if dust_text:
        return f"{line1}\n{dust_text}\n{line2}"
    return f"{line1}\n{line2}"


PERPLEXITY_URL = "https://api.perplexity.ai/chat/completions"

PERPLEXITY_WEATHER_SYSTEM = (
    "한국 외 지역 날씨 질문에 답한다. "
    "정확히 3줄로만 출력한다. 서론·출처([1],[2] 등)·추가 설명 금지.\n"
    "1번째 줄: '{지명} 지금 기온 N°C, {하늘상태}, 습도 N%, 풍속 N m/s다!' (수치는 최신 값).\n"
    "2번째 줄: '대기질지수 AQI N ({등급}).' — 최신 AQI 수치와 등급(예: 좋음/보통/나쁨/매우나쁨) 그대로.\n"
    "3번째 줄: '강수확률 N%. 기준: 현지 기상 기관 {기관명} 최신 발표.' 형식."
)


def fallback_perplexity(user_text: str, place_hint: str) -> str:
    api_key = os.environ.get("PERPLEXITY_API_KEY")
    if not api_key:
        return f"[Perplexity fallback stub] '{place_hint or user_text}' 해외 날씨 경로. 실제 봇에선 Perplexity sonar-pro 호출."
    body = {
        "model": "sonar-pro",
        "messages": [
            {"role": "system", "content": PERPLEXITY_WEATHER_SYSTEM},
            {"role": "user", "content": user_text},
        ],
        "temperature": 0.1,
        "max_tokens": 200,
    }
    req = urllib.request.Request(
        PERPLEXITY_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
    import re
    content = re.sub(r"\[\d+\]", "", content).strip()
    return content


def handle(user_text: str, *, client: genai.Client) -> tuple[str, str]:
    """Return (route_label, response_text) for inspection."""
    geo = geocode(user_text, client=client)
    status = geo.get("status")

    if status == "ok":
        payload = fetch_weather(geo["lat"], geo["lon"])
        if not payload:
            return "ok_but_empty", f"{geo['place']} 날씨 데이터를 못 가져왔다!"
        dust = fetch_fine_dust(geo.get("region_hint") or "")
        return "ok", summarize(payload, place=geo["place"], dust=dust)

    if status == "non_korea":
        return "non_korea_perplexity", fallback_perplexity(user_text, geo.get("place", ""))

    if status == "missing":
        payload = fetch_weather(YONGSAN_DEFAULT["lat"], YONGSAN_DEFAULT["lon"])
        if not payload:
            return "missing_fallback_empty", "기본 위치(서울 용산구) 날씨 조회 실패."
        dust = fetch_fine_dust(YONGSAN_DEFAULT["region_hint"])
        text = summarize(payload, place=YONGSAN_DEFAULT["place"], dust=dust)
        return "missing_yongsan_default", f"(위치 미지정 → 기본: 용산구)\n{text}"

    if status == "ambiguous":
        hint = geo.get("place") or "입력된 위치"
        return "ambiguous_reask", (
            f"'{hint}'는 너무 광범위하다! 구체적인 시/구/동이나 랜드마크로 다시 알려줘."
        )

    return "unknown", f"지명 판정 실패. status={status}, reason={geo.get('reason', '?')}"


WEATHER_KEYWORDS = (
    "날씨", "기온", "온도",
    "비와", "비 와", "비 옴", "비옴", "눈와", "눈 와", "소나기",
    "춥", "추워", "추운", "추위",
    "덥", "더워", "더운", "더위",
    "맑", "흐림", "흐려", "폭염", "한파", "미세먼지", "황사",
)


def is_weather_query(text: str) -> bool:
    t = (text or "").lower()
    return any(kw in t for kw in WEATHER_KEYWORDS)


TEST_CASES = [
    "서울 시청 지금 날씨 어때?",
    "부산 날씨 알려줘",
    "판교 테크노밸리 오늘 비와?",
    "여의도 지금 기온 몇도야?",
    "제주도 지금 날씨",
    "강릉 지금 추워?",
    "날씨 어때?",
    "도쿄 날씨 알려줘",
    "ㅇㄹㅇㄹㅇㄹ",
    "한강 근처 날씨",
]


def main() -> int:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: GEMINI_API_KEY not set", file=sys.stderr)
        return 2
    client = genai.Client(api_key=api_key)

    print(f"PROXY: {PROXY_BASE}")
    print(f"MODEL: gemini-2.5-flash-lite")
    print("=" * 70)

    for i, query in enumerate(TEST_CASES, 1):
        print(f"\n[{i}/{len(TEST_CASES)}] 입력: {query}")
        if not is_weather_query(query):
            print("  intent: not_weather → (skip weather flow, 기존 DM 채팅 경로로 위임)")
            continue
        print("  intent: weather")
        try:
            route, result = handle(query, client=client)
            print(f"  route: {route}")
            print("  응답:")
            for line in (result or "(empty)").splitlines():
                print(f"    {line}")
        except Exception as exc:
            print(f"  ERROR: {type(exc).__name__}: {exc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
