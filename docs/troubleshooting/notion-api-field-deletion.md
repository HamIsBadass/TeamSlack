# Notion DB Schema Update Script - 원인 분석 및 수정 기록

## 문제 상황

스크립트가 API 200 응답을 반환했으나, 실제 Notion DB는 업데이트되지 않음.

```
API 응답: 200 OK ✓
실제 DB 상태: apply_url 필드 여전히 존재 ✗
```

---

## 원인 분석

### 이전 방식

```python
def remove_apply_url_field(properties: dict):
    if "apply_url" in properties:
        del properties["apply_url"]
```

**문제:**
- 필드를 Python dict에서 제거만 함
- Notion API에 전송되는 payload 자체에서 필드가 없음
- Notion API는 전송되지 않은 필드를 기존값 유지로 해석

---

### 수정된 방식

```python
def remove_apply_url_field(properties: dict):
    if "apply_url" in properties:
        properties["apply_url"] = None
```

**이유:**
- Notion API 스펙: 필드 삭제 = 필드값을 `null`로 명시적 설정
- Payload에 `"apply_url": null` 포함
- API가 `null 값 = 필드 삭제 의도`로 해석

---

## Notion API 필드 업데이트 규칙

| 작업 | 방식 | 예시 |
|---|---|---|
| 필드 추가 | `{"field_name": {type, ...}}` | `{"apply_url": {"type": "url"}}` |
| 필드 값 변경 | `{"field_name": new_value}` | `{"keywords": {"multi_select": {...}}}` |
| 필드 삭제 | `{"field_name": null}` | `{"apply_url": null}` |

---

## 수정 후 동작 확인

### 적용된 변경

- `remove_apply_url_field()` 함수: `del` -> `None` 설정으로 변경
- 주석 업데이트: Notion API requires explicitly setting field to null for deletion

### 테스트 방법

```bash
cd c:\Users\VIRNECT\Downloads\career\Private\TeamSlack
$env:NOTION_TOKEN="your-token"
uv run --python 3.11 --with requests scripts/update-db-schema.py
```

**예상 결과:**
- apply_url 필드 검출 -> `properties["apply_url"] = null` 설정
- Payload에 `"apply_url": null` 포함
- API 200 응답 + 실제 DB에서 apply_url 삭제 완료

---

## 향후 활용

이 스크립트는 다음과 같이 확장 가능합니다:

1. 필드 추가: `properties["new_field"] = {"type": "text"}`
2. 옵션 변경: keywords 옵션 추가/제거
3. 배치 실행: 여러 DB에 동일하게 적용

개발 후 테스트 시 이 포인트를 기억하면 됩니다.
