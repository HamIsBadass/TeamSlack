---
name: realestate
description: 국토교통부 실거래/전월세 공식 신고 데이터 조회. k-skill-proxy `/v1/real-estate/*` 경유
trigger_keywords: [실거래, 실거래가, 부동산, 매매가, 전세, 월세, 전월세]
---

# Real Estate (한국 부동산 실거래)

## 동작 개요

1. intent 판정: `is_real_estate_query(text)` — 두 신호 중 하나로 매치
   - 핵심 키워드 (`실거래/실거래가/부동산/매매가/전월세/전세/월세`)
   - 자산타입(아파트/오피스텔/빌라/…) + (`매매/거래/가격/시세`) 조합
2. **제외 키워드** 선행 필터: 해외/뉴욕/도쿄/런던/청약/분양 → 여기서 걸리면 False 반환 → Perplexity 루트로 자연 위임
3. 힌트 추출:
   - 지역: `([가-힣]{2,6}(?:구|시|군|동|읍|면))` 첫 매치
   - 자산: 아파트(기본), 오피스텔, 연립/다세대(villa), 단독/다가구(single-house), 상업업무(commercial)
   - 거래유형: `trade`(매매 기본) / `rent`(전세·월세·전월세·임대)
   - 년월: "2024년 3월" · "24년 3월" · "2024-03" · "202403" → 없으면 전월(MOLIT 신고 lag 고려)
4. k-skill-proxy 호출 순서:
   - `/v1/real-estate/region-code?q=<지역>` → `lawd_cd` 5자리 추출 (없으면 "법정동 코드를 찾지 못했다")
   - `/v1/real-estate/<asset>/<deal>?lawd_cd=&deal_ymd=&num_of_rows=100`
5. 요약 렌더:
   - 매매: 거래건수 · 중위가 · 최저 · 최고, 대표 3건 (단지명/동/면적/층/가격/날짜)
   - 전월세: 계약건수 · 보증금 중위 · 월세 평균, 대표 3건 (보증금/월세)

## k-skill 통합

**활용 스킬**: `real-estate-search` (`~/.agents/skills/real-estate-search/SKILL.md`)

**엔드포인트 매핑**:

| 요청 필드 | 값 | 주석 |
|---|---|---|
| path | `/v1/real-estate/region-code` / `/{asset}/{deal}` | k-skill-proxy hosted (`KSKILL_PROXY_BASE_URL` 미설정 시 `k-skill-proxy.nomadamas.org` 폴백) |
| `q` | 지역 토큰 (구/시/군/동/읍/면) | `_RE_REGION_PATTERN` 로 추출 |
| `lawd_cd` | 5자리 법정동 코드 | region-code 응답 `results[0].lawd_cd` |
| `deal_ymd` | 6자리 YYYYMM | 미지정 시 전월. 신고 lag 고려 |
| `num_of_rows` | 100 | 고정 |

**asset / deal 매트릭스**:

| 한글 키워드 | asset | deal |
|---|---|---|
| 아파트 매매 | `apartment` | `trade` |
| 아파트 전세/월세 | `apartment` | `rent` |
| 오피스텔 | `officetel` | `trade`/`rent` |
| 빌라/연립/다세대 | `villa` | `trade`/`rent` |
| 다가구/단독(주택) | `single-house` | `trade`/`rent` |
| 상가/상업업무 | `commercial` | `trade` 전용 (rent 미지원) |

**credential**:
- 사용자는 `DATA_GO_KR_API_KEY` 직접 발급 불필요
- proxy 서버만 upstream MOLIT key 보관

**응답 스키마 (주요 필드)**:

```json
// region-code
{"results": [{"lawd_cd": "11680", "name": "서울특별시 강남구"}]}

// apartment/trade
{"items": [{"name": "래미안 퍼스티지", "district": "반포동",
             "area_m2": 84.99, "floor": 12,
             "price_10k": 245000, "deal_date": "2024-03-15"}],
 "summary": {"median_price_10k": 230000, "min_price_10k": 180000,
             "max_price_10k": 310000, "sample_count": 42}}

// apartment/rent
// items[*] 에 deposit_10k, monthly_rent_10k, contract_type 추가
```

## 트리거 예시

```
강남구 아파트 실거래
마포구 오피스텔 전세
성수동 빌라 월세
용산구 상업업무용 매매
서초구 아파트 2024년 3월 매매
```

## 제외되는 질문 (Perplexity 로 넘어감)

- 해외 부동산 (뉴욕/도쿄/런던 등)
- 청약/분양 관련

## 응답 포맷

```
**🏢 서울특별시 강남구 아파트 매매 · 2026-03**
• 거래 42건 · 중위 23억 / 최저 18억 / 최고 31억
  - 래미안 퍼스티지 · 반포동 84.99㎡ 12층 24억 5,000만 (2024-03-15)
  - …

`국토교통부 실거래가 신고 기준`
```

## 실패 모드

- **proxy 장애/타임아웃**: `"부동산 실거래 조회 실패!"` + 에러 문자열
- **region-code 미매치**: `"'{region}' 법정동 코드를 찾지 못했다!"`
- **데이터 없음**: `"해당 지역/월 실거래 데이터가 없다!"` + 다른 월 유도

## 관련 파일

- [realestate_engine.py](../realestate_engine.py) — 로직
- `~/.agents/skills/real-estate-search/SKILL.md` — upstream k-skill 명세
