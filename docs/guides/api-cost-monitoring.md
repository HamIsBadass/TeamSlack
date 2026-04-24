# API 사용량/비용 확인 가이드

작성일: 2026-04-21
대상: TeamSlack personal-bot (쥐피티) 운영자

---

## 1. 빠른 확인 — Slack 내 `/cost`

개인 비서 봇이 메모리 기반 비용 트래커(`shared/api_cost_tracker.py`)를 사용한다. 슬랙에서 직접 호출:

```text
/cost
```

출력 예:

```text
Gemini 사용량 — 오늘(2026-04-21) $0.0084
• gemini_flash_lite: $0.0050
• gemini_flash: $0.0034
이번달(2026-04) Gemini 누적 — $0.1420

Perplexity 사용량은 대시보드에서 확인한다: console.perplexity.ai/billing
_주: Gemini 수치는 봇 재시작 시 초기화되는 인메모리 추정치다. 실 청구는 각 대시보드 기준._
```

특징:
- **Gemini 만** 내부 트래커로 실시간 표시. 본인 `user_id` 기준 **오늘(UTC) / 이번달(UTC)** 누적.
- **Perplexity 는** 내부 표시를 생략하고 공식 빌링 대시보드 링크로 위임한다.
  링크: `https://console.perplexity.ai/group/47808882/billing`
  (Perplexity 는 퍼 유저 실시간 사용량 조회 API 가 없어 대시보드가 단일 진실 원천.)
- 봇 프로세스가 재시작되면 Gemini 트래커가 0으로 초기화된다(in-memory). 월 누적도 재시작 이후부터 합산.

---

## 2. 공식 청구 대시보드 (실제 결제 기준)

### Perplexity

- URL: `https://www.perplexity.ai/settings/api` → Usage
- 확인 가능: 일별/월별 호출 수 × 모델 × 비용
- 단가: `sonar` $0.001/req + 토큰, `sonar-pro`/`sonar-reasoning` 계열은 더 높음. 실 단가는 대시보드의 최신 값이 기준.

### Gemini (Google AI Studio / Google Cloud)

- AI Studio: `https://aistudio.google.com` → API keys → Usage
- Cloud Billing: `https://console.cloud.google.com/billing` → Reports → "Generative Language API" 또는 "Vertex AI" 필터
- 단가 참고:
  - `gemini-2.5-flash-lite`: $0.10 in / $0.40 out per 1M tokens
  - `gemini-2.5-flash`: $0.30 in / $2.50 out per 1M tokens
  - `gemini-2.5-pro`: $1.25 in / $10.00 out per 1M tokens
- 단가 변경 시 `shared/api_cost_tracker.py:COST_MAPPING` 업데이트 필요.

---

## 3. 코드 내 트래커 직접 조회

관리자 디버깅용으로 singleton에 접근:

```python
from shared.api_cost_tracker import get_cost_tracker
tracker = get_cost_tracker()
print(tracker.get_daily_summary("U0XXXXXXX"))   # 특정 유저
# 세션 단위: tracker.get_session_summary(session_id)
# 요청 단위: tracker.get_request_summary(request_id)
```

---

## 4. 라우팅·단가 설계

현재 기본 라우팅(2026-04-21):

| 호출 경로 | 모델 | 비고 |
|---|---|---|
| DM/멘션 자유 대화 | `gemini-2.5-flash-lite` | 짧은 턴 기본값 |
| `/reply` 초안 | `gemini-2.5-flash-lite` (기본) → length > 800자면 flash, > 3000자면 pro | `select_gemini_model(task_type="reply_draft", doc_length=...)` |
| `/reply` 수정 | `gemini-2.5-flash` | `reply_rewrite`는 mid 티어 |
| `/summary` | `gemini-2.5-pro` | `long_summary`는 heavy 티어 |
| `/psearch` (키워드 라우팅) | `sonar` / `sonar-pro` / `sonar-reasoning` / `sonar-reasoning-pro` | `select_perplexity_model(query)` |
| `/usdtw` | `sonar-pro` | 환율 최신성 확보 |
| DM 검색 의도 | auto (키워드) | `/psearch` 와 동일 라우팅 |

변경 지점: [shared/utils/model_router.py](../../shared/utils/model_router.py) ← 라우팅 규칙 / [shared/api_cost_tracker.py](../../shared/api_cost_tracker.py) ← 단가표.

---

## 5. 트러블슈팅

| 증상 | 원인 | 대응 |
|---|---|---|
| `/cost` 가 "집계 없음" | 봇 재시작 직후 또는 호출 없음 | 정상. API 호출 1회 이상 후 재시도 |
| 추정치와 실 청구가 다름 | `COST_MAPPING` 단가가 구식 / Perplexity 는 쿼리당 과금으로 보정 중 | 대시보드 기준을 정답으로 본다. `COST_MAPPING` 업데이트 |
| 일부 호출이 집계 안 됨 | handler → helper 경로에 `user_id` 누락 | `_record_llm_cost_tokens` / `_record_llm_cost_usd` 호출부 / `user_id` 파라미터 전달 여부 확인 |
