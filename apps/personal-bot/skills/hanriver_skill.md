---
name: hanriver
description: 한강홍수통제소 실시간 수위/유량 관측값 조회. k-skill-proxy `/v1/han-river/water-level` 경유
trigger_keywords: [수위, 유량, 홍수, 방류, 한강대교, 잠수교, 팔당, 한강]
---

# Han River Water Level (한강 수위/유량)

## 동작 개요

1. intent 판정: `is_han_river_query(text)` — 세 신호 중 하나로 매치
   - 7자리 관측소코드 + 핵심 키워드(`수위/유량/홍수/방류`)
   - 알려진 교량/관측소명(한강대교, 잠수교, 반포대교, …, 팔당댐 등) + 핵심 키워드
   - 한강/북한강/남한강/중랑천/탄천 등 수계 토큰 + 핵심 키워드
2. 힌트 추출:
   - `stationCode`: `\b(\d{7})\b` 우선
   - `stationName`: 사전에 등록된 교량/관측소명 매칭, 없으면 기본값 `"한강대교"` (대표 관측소로 조회)
3. k-skill-proxy 호출:
   - `/v1/han-river/water-level?stationCode=<7자리>` 또는 `?stationName=<교량명>`
4. 응답 렌더:
   - 단일 관측소 → 관측시각, 현재 수위(m), 현재 유량(m³/s), 기준 수위(관심/주의/경보/심각) 중 값 있는 것만
   - `ambiguous_station` → 후보 최대 8개 제시 + 재질의 유도

## k-skill 통합

**활용 스킬**: `han-river-water-level` (`~/.agents/skills/han-river-water-level/SKILL.md`)

**엔드포인트 매핑**:

| 요청 필드 | 값 | 주석 |
|---|---|---|
| path | `/v1/han-river/water-level` | k-skill-proxy hosted (`KSKILL_PROXY_BASE_URL` 미설정 시 `k-skill-proxy.nomadamas.org` 폴백) |
| `stationCode` | 7자리 관측소코드 | 예: `1018683` (한강대교) |
| `stationName` | 교량/관측소명 | 예: `한강대교`, `잠수교`, `팔당댐` |

**credential**:
- 사용자는 HRFCO `ServiceKey` 직접 발급 불필요
- proxy 서버만 upstream `HRFCO_OPEN_API_KEY` 보관

**응답 스키마 (주요 필드)**:

```json
// 정상
{"item": {
  "stationName": "한강대교", "stationCode": "1018683",
  "observedAt": "2026-04-22 14:30",
  "waterLevel": 1.82, "flow": 245.3,
  "attentionLevel": 4.0, "warningLevel": 6.2,
  "alertLevel": 8.5, "seriousLevel": 10.5
}}

// 모호
{"ambiguous_station": true,
 "candidate_stations": [
    {"name": "한강대교", "code": "1018683"},
    {"name": "잠수교", "code": "1018680"}
 ]}
```

## 트리거 예시

```
한강대교 수위 어때
잠수교 유량 알려줘
팔당댐 방류 상황
1018683 수위
한강 수위 어떄
```

## 응답 포맷

```
**🌊 한강대교 · 1018683**
• 관측 시각: 2026-04-22 14:30
• 현재 수위: 1.82m
• 현재 유량: 245.30m³/s
• 기준 수위: 관심 4.00m / 주의 6.20m / 경보 8.50m / 심각 10.50m

`한강홍수통제소 실시간 관측값 기준`
```

ambiguous:

```
**🌊 관측소가 여러 곳 잡혔다!**
구체적인 교량/관측소명이나 7자리 관측소코드로 다시 물어달라!

• 한강대교 (1018683)
• 잠수교 (1018680)
...
```

## 실패 모드

- **proxy 장애/타임아웃**: `"한강 수위 조회 실패!"` + 에러 문자열
- **HRFCO_OPEN_API_KEY 미설정**: proxy 503 → 상위 HTTP 에러로 폴백
- **10분 자료 갱신 지연**: 비어있는 필드는 `-` 로 표기
- **ambiguous_station**: 후보 리스트 제시 후 재질의 유도

## 관련 파일

- [hanriver_engine.py](../hanriver_engine.py) — 로직
- `~/.agents/skills/han-river-water-level/SKILL.md` — upstream k-skill 명세
