---
name: subway
description: 서울 열린데이터 실시간 지하철 도착정보 조회. k-skill-proxy `/v1/seoul-subway/arrival` 경유
trigger_keywords: [지하철, 도착정보, 열차, "<역명>역 도착", "<역명>역 몇 분"]
---

# Subway (서울 지하철 도착)

## 동작 개요

1. intent 판정:
   - 키워드(`지하철`/`도착정보`/`열차`) 중 하나 포함 OR
   - `[가-힣]{1,6}역` 매치 + (`도착`|`몇 분`|`곧 들어`) 중 하나 조합
2. 역명 추출: `([가-힣]{1,6}역)(?=[^가-힣]|$)` 첫 매치. 여러 역 혼재 시 첫 번째
3. k-skill-proxy 호출: `GET /v1/seoul-subway/arrival?stationName=<역>&startIndex=1&endIndex=20`
4. 응답 `realtimeArrivalList` 를 `(subwayId, updnLine)` 별로 그룹핑, 상위 2건 렌더

## k-skill 통합

**활용 스킬**: `seoul-subway-arrival` (`~/.agents/skills/seoul-subway-arrival/SKILL.md`)

**엔드포인트 매핑**:

| 요청 필드 | 값 | 주석 |
|---|---|---|
| path | `/v1/seoul-subway/arrival` | k-skill-proxy (`KSKILL_PROXY_BASE_URL`) hosted 경유 |
| `stationName` | `사당` (역 접미 제거) | **upstream 서울 Open API 는 역 접미 없는 순수 역명을 기대**. 클라이언트는 `"사당역"` 수신 → `"사당"` 으로 정규화 후 전송 |
| `startIndex` | `1` | **필수 파라미터**. upstream 이 startIndex/endIndex 둘 다 요구. 빈 값이면 `INFO-200 해당하는 데이터가 없습니다` 반환 |
| `endIndex` | `20` | 일반적으로 5~15개 환승·방향 조합이 나옴. 여유 확보 |

**credential**:
- 클라이언트/쥐피티는 서울 Open API 키를 직접 들고 있지 않음
- 프록시 서버에만 upstream API key 존재. 키 유출 없음
- `KSKILL_PROXY_BASE_URL` 미설정 시 `k-skill-proxy.nomadamas.org` 기본 hosted 로 폴백

**응답 스키마 (주요 필드)**:

```json
{
  "errorMessage": {"status": 200, "code": "INFO-000", "total": N},
  "realtimeArrivalList": [
    {
      "subwayId": "1004",        // 1001~1009 + 중앙/경의중앙/공항/경춘/수인분당/신분당/우이신설/서해/경강/GTX-A
      "updnLine": "상행",         // 상행/하행/외선/내선
      "trainLineNm": "불암산행 - 총신대입구(이수)방면",
      "statnNm": "사당",
      "barvlDt": "200",            // 도착 예정 시간 초. 0 은 '도착' 상태
      "arvlMsg2": "3분 20초 후",
      "arvlMsg3": "서울대입구",
      "bstatnNm": "불암산",          // 종착역
      "recptnDt": "2026-04-22 17:08:48"
    }
  ]
}
```

**subwayId → 노선명 매핑** ([subway_engine.py:_LINE_NAME](../subway_engine.py)):
1001 1호선 · 1002 2호선 · 1003 3호선 · 1004 4호선 · 1005 5호선 · 1006 6호선 · 1007 7호선 · 1008 8호선 · 1009 9호선 · 1061 중앙선 · 1063 경의중앙 · 1065 공항철도 · 1067 경춘선 · 1075 수인분당 · 1077 신분당 · 1092 우이신설 · 1093 서해선 · 1081 경강선 · 1032 GTX-A

## 트리거 예시

```
강남역 도착 정보
사당역 몇 분 뒤?
홍대입구역 지하철
서울역 곧 들어오는 열차
```

## 역명 규칙

- **역 접미 필수**: `강남 도착` ❌ → `강남역 도착` ✓ (intent 판정용)
- upstream 전송 시에만 접미 제거
- 여러 역 혼재 시 regex 첫 매치만 사용

## 시간 지정 정책

- upstream 이 **실시간 도착**만 제공 → 특정 시각(`6시 20분`, `18:20`, `오후 2시` 등) 질의는 미지원
- `_has_specific_time()` 으로 시각 표기 감지 시 안내 메시지 반환 ("특정 시각의 시간표 조회는 지원하지 않아!")
- `1시간 뒤` 같은 duration 은 시각으로 보지 않음 (negative lookahead `(?!간)`)
- 시각 표기 + 역명 조합은 intent 로 인정해서 skill 이 가로채야 LLM 으로 빠지지 않음 (`is_subway_query` 가 `_TIME_SPECIFIC_PATTERN` / `_DIRECTION_PATTERN` 포함)

## 응답 포맷

```
🚇 사당역 실시간 도착 · 기준 17:13
• 2호선 내선
  - 성수행: 4분 40초 후 (현재 서초)
  - 성수행: 7분 후 (현재 강남)
• 4호선 상행
  - 불암산행: 사당 도착
  - 불암산행: [4]번째 전역 (대공원)

실시간 데이터라 수초 단위로 변경될 수 있다
```

## 실패 모드

- **`startIndex/endIndex` 누락**: proxy 가 그대로 전달 → upstream `INFO-200 해당하는 데이터가 없습니다`
- **역명 미존재**: 동일 에러. 표기 확인 재시도 필요
- **quota 초과**: upstream 일일 호출 제한 (서울 Open API). 메시지로 노출될 수 있음
- **proxy 장애**: HTTP ≥400 또는 타임아웃 → `"도착 정보 조회 실패!"` + 에러 문자열

## 관련 파일

- [subway_engine.py](../subway_engine.py) — 로직
- `~/.agents/skills/seoul-subway-arrival/SKILL.md` — upstream k-skill 명세
