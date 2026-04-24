---
name: ktx
description: KTX/Korail 좌석 조회 (korail2 라이브러리 직결). 예약/결제는 자동화하지 않음 — 조회 전용
trigger_keywords: [KTX, ktx, 케이티엑스, 코레일, 무궁화, 새마을, ITX]
---

# KTX (한국철도 Korail)

## 동작 개요

1. intent 판정: `is_ktx_query(text)` — `KTX`/`코레일`/`무궁화`/`새마을`/`ITX` 문자열 포함 시 매치
2. 힌트 추출:
   - 출발역/도착역: `_STATION_ALIASES` 사전 매칭 (서울/용산/광명 등 주요역)
   - 날짜: `오늘/내일/모레/글피` · `2026-03-28` · `3월 28일` (지난 날짜면 내년 roll)
   - 시각: `HH:MM` · `N시` · `오후 N시` → `HHMMSS`. 미지정 시 `000000`
   - 열차종: 기본 `KTX`, 텍스트에 `무궁화`/`새마을`/`ITX` 있으면 해당 타입으로
3. korail2 호출:
   - `Korail(id, pwd)` 로그인 (내부 Dynapath 토큰 자동 처리)
   - `korail.search_train(dep, arr, date, time, train_type=..., include_no_seats=True, include_waiting_list=True)` — 매진·대기 포함
4. 결과 렌더: 상위 5편 (열차종/편번호/출도착/좌석 상태)

## k-skill 통합

**활용 스킬**: `ktx-booking` (`~/.agents/skills/ktx-booking/SKILL.md`)

**라이브러리**: `korail2` + `pycryptodome` (PyPI, `pip install korail2 pycryptodome`). k-skill-proxy 미경유

**credential**:
- `KSKILL_KTX_ID`, `KSKILL_KTX_PASSWORD` 환경변수 필수
- `~/.config/k-skill/secrets.env` 에서 자동 로드 (socket_mode_runner 부팅 시)
- ID 는 보통 코레일 회원번호(10자리) 또는 이메일

**지원 역 (KTX/Korail 주요역)**:

서울 · 용산 · 영등포 · 광명 · 수원 · 평택 · 천안아산 · 오송 · 대전 · 서대전 · 김천구미 · 동대구 · 신경주 · 울산 · 부산 · 부전 · 익산 · 정읍 · 광주송정 · 목포 · 여수엑스포 · 순천 · 전주 · 강릉 · 평창 · 진부 · 춘천

축약 매핑: 천안/아산→천안아산, 김천/구미→김천구미, 대구→동대구, 경주→신경주, 광주/송정리→광주송정, 여수→여수엑스포

## 트리거 예시

```
KTX 서울 부산 내일 9시
KTX 용산에서 광주송정 오늘 오전 10시
KTX 서울 강릉 2026-05-10 14:30
코레일 서울 부산 모레
무궁화 청량리 안동 내일 8시
```

## 예약 자동화 안 하는 이유

1. k-skill SKILL.md 정책: "결제 완료까지는 자동화하지 않는다"
2. 예약은 side-effecting → 사용자 확인 없이 실행 위험
3. Korail Dynapath anti-bot 정책 변경 시 잠금 가능성 존재

## 응답 포맷

```
**🚆 KTX 서울 → 부산 · 2026-05-10**
• 18편 조회 (상위 5편)
  - KTX 101편 · 05:30 → 08:10 · 일반 O · 특실 O
  - KTX 산천 103편 · 06:00 → 08:41 · 일반 O
  - KTX 105편 · 07:00 → 09:41 · 매진(대기가능)
  - ...

`실결제는 코레일톡/레츠코레일에서 직접 — 조회 전용`
```

## 실패 모드

- **KSKILL_KTX_ID/PASSWORD 미설정**: 안내 후 secrets.env 편집 유도
- **korail2/pycryptodome 미설치**: `pip install korail2 pycryptodome` 안내
- **로그인 실패**: `KTX 로그인 실패!` + 예외 문자열
- **Dynapath anti-bot (MACRO ERROR)**: 전용 안내 — "잠시 후 다시 시도. 반복되면 코레일톡 앱 접속 후 재시도"
- **매진**: 결과에 `매진(대기가능)` 표기로 노출

## 관련 파일

- [ktx_engine.py](../ktx_engine.py) — 로직
- `~/.agents/skills/ktx-booking/SKILL.md` — upstream k-skill 명세
