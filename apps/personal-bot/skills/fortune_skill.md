---
name: fortune
description: 일진·사주·별자리 기반 오늘의 운세. 프로필 레지스트리에서 대상자 정보 매칭, Gemini structured output 으로 5종 운세 + 행운 색/숫자 생성
trigger_keywords: [운세, 사주, 오늘의 점, 오늘 점괘, 점괘]
---

# Fortune (운세)

## 동작 개요

1. intent 판정: `is_fortune_query(text)` — 키워드 포함 검사
2. 대상자 해결 순서:
   - 텍스트에 `"이유송 운세"` 같은 명시 이름 → `extract_fortune_target` → `resolve_profile` (alias/trailing particle 스트립 포함)
   - 명시 없으면 Slack display_name 부분일치 — 3글자 풀네임만 (예: `2D팀_이유송_연구원` → 이유송)
   - 둘 다 실패하면 대화형 등록 플로우 (pending registration, TTL 10분)
3. 운세 생성: 오늘 일진(JDN 공식) + 사용자 일간 오행관계 + 요일 지배 행성 + 별자리 힌트 → Gemini 2.5 Flash Lite structured output (JSON schema 강제) → 총운/애정/재물/업무/건강 별점+한줄 + 행운 색·숫자 + 한마디

## 데이터 출처

- **Gemini 2.5 Flash Lite** (`response_schema` 강제): 운세 문장 생성. k-skill-proxy 경유 안 함 — 직접 Gemini API 호출
- **일진 계산**: 로컬 JDN 공식. 만세력 기준 `2000-01-01 = 戊午일` 검증됨
- **프로필 레지스트리**: `apps/personal-bot/fortune_profiles.json` — 생년월일·띠·별자리·일간 저장
- **외부 의존성**: `GEMINI_API_KEY` env 만 필요. k-skill-proxy 미필요

## k-skill 통합 상태

**연동 없음.** 운세는 외부 데이터가 아니라 로컬 계산 + Gemini 문장 생성만 쓴다. k-skill-proxy `KSKILL_PROXY_BASE_URL` 과 무관하게 동작. 따라서 이 스킬은 k-skill 카테고리에 해당하지 않고, 쥐피티 내부 고유 기능으로 분류.

## 트리거 예시

```
오늘 운세
이유송 운세 알려줘
사주 어때
지은이 오늘 점괘
```

## 멀티턴 (pending registration)

미등록 대상자가 질의되면 런너의 skill 루프 밖에서 **선행 게이트**로 처리:

- `has_pending_registration(user_id)` → DM 응답을 등록 폼으로 해석
- `is_profile_update_request(text)` → 프로필 수정 플로우 진입

이 두 게이트는 stateful 라서 skill registry 매칭보다 먼저 실행된다. 이들이 처리하지 않은 경우에만 일반 `matches()` 루프가 돈다.

## 응답 포맷 (Slack)

```
🔮 2026-04-22 수요일 오늘의 운세
`이유송 · 99년 토끼띠(기묘생) · 양자리 · 일간 을목(乙)`

• 총운 ★★★☆☆ — …
• 애정운 ★★★★☆ — …
• 재물운 ★★★☆☆ — …
• 업무운 ★★★★★ — …
• 건강운 ★★★☆☆ — …

🎨 행운의 색 녹색 · 연두색
🔢 행운의 숫자 3 · 8

📜 한마디 …
```

## 실패 모드

- `GEMINI_API_KEY` 미설정 → `"운세 생성에 실패했다"`
- Gemini API 에러/타임아웃 → 동일
- 프로필 일간 없음 → 오행 관계 힌트 스킵, 그대로 진행
- Slack display_name 에서 동일 3글자 이름 동시 매칭 → 모호성 안내

## 관련 파일

- [fortune_engine.py](../fortune_engine.py) — 로직
- [fortune_profiles.json](../fortune_profiles.json) — 레지스트리
