# 개인봇 스타일 가이드

> 모든 봇에 공통 적용되는 상위 규칙은 [bot-common-voice.md](bot-common-voice.md) 를 먼저 참고. 이 문서는 개인봇 **고유** 규칙만 다룬다.

이 문서는 개인봇(쥐피티🐹)의 말투/표현 규칙과 기능 범위를 확인하고 수정하기 위한 기준 문서입니다.

## 적용 대상

- 페르소나 정의: [shared/profile/personas/personal.md](../../shared/profile/personas/personal.md)
- 실행 파일: [apps/personal-bot/socket_mode_runner.py](../../apps/personal-bot/socket_mode_runner.py)
- 주요 기능: `/psearch`, `/usdtw`, `/reply`, `/summary`, DM 자유 대화, app mention 응답

## 현재 스타일 정책

- 톤: 당당하고 간결한 업무형 반말
- 종결: 기본 "~다!", 문단 말미는 "~햄.🐹"
- 보수 규칙: 마지막 문장에 "해씨(해바라기씨)" 수량 청구
- 검색 응답: Perplexity 경유 시에도 개인봇 스타일 후처리 적용

## API 호출 라우팅 (2026-04-21 기준 코드 동작)

페르소나 [personal.md](../../shared/profile/personas/personal.md) 의 "API 호출 라우팅" 섹션과 동기화 유지.

| 호출 시나리오 | 사용 API | 구현 지점 |
|---|---|---|
| `/psearch`, 검색 키워드 DM/멘션 | Perplexity (+금융 질문은 Finance 프롬프트 병용) | `_perplexity_chat_dm`, `_perplexity_search` |
| `/usdtw` (USD↔KRW 환율) | Perplexity `sonar-pro` + Finance 지침 | `handle_usdtw` |
| DM/멘션 일반 대화 (비검색) | Gemini `gemini-2.5-flash-lite` | `_gemini_chat_dm` |
| `/reply` 답장 초안 생성·수정 | Gemini `gemini-2.5-flash-lite` | `_gemini_generate_reply`, `_rewrite_reply_draft` |
| `/summary` 문서 요약 | Gemini `gemini-2.5-flash-lite` | `_gemini_generate_summary` |

검색 의도 판정은 `_looks_like_search_request()` 의 키워드·패턴 기반 휴리스틱을 따른다. 금융 질문 분기는 `_is_finance_query()`.

## 수정 포인트

### 1) 시스템 프롬프트(말투 규칙)

- 위치: [apps/personal-bot/socket_mode_runner.py](../../apps/personal-bot/socket_mode_runner.py)
- 상수: `SYSTEM_PROMPT_BASE`, `SYSTEM_PROMPT_PSEARCH`, `SYSTEM_PROMPT_PSEARCH_FINANCE`, `SYSTEM_PROMPT_PSEARCH_FORMATTED`, `SYSTEM_PROMPT_USDTW`
- 페르소나 음성 규칙 수정은 [shared/profile/personas/personal.md](../../shared/profile/personas/personal.md) 에서 수행. 런타임 반영은 프로세스 재시작 또는 `shared.profile.reload_personas()`.

### 2) 응답 후처리(개인 스타일 부착)

- 위치: [apps/personal-bot/socket_mode_runner.py](../../apps/personal-bot/socket_mode_runner.py)
- 함수: `add_gom_emojis` (호환 명칭 유지, 내부 동작은 햄스터 스타일)

### 3) 검색 질의 정제·라우팅

- 함수: `_looks_like_search_request`, `_is_finance_query`, `_extract_search_query`, `_extract_year_terms`, `_perplexity_system_prompt_for_query`, `_perplexity_chat_dm`
- 연도 표현(예: 26년, 2026년)은 검색 제약으로 우선 반영한다.
- 조건 불일치 시 임의 연도 결과를 단정하지 않도록 프롬프트를 유지한다.

### 4) Gemini 호출 지점

- 함수: `_gemini_chat_dm`, `_gemini_generate_reply`, `_rewrite_reply_draft`, `_gemini_generate_summary`
- 기본 모델은 `gemini-2.5-flash-lite`. 무거운 작업(코드 리뷰/아키텍처/장문 요약)은 `select_gemini_model()` 로 `gemini-2.5-pro` 승격을 고려.

## 빠른 점검 절차

1. 문법 검사
   ```bash
   python -m py_compile apps/personal-bot/socket_mode_runner.py
   python -m py_compile shared/utils/slack_formatter.py
   ```
2. 봇 실행
   ```bash
   python apps/personal-bot/socket_mode_runner.py
   ```
3. Slack 확인
   - DM: 검색해줘 요청 시 Perplexity 경로 + 다!/햄 스타일 유지
   - DM: 비검색 자유 대화 시 Gemini 경로 + 다!/햄 스타일 유지
   - DM: 연도 포함 검색(예: 26년 영화)에서 연도 제약 반영
   - 채널 멘션: 공개 응답에서도 개인봇 스타일 유지

## 관련 문서

- [오케스트레이터 봇 스타일 가이드](./orchestrator-bot-style.md)
- [/psearch 운영 가이드](./psearch-guideline-management.md)
- [봇 공통 음성 규칙](./bot-common-voice.md)
