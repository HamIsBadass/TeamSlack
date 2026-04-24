---
name: stock
description: KRX 공식 데이터 기반 국내 상장 종목 검색/기본정보/일별 시세. k-skill-proxy `/v1/korean-stock/*` 경유
trigger_keywords: [주가, 종목, 코스피, 코스닥, 종가, 시세, "<6자리코드>", 종목코드]
---

# Stock (한국 주식)

## 동작 개요

1. intent 판정: `is_korean_stock_query(text)` — 3단 신호
   - 시장 토큰(`코스피`/`코스닥`/`코넥스`/`KOSPI`/`KOSDAQ`/`KONEX`/`KRX`)
   - 6자리 종목코드 `\b\d{6}\b` + tail 키워드(`주가/시세/종가/종목코드/...`)
   - 종목명 + tail 키워드 패턴 (`[가-힣A-Za-z0-9&]{1,15}` + 조사? + tail)
2. **제외 키워드** 선행 필터: 환율/달러/원달러/코인/비트코인/금리/국채/나스닥/애플/테슬라 등 → 여기서 걸리면 False 반환해서 **Perplexity Finance 루트로 자연스럽게 위임**
3. 힌트 추출: 6자리 코드 우선, 없으면 종목명 후보
4. k-skill-proxy 호출 순서:
   - 코드 있음 → `trade-info` 를 KOSPI→KOSDAQ→KONEX 순 시도, 실패 시 전일 재시도
   - 코드 없음 → `search` 로 후보 조회 → 단일/정확일치 → `trade-info` 연쇄 호출, 다수 후보는 리스트로 표시
5. 숫자 렌더: 종가(원), 등락(+±.%/±원), 거래량(주), 시가총액(조/억 단위)

## k-skill 통합

**활용 스킬**: `korean-stock-search` (`~/.agents/skills/korean-stock-search/SKILL.md`)

**엔드포인트 매핑**:

| 요청 필드 | 값 | 주석 |
|---|---|---|
| path | `/v1/korean-stock/search` / `/base-info` / `/trade-info` | k-skill-proxy hosted (`KSKILL_PROXY_BASE_URL` 미설정 시 `k-skill-proxy.nomadamas.org` 폴백) |
| `q` | 원문에서 추출된 회사명 후보 | 조사(`은/는/이/가/의/을/를`) 제거 후 tail 키워드 앞까지 |
| `market` | `KOSPI` \| `KOSDAQ` \| `KONEX` | 코드 직행 시 3개 시장 순차 시도 |
| `code` | 6자리 단축코드 | 정규식 `(?<!\d)(\d{6})(?!\d)` |
| `bas_dd` | `YYYYMMDD` | KST 16:00 이전이면 전일 기본. 주말이면 직전 평일로 swap |
| `limit` | 5 | `search` 결과 후보 제한 |

**credential**:
- 사용자는 `KRX_API_KEY` 직접 발급 불필요
- proxy 서버만 upstream KRX Open API key 보관
- 개인봇 → proxy 는 read-only HTTP GET 만

**응답 스키마 (주요 필드)**:

```json
// /search
{"items": [{"market": "KOSPI", "code": "005930", "name": "삼성전자", "english_name": "Samsung Electronics", "listed_at": "1975-06-11"}]}

// /trade-info
{"item": {
  "market": "KOSPI", "code": "005930", "base_date": "20260423",
  "name": "삼성전자",
  "close_price": 84000, "change_price": 1000, "fluctuation_rate": 1.2,
  "open_price": 83000, "high_price": 84500, "low_price": 82800,
  "trading_volume": 12345678, "trading_value": 1030000000000,
  "market_cap": 500000000000000
}}
```

## 트리거 예시

```
삼성전자 주가
005930 시세 어때
SK하이닉스 종가 알려줘
코스피 카카오 기본정보
알테오젠 종목코드
```

## 별칭(alias) 매핑

KRX 색인 정식명과 한국식 축약/별칭이 다른 경우 `_NAME_ALIASES` 에서 치환 후 `/search` 로 전달. 모호한 축약(예: `포스코`는 홀딩스/퓨처엠/인터내셔널 다수)은 의도적으로 **포함하지 않는다**.

| 별칭 | 정식명 |
|---|---|
| 삼전 | 삼성전자 |
| 삼바 | 삼성바이오로직스 |
| 엘지전자 | LG전자 |
| 엘지화학 | LG화학 |
| 엘지에너지솔루션 | LG에너지솔루션 |
| 엘지이노텍 | LG이노텍 |
| 엘지디스플레이 | LG디스플레이 |
| 네이버 | NAVER |
| 현차 | 현대차 |
| 카뱅 | 카카오뱅크 |
| 카페이 | 카카오페이 |
| 셀젠 | 셀트리온 |
| 하닉 | SK하이닉스 |
| 포홀 | POSCO홀딩스 |

추가는 [stock_engine.py](../stock_engine.py) 의 `_NAME_ALIASES` 에 한 줄씩 얹는다. 다중 후보가 있는 축약은 넣지 말고 사용자가 정식명으로 다시 묻게 둔다.

## 제외되는 질문 (Perplexity 로 넘어감)

- `원달러 환율` / `USD KRW`
- `비트코인 시세` / `이더리움`
- `국고채 3년` / `금리 전망`
- `테슬라 주가` / `NVIDIA 실적` / `나스닥`
- `유가` / `금값` / `WTI`

## 응답 포맷

```
📈 삼성전자 (KOSPI · 005930) · 기준 2026-04-23
• 종가: 84,000원 (+1.20%, +1,000원)
• 시/고/저: 83,000원 / 84,500원 / 82,800원
• 거래량: 12,345,678주
• 시가총액: 500조원

KRX 공식 데이터 기준 · 투자 조언 아님
```

후보 여러 건:

```
🔎 '삼성' 검색 결과
• 삼성전자 (KOSPI · 005930)
• 삼성바이오로직스 (KOSPI · 207940)
• 삼성SDI (KOSPI · 006400)
...

구체적으로 종목명 또는 6자리 종목코드로 다시 물어달라!
```

## 실패 모드

- **proxy 장애/타임아웃**: `"주식 검색 실패!"` + 에러 문자열
- **종목 없음**: `"상장 종목을 찾지 못했다!"` 안내
- **휴장일/데이터 미존재**: 자동으로 전일 `bas_dd` 재시도, 그래도 없으면 `"시세를 받아오지 못했다!"`
- **upstream degraded**: `upstream.degraded=true` 반환 시 부분 결과 그대로 렌더 (현재 구현은 단순히 items 만 사용, 플래그 무시)
- **KRX_API_KEY 미설정**: proxy 가 503 — 상위 HTTP 에러로 폴백 메시지

## 관련 파일

- [stock_engine.py](../stock_engine.py) — 로직
- `~/.agents/skills/korean-stock-search/SKILL.md` — upstream k-skill 명세
