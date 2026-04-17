# Notion Database API - 필드 조작 지침

이 문서는 Notion API를 사용하여 데이터베이스 필드를 생성, 수정, 삭제하는 방법을 설명합니다.  
향후 새로운 데이터베이스를 만들거나 기존 DB를 수정할 때 참고하세요.

---

## 목차

1. API 기본 설정
2. 필드 생성 (Create)
3. 필드 수정 (Update)
4. 필드 삭제 (Delete)
5. 실제 예제
6. 주의사항 및 Best Practice
7. 자동입력 누락 대응 로직
8. 트러블슈팅

---

## API 기본 설정

### 필수 정보

```python
NOTION_TOKEN = "ntn_..."
DATABASE_ID = "xxxxxxxx-xxxx-..."

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

NOTION_API_URL = "https://api.notion.com/v1"
```

### API 엔드포인트

```
PATCH https://api.notion.com/v1/databases/{DATABASE_ID}
```

---

## 필드 생성 (Create)

### 기본 구조

```python
payload = {
    "properties": {
        "필드명": {
            "type": "필드타입"
        }
    }
}
```

### 지원 필드 타입

#### 1. 텍스트 타입

```python
"field_name": {"type": "rich_text"}
"url_field": {"type": "url"}
"email_field": {"type": "email"}
"phone_field": {"type": "phone_number"}
```

#### 2. 선택 타입

```python
"status": {
    "type": "select",
    "select": {
        "options": [
            {"name": "Not Started", "color": "red"},
            {"name": "In Progress", "color": "yellow"},
            {"name": "Done", "color": "green"}
        ]
    }
}

"keywords": {
    "type": "multi_select",
    "multi_select": {
        "options": [
            {"name": "전시", "color": "purple"},
            {"name": "공연", "color": "pink"},
            {"name": "축제", "color": "green"}
        ]
    }
}
```

#### 3. 날짜/시간 타입

```python
"date_field": {"type": "date"}
"datetime_field": {"type": "date"}
```

#### 4. 체크박스

```python
"is_done": {"type": "checkbox"}
```

#### 5. 숫자

```python
"count": {"type": "number"}
```

#### 6. 제목

```python
"title": {"type": "title"}
```

---

## 필드 수정 (Update)

### 옵션 추가/제거

```python
payload = {
    "properties": {
        "keywords": {
            "type": "multi_select",
            "multi_select": {
                "options": [
                    {"name": "전시", "color": "purple"},
                    {"name": "공연", "color": "pink"},
                    {"name": "축제", "color": "green"},
                    {"name": "체험", "color": "yellow"}
                ]
            }
        }
    }
}
```

### 필드 이름 변경

Notion API는 필드명 변경을 지원하지 않습니다. 새 필드 생성 후 마이그레이션하거나 기존 필드를 삭제하세요.

---

## 필드 삭제 (Delete)

필드를 삭제하려면 명시적으로 `null`로 설정해야 합니다.

```python
payload = {
    "properties": {
        "필드명": None
    }
}
```

---

## 실제 예제

```python
import os
import requests

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
DATABASE_ID = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

payload = {
    "properties": {
        "title": {"type": "title"},
        "source_url": {"type": "url"},
        "keywords": {
            "type": "multi_select",
            "multi_select": {
                "options": [
                    {"name": "전시", "color": "purple"},
                    {"name": "공연", "color": "pink"},
                    {"name": "축제", "color": "green"},
                    {"name": "체험", "color": "yellow"}
                ]
            }
        },
        "memo": {"type": "rich_text"},
        "date": {"type": "date"},
        "autofilled": {"type": "checkbox"},
        "last_autofill_at": {"type": "date"},
        "error": {"type": "rich_text"}
    }
}

url = f"https://api.notion.com/v1/databases/{DATABASE_ID}"
response = requests.patch(url, headers=HEADERS, json=payload)

if response.status_code == 200:
    print("✓ 필드 추가 성공")
else:
    print(f"❌ 오류: {response.text}")
```

---

## 주의사항

- 필드 삭제는 `null`로 해야 합니다.
- unknown 값은 추측하지 않습니다.
- 각 DB의 필드명과 허용값은 개별 가이드에 정의합니다.
